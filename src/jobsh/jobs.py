import sqlite3
import time
from datetime import datetime, timezone

from .classification import classify
from .personio_feed import fetch_records

JOB_FIELDS = (
    "title", "description", "locations", "location_text", "work_mode", "employment_type",
    "original_url", "german_eligibility_evidence", "published_at", "content_hash", "raw_record",
    "source_category", "it_classification", "classification_rule",
)
UPSERT_JOB = f"""
    INSERT INTO jobs (source_id, external_id, first_seen_at, last_seen_at, {', '.join(JOB_FIELDS)})
    VALUES (:source_id, :external_id, :seen_at, :seen_at, {', '.join(':' + name for name in JOB_FIELDS)})
    ON CONFLICT (source_id, external_id) DO UPDATE SET
        last_seen_at = :seen_at, missing_imports = 0, closed_at = NULL,
        {', '.join(f'{name} = excluded.{name}' for name in JOB_FIELDS)}
"""


def register_feed(
    database: sqlite3.Connection,
    account: str,
    url: str,
    discovery: str,
    discovered_at: str | None = None,
) -> None:
    """Register or update a Personio feed."""
    database.execute(
        "INSERT INTO companies (name) VALUES (?) ON CONFLICT (name) DO NOTHING",
        (account,),
    )
    database.execute(
        """
        INSERT INTO sources
            (company_id, provider, provider_account, url, discovery, discovered_at)
        VALUES ((SELECT id FROM companies WHERE name = ?), 'personio', ?, ?, ?, ?)
        ON CONFLICT (provider, provider_account) DO UPDATE SET
            url = excluded.url,
            discovery = excluded.discovery,
            discovered_at = COALESCE(excluded.discovered_at, sources.discovered_at)
        """,
        (account, account, url, discovery, discovered_at),
    )


def save_jobs(
    database: sqlite3.Connection,
    source_id: int,
    records: list[dict[str, str | None]],
    seen_at: str,
) -> tuple[int, int, int]:
    created = unchanged = 0
    for record in records:
        existing = database.execute(
            "SELECT content_hash FROM jobs WHERE source_id = ? AND external_id = ?",
            (source_id, record["external_id"]),
        ).fetchone()
        classification, rule = classify(
            record["title"], record.get("description") or "", record.get("source_category") or ""
        )
        database.execute(UPSERT_JOB, record | {
            "source_id": source_id, "seen_at": seen_at,
            "source_category": record.get("source_category"),
            "it_classification": classification, "classification_rule": rule,
        })
        if existing is None:
            created += 1
        elif existing["content_hash"] == record["content_hash"]:
            unchanged += 1
    return created, len(records) - created - unchanged, unchanged


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


def sync(database: sqlite3.Connection, timeout: float) -> tuple[int, int]:
    sources = database.execute(
        "SELECT id, url FROM sources WHERE provider = 'personio' ORDER BY id"
    ).fetchall()
    succeeded = 0
    for source_id, url in sources:
        started_at = datetime.now(timezone.utc).isoformat()
        started = time.monotonic()
        try:
            records = fetch_records(url, timeout)
            finished_at = datetime.now(timezone.utc).isoformat()
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
                database.execute(
                    "UPDATE sources SET last_success_at = ? WHERE id = ?", (finished_at, source_id),
                )
                _record_sync(database, source_id, started_at, finished_at, started, counts)
        except (OSError, ValueError, sqlite3.Error) as error:
            finished_at = datetime.now(timezone.utc).isoformat()
            with database:
                _record_sync(database, source_id, started_at, finished_at, started, error=error)
        else:
            succeeded += 1
    return succeeded, len(sources) - succeeded
