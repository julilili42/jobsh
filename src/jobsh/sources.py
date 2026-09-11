import sqlite3
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from itertools import islice

from .jobs import save_jobs
from .adapters import ADAPTERS


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
    try:
        adapter = ADAPTERS.get(provider)
        if adapter is None:
            raise ValueError(f"unknown provider: {provider}")
        return source_id, started_at, started, adapter.fetch_records(url, timeout), None
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
            database.execute(
                "UPDATE sources SET last_success_at = ? WHERE id = ?", (finished_at, source_id),
            )
            _record_sync(database, source_id, started_at, finished_at, started, counts)
    except (KeyError, ValueError, OSError, sqlite3.Error) as error:
        finished_at = datetime.now(timezone.utc).isoformat()
        with database:
            _record_sync(database, source_id, started_at, finished_at, started, error=error)
        return False
    return True


def sync(database: sqlite3.Connection, timeout: float, workers: int = 32) -> tuple[int, int]:
    if timeout <= 0 or workers < 1:
        raise ValueError("timeout and workers must be > 0")
    sources = database.execute("SELECT id, provider, url FROM sources ORDER BY id").fetchall()
    remaining = iter(sources)
    succeeded = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = {pool.submit(_fetch_source, source, timeout)
                   for source in islice(remaining, workers)}
        while pending:
            completed, pending = wait(pending, return_when=FIRST_COMPLETED)
            for future in completed:
                succeeded += _save_source(database, *future.result())
                source = next(remaining, None)
                if source is not None:
                    pending.add(pool.submit(_fetch_source, source, timeout))
    return succeeded, len(sources) - succeeded
