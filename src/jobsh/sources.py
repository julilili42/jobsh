import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import partial

from .jobs import save_jobs
from .personio_feed import fetch_records

ADAPTERS = {"personio": fetch_records}


def register_source(
    database: sqlite3.Connection,
    provider: str,
    account: str,
    url: str,
    discovery: str,
    discovered_at: str | None = None,
) -> None:
    database.execute(
        "INSERT INTO companies (name) VALUES (?) ON CONFLICT (name) DO NOTHING",
        (account,),
    )
    database.execute(
        """
        INSERT INTO sources
            (company_id, provider, provider_account, url, discovery, discovered_at)
        VALUES ((SELECT id FROM companies WHERE name = ?), ?, ?, ?, ?, ?)
        ON CONFLICT (provider, provider_account) DO UPDATE SET
            url = excluded.url,
            discovery = excluded.discovery,
            discovered_at = COALESCE(excluded.discovered_at, sources.discovered_at)
        """,
        (account, provider, account, url, discovery, discovered_at),
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


def _fetch_source(source: sqlite3.Row, timeout: float):
    source_id, provider, url = source
    started_at = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    adapter = ADAPTERS.get(provider)
    if adapter is None:
        return source_id, started_at, started, [], ValueError(f"unknown provider: {provider}")
    try:
        return source_id, started_at, started, adapter(url, timeout), None
    except (OSError, ValueError) as error:
        return source_id, started_at, started, [], error


def _save_source(
    database: sqlite3.Connection,
    source_id: int,
    started_at: str,
    started: float,
    records: list[dict[str, str | None]],
    error: Exception | None,
) -> bool:
    finished_at = datetime.now(timezone.utc).isoformat()
    if error is not None:
        with database:
            _record_sync(database, source_id, started_at, finished_at, started, error=error)
        return False
    try:
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
    except (KeyError, ValueError, sqlite3.Error) as error:
        finished_at = datetime.now(timezone.utc).isoformat()
        with database:
            _record_sync(database, source_id, started_at, finished_at, started, error=error)
        return False
    return True


def sync(database: sqlite3.Connection, timeout: float, workers: int = 32) -> tuple[int, int]:
    if timeout <= 0 or workers < 1:
        raise ValueError("timeout and workers must be > 0")
    sources = database.execute("SELECT id, provider, url FROM sources ORDER BY id").fetchall()
    fetch_source = partial(_fetch_source, timeout=timeout)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        fetched = pool.map(fetch_source, sources)
        succeeded = sum(_save_source(database, *result) for result in fetched)
    return succeeded, len(sources) - succeeded
