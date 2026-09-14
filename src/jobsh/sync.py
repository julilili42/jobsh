import sqlite3
import time
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import UTC, datetime
from urllib.parse import urlsplit

from .adapters import ADAPTERS
from .db import save_source

PER_HOST_WORKERS = 8
SOURCE_BATCH = 1_000


def _fetch_source(source: sqlite3.Row, timeout: float):
    source_id, provider, url = source
    started_at = datetime.now(UTC).isoformat()
    started = time.monotonic()
    try:
        adapter = ADAPTERS.get(provider)
        if adapter is None:
            raise ValueError(f"unknown provider: {provider}")
        return source_id, started_at, started, adapter.fetch_records(url, timeout), None
    except (OSError, ValueError) as error:
        return source_id, started_at, started, [], error


def _due_sources(database: sqlite3.Connection, now: str, limit: int) -> list[sqlite3.Row]:
    return database.execute(
        "SELECT id, provider, url FROM sources "
        "WHERE next_sync_at IS NULL OR next_sync_at <= ? ORDER BY next_sync_at, id LIMIT ?",
        (now, limit),
    ).fetchall()


def _sync_sources(
    database: sqlite3.Connection, sources: list[sqlite3.Row], timeout: float, workers: int,
) -> int:
    hosts: dict[str, deque[sqlite3.Row]] = {}
    for source in sources:
        try:
            host = urlsplit(source["url"]).hostname or ""
        except ValueError:
            host = source["url"]
        hosts.setdefault(host, deque()).append(source)
    ready = deque(hosts)
    queued = set(ready)
    active = dict.fromkeys(hosts, 0)
    succeeded = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = {}
        while ready or pending:
            while ready and len(pending) < workers:
                host = ready.popleft()
                queued.remove(host)
                pending[pool.submit(_fetch_source, hosts[host].popleft(), timeout)] = host
                active[host] += 1
                if hosts[host] and active[host] < PER_HOST_WORKERS:
                    ready.append(host)
                    queued.add(host)
            completed, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in completed:
                host = pending.pop(future)
                active[host] -= 1
                succeeded += save_source(database, *future.result())
                if hosts[host] and host not in queued:
                    ready.append(host)
                    queued.add(host)
    return succeeded


def sync(
    database: sqlite3.Connection, timeout: float, workers: int = 32, limit: int = 0,
) -> tuple[int, int]:
    if timeout <= 0 or workers < 1 or limit < 0:
        raise ValueError("timeout and workers must be > 0; limit must be >= 0")
    now = datetime.now(UTC).isoformat()
    succeeded = total = 0
    while not limit or total < limit:
        sources = _due_sources(database, now, min(SOURCE_BATCH, limit - total) if limit else SOURCE_BATCH)
        if not sources:
            break
        total += len(sources)
        succeeded += _sync_sources(database, sources, timeout, workers)
    return succeeded, total - succeeded
