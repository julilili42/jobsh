import sqlite3
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from itertools import islice

from .adapters import ADAPTERS
from .db import save_source


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
                succeeded += save_source(database, *future.result())
                source = next(remaining, None)
                if source is not None:
                    pending.add(pool.submit(_fetch_source, source, timeout))
    return succeeded, len(sources) - succeeded
