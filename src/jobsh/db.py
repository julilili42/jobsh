import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

MIGRATION = Path(__file__).parents[2] / "migrations" / "001_initial.sql"
JOB_FIELDS = (
    "title", "description", "locations", "location_text", "work_mode", "employment_type",
    "original_url", "published_at", "content_hash", "raw_record", "source_category",
)
UPSERT_JOB = f"""
    INSERT INTO jobs (source_id, external_id, first_seen_at, last_seen_at, {', '.join(JOB_FIELDS)})
    VALUES (:source_id, :external_id, :seen_at, :seen_at, {', '.join(':' + name for name in JOB_FIELDS)})
    ON CONFLICT (source_id, external_id) DO UPDATE SET
        last_seen_at = :seen_at, missing_imports = 0, closed_at = NULL,
        {', '.join(f'{name} = excluded.{name}' for name in JOB_FIELDS)}
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
    if not database.execute("SELECT 1 FROM sqlite_master WHERE name = 'jobs_fts'").fetchone():
        database.executescript(
            "BEGIN IMMEDIATE;\n" + MIGRATION.with_name("002_search.sql").read_text() + "\nCOMMIT;"
        )
    return database


def register_source(
    database: sqlite3.Connection, provider: str, account: str, url: str,
    discovery: str, discovered_at: str | None = None,
) -> None:
    database.execute("INSERT INTO companies (name) VALUES (?) ON CONFLICT (name) DO NOTHING", (account,))
    database.execute(
        """INSERT INTO sources
            (company_id, provider, provider_account, url, discovery, discovered_at)
        VALUES ((SELECT id FROM companies WHERE name = ?), ?, ?, ?, ?, ?)
        ON CONFLICT (provider, provider_account) DO UPDATE SET
            next_sync_at = CASE WHEN sources.url <> excluded.url THEN NULL ELSE sources.next_sync_at END,
            failure_count = CASE WHEN sources.url <> excluded.url THEN 0 ELSE sources.failure_count END,
            url = excluded.url,
            discovery = excluded.discovery,
            discovered_at = COALESCE(excluded.discovered_at, sources.discovered_at)""",
        (account, provider, account, url, discovery, discovered_at),
    )
    database.execute(
        "DELETE FROM discovery_candidates WHERE provider = ? AND account = ?",
        (provider, account),
    )


def queue_candidates(
    database: sqlite3.Connection, provider: str, candidates: list[tuple[str, str]], limit: int,
) -> list[tuple[str, str]]:
    now = datetime.now(timezone.utc).isoformat()
    database.executemany(
        """INSERT INTO discovery_candidates (provider, account, url, discovered_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (provider, account) DO UPDATE SET
            retry_at = CASE WHEN url <> excluded.url THEN NULL ELSE retry_at END,
            error = CASE WHEN url <> excluded.url THEN NULL ELSE error END,
            url = excluded.url""",
        ((provider, account, url, now) for account, url in candidates),
    )
    rows = database.execute(
        """SELECT account, url FROM discovery_candidates AS candidate
        WHERE provider = ? AND (retry_at IS NULL OR retry_at <= ?)
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
    retry_at = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
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
        row["external_id"]: row
        for row in database.execute(
            f"SELECT external_id, {', '.join(JOB_FIELDS)} FROM jobs WHERE source_id = ?", (source_id,),
        )
    }
    created = updated = 0
    unchanged = []
    for record in records:
        values = record | {
            "source_id": source_id, "seen_at": seen_at, "source_category": record.get("source_category"),
        }
        previous = existing.get(record["external_id"])
        if previous is not None and all(previous[name] == values[name] for name in JOB_FIELDS):
            unchanged.append((seen_at, source_id, record["external_id"]))
            continue
        database.execute(UPSERT_JOB, values)
        if previous is None:
            created += 1
        else:
            updated += 1
    database.executemany(
        "UPDATE jobs SET last_seen_at = ?, missing_imports = 0, closed_at = NULL "
        "WHERE source_id = ? AND external_id = ?", unchanged,
    )
    return created, updated, len(unchanged)


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
    finished = datetime.now(timezone.utc)
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
    except (KeyError, ValueError, OSError, sqlite3.Error) as error:
        finished = datetime.now(timezone.utc)
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
            _record_sync(database, source_id, started_at, finished_at, started, error=error)
        return False
    return True
