import json
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from itertools import batched
from pathlib import Path

MIGRATION = Path(__file__).with_name("migrations") / "001_initial.sql"
JOB_FIELDS = (
    "title", "description", "locations", "location_text", "work_mode", "employment_type",
    "original_url", "published_at", "content_hash", "raw_record", "source_category",
)
JOB_UPDATES = ", ".join(
    "description = COALESCE(excluded.description, jobs.description)"
    if name == "description" else f"{name} = excluded.{name}" for name in JOB_FIELDS
)
UPSERT_JOB = f"""
    INSERT INTO jobs (source_id, external_id, first_seen_at, last_seen_at, {', '.join(JOB_FIELDS)})
    VALUES (:source_id, :external_id, :seen_at, :seen_at, {', '.join(':' + name for name in JOB_FIELDS)})
    ON CONFLICT (source_id, external_id) DO UPDATE SET
        last_seen_at = :seen_at, missing_imports = 0, closed_at = NULL,
        {JOB_UPDATES}
"""


def connect(path: str | Path) -> sqlite3.Connection:
    database = sqlite3.connect(path)
    database.row_factory = sqlite3.Row
    database.execute("PRAGMA foreign_keys = ON")
    database.execute("PRAGMA journal_mode = WAL")
    database.executescript(MIGRATION.read_text())
    with database:
        database.execute("BEGIN IMMEDIATE")
        for table, additions in {
            "jobs": (
                ("missing_imports", "INTEGER NOT NULL DEFAULT 0 CHECK (missing_imports >= 0)"),
                ("source_category", "TEXT"),
            ),
            "sources": (
                ("next_sync_at", "TEXT"),
                ("failure_count", "INTEGER NOT NULL DEFAULT 0 CHECK (failure_count >= 0)"),
            ),
        }.items():
            columns = {row["name"] for row in database.execute(f"PRAGMA table_info({table})")}
            for name, definition in additions:
                if name not in columns:
                    database.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
        database.execute("CREATE INDEX IF NOT EXISTS sources_due ON sources(next_sync_at)")
    for table, migration in (
        ("jobs_fts", "002_search.sql"),
        ("jobs_filter_fts", "003_filter_search.sql"),
    ):
        if database.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (table,)).fetchone():
            continue
        database.executescript(
            "BEGIN IMMEDIATE;\n" + MIGRATION.with_name(migration).read_text() + "\nCOMMIT;"
        )
    return database


def connect_readonly(path: str | Path) -> sqlite3.Connection:
    database = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    database.row_factory = sqlite3.Row
    return database


def register_source(
    database: sqlite3.Connection, provider: str, account: str, url: str,
    discovery: str, discovered_at: str | None = None,
) -> int:
    database.execute("INSERT INTO companies (name) VALUES (?) ON CONFLICT (name) DO NOTHING", (account,))
    source_id = database.execute(
        """INSERT INTO sources
            (company_id, provider, provider_account, url, discovery, discovered_at)
        VALUES ((SELECT id FROM companies WHERE name = ?), ?, ?, ?, ?, ?)
        ON CONFLICT (provider, provider_account) DO UPDATE SET
            next_sync_at = CASE WHEN sources.url <> excluded.url THEN NULL ELSE sources.next_sync_at END,
            failure_count = CASE WHEN sources.url <> excluded.url THEN 0 ELSE sources.failure_count END,
            url = excluded.url,
            discovery = excluded.discovery,
            discovered_at = COALESCE(excluded.discovered_at, sources.discovered_at)
        RETURNING id""",
        (account, provider, account, url, discovery, discovered_at),
    ).fetchone()[0]
    database.execute(
        "DELETE FROM discovery_candidates WHERE provider = ? AND account = ?",
        (provider, account),
    )
    return source_id


def checkpoint_discovery(
    database: sqlite3.Connection, provider: str, candidates: list[tuple[str, str]], states: dict[str, dict],
) -> None:
    now = datetime.now(UTC).isoformat()
    database.executemany(
        """INSERT INTO discovery_candidates (provider, account, url, discovered_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (provider, account) DO UPDATE SET
            retry_at = CASE WHEN url <> excluded.url THEN NULL ELSE retry_at END,
            error = CASE WHEN url <> excluded.url THEN NULL ELSE error END,
            url = excluded.url""",
        ((provider, account, url, now) for account, url in candidates),
    )
    database.executemany(
        "INSERT OR REPLACE INTO discovery_state VALUES (?, ?)",
        ((domain, json.dumps(state)) for domain, state in states.items()),
    )


def queue_candidates(
    database: sqlite3.Connection, provider: str, limit: int, retries: bool | None = None,
) -> list[tuple[str, str]]:
    now = datetime.now(UTC).isoformat()
    retry_filter = "" if retries is None else " AND retry_at IS " + ("NOT NULL" if retries else "NULL")
    rows = database.execute(
        """SELECT account, url FROM discovery_candidates AS candidate
        WHERE provider = ? AND (retry_at IS NULL OR retry_at <= ?)
        """ + retry_filter + """
          AND NOT EXISTS (
              SELECT 1 FROM sources
              WHERE provider = candidate.provider AND provider_account = candidate.account
          )
        ORDER BY retry_at IS NOT NULL, discovered_at, account
        LIMIT ?""",
        (provider, now, limit or -1),
    )
    return [(row["account"], row["url"]) for row in rows]


