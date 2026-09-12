import sqlite3
import time
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from urllib.parse import urlsplit

from .adapters import ADAPTERS
from .db import save_source

PER_HOST_WORKERS = 2


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
    now = datetime.now(timezone.utc).isoformat()
    sources = database.execute(
        "SELECT id, provider, url FROM sources "
        "WHERE next_sync_at IS NULL OR next_sync_at <= ? ORDER BY next_sync_at, id", (now,),
    ).fetchall()
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
    return succeeded, len(sources) - succeeded