def fail_candidate(
    database: sqlite3.Connection, provider: str, account: str, error: Exception,
) -> None:
    retry_at = (datetime.now(UTC) + (
        timedelta(minutes=5) if isinstance(error, OSError) else timedelta(days=1)
    )).isoformat()
    database.execute(
        """UPDATE discovery_candidates
        SET retry_at = ?, error = ?
        WHERE provider = ? AND account = ?""",
        (retry_at, str(error), provider, account),
    )


def save_jobs(
    database: sqlite3.Connection, source_id: int,
    records: list[dict[str, str | None]], seen_at: str,
) -> tuple[int, int, int]:
    existing = {
        row["external_id"]: (row["content_hash"], row["title"])
        for row in database.execute(
            "SELECT external_id, content_hash, title FROM jobs WHERE source_id = ?", (source_id,),
        )
    }
    created = updated = 0
    changed, unchanged = [], []
    for record in records:
        values = record | {
            "source_id": source_id, "seen_at": seen_at, "source_category": record.get("source_category"),
        }
        previous = existing.get(record["external_id"])
        if previous == (record["content_hash"], record["title"]):
            unchanged.append((seen_at, source_id, record["external_id"]))
            continue
        changed.append(values)
        if previous is None:
            created += 1
        else:
            updated += 1
    database.executemany(UPSERT_JOB, changed)
    for batch in batched(unchanged, 500):
        database.execute(
            "UPDATE jobs SET last_seen_at = ?, missing_imports = 0, closed_at = NULL "
            "WHERE source_id = ? AND external_id IN (" + ", ".join("?" for _ in batch) + ")",
            (seen_at, source_id, *(external_id for _, _, external_id in batch)),
        )
    return created, updated, len(unchanged)


def _consolidate_jobvite_jobs(database: sqlite3.Connection, source_id: int, closed_at: str) -> None:
    source = database.execute(
        "SELECT provider, provider_account, url FROM sources WHERE id = ?", (source_id,),
    ).fetchone()
    if source is None or source["provider"] != "jobvite" or source["url"] != f"https://jobs.jobvite.com/{source['provider_account']}":
        return
    prefix = f"https://jobs.jobvite.com/{source['provider_account']}/job/"
    legacy_sources = "provider = 'jobvite' AND id <> ? AND instr(replace(url, 'http://', 'https://'), ?) = 1"
    database.execute(
        """UPDATE jobs AS legacy SET closed_at = ?
        WHERE legacy.closed_at IS NULL
          AND legacy.source_id IN (
              SELECT id FROM sources
              WHERE """ + legacy_sources + """
          )""",
        (closed_at, source_id, prefix),
    )
    # ponytail: sentinel avoids a schema migration; add disabled_at if sources need re-enabling.
    database.execute(
        "UPDATE sources SET next_sync_at = '9999-12-31T23:59:59+00:00' WHERE " + legacy_sources,
        (source_id, prefix),
    )


def _record_sync(
    database: sqlite3.Connection, source_id: int, started_at: str, finished_at: str,
    started: float, counts: tuple[int, int, int] = (0, 0, 0), error: Exception | None = None,
) -> None:
    database.execute(
        """INSERT INTO sync_runs (
            source_id, started_at, finished_at, status, created_count,
            updated_count, unchanged_count, duration_ms, error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (source_id, started_at, finished_at, "failed" if error is not None else "succeeded",
         *counts, round((time.monotonic() - started) * 1000), str(error) if error is not None else None),
    )


def save_source(
    database: sqlite3.Connection,
    source_id: int,
    started_at: str,
    started: float,
    records: list[dict[str, str | None]],
    error: Exception | None,
) -> bool:
    finished = datetime.now(UTC)
    finished_at = finished.isoformat()
    try:
        if error is not None:
            raise error
        with database:
            database.execute(
                "UPDATE jobs SET missing_imports = missing_imports + 1 "
                "WHERE source_id = ? AND closed_at IS NULL", (source_id,),
            )
            counts = save_jobs(database, source_id, records, finished_at)
            _consolidate_jobvite_jobs(database, source_id, finished_at)
            database.execute(
                "UPDATE jobs SET closed_at = ? "
                "WHERE source_id = ? AND missing_imports >= 2 AND closed_at IS NULL",
                (finished_at, source_id),
            )
            interval = timedelta(hours=1 if counts[0] or counts[1] else 6)
            database.execute(
                "UPDATE sources SET last_success_at = ?, next_sync_at = ?, failure_count = 0 WHERE id = ?",
                (finished_at, (finished + interval).isoformat(), source_id),
            )
            _record_sync(database, source_id, started_at, finished_at, started, counts)
    except (KeyError, ValueError, OSError, sqlite3.Error) as failure:
        finished = datetime.now(UTC)
        finished_at = finished.isoformat()
        with database:
            failures = database.execute(
                "SELECT failure_count FROM sources WHERE id = ?", (source_id,),
            ).fetchone()[0] + 1
            retry = timedelta(minutes=min(5 * 2 ** min(failures - 1, 7), 360))
            database.execute(
                "UPDATE sources SET next_sync_at = ?, failure_count = ? WHERE id = ?",
                ((finished + retry).isoformat(), failures, source_id),
            )
            _record_sync(database, source_id, started_at, finished_at, started, error=failure)
        return False
    return True
