import json
import sqlite3
import sys
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import partial
from urllib.parse import urlencode

from .http import HTTPStatusError, fetch
from .adapters import ADAPTERS, Adapter
from .db import fail_candidate, queue_candidates

COLLECTIONS_URL = "https://index.commoncrawl.org/collinfo.json"
RETRYABLE_INDEX_ERRORS = {400, 408, 425, 500, 502, 504}


def _read_json(url: str, timeout: float, *, lines: bool = False):
    for attempt in range(3):
        try:
            data = fetch(url, timeout)
            return [json.loads(line) for line in data.splitlines()] if lines else json.loads(data)
        except (json.JSONDecodeError, OSError) as error:
            if isinstance(error, HTTPStatusError) and error.status_code not in RETRYABLE_INDEX_ERRORS:
                raise
            if attempt == 2:
                if isinstance(error, OSError):
                    raise
                raise ValueError(f"invalid Common Crawl JSON from {url}: {error}") from error
            time.sleep(attempt + 1)


def records(domain: str, timeout: float, state: dict | None = None, collection_count: int = 1):
    if collection_count < 1:
        raise ValueError("collections must be > 0")
    collections = sorted(_read_json(COLLECTIONS_URL, timeout), key=lambda item: item["to"], reverse=True)
    state = state if state is not None else {}
    cursors = state.setdefault("collections", {})
    endpoints = {item["cdx-api"] for item in collections}
    if not cursors and state.get("endpoint") in endpoints:
        cursors[state["endpoint"]] = {"page": state.get("page", 0), "offset": state.get("offset", 0)}
    elif cursors and state.get("endpoint") not in cursors:
        cursors.clear()
    query = {"url": domain, "matchType": "domain", "filter": "status:200",
             "output": "json", "pageSize": 1}
    last_error = None
    selected = []
    for collection in collections:
        endpoint = collection["cdx-api"]
        try:
            pages = _read_json(f"{endpoint}?{urlencode(query | {'showNumPages': 'true'})}", timeout)["pages"]
            selected.append((endpoint, pages))
            if len(selected) == collection_count:
                break
        except HTTPStatusError as error:
            if error.status_code not in RETRYABLE_INDEX_ERRORS | {429, 503}:
                raise
            last_error = error
    if not selected:
        raise last_error or ValueError("Common Crawl has no collections")
    for endpoint, pages in selected:
        cursor = cursors.setdefault(endpoint, {"page": 0, "offset": 0})
        for page in range(cursor["page"], pages):
            try:
                rows = _read_json(
                    f"{endpoint}?{urlencode(query | {'page': page, 'fl': 'url'})}", timeout, lines=True
                )
            except HTTPStatusError as error:
                if error.status_code != 404:
                    raise
                rows = []
            for offset in range(cursor["offset"], len(rows)):
                cursor.update(page=page, offset=offset + 1)
                state.update(endpoint=endpoint, **cursor)
                yield rows[offset]
            cursor.update(page=page + 1, offset=0)
            state.update(endpoint=endpoint, **cursor)
            if page + 1 < pages:
                time.sleep(1)


def verify(source: tuple[str, str], adapter: Adapter, timeout: float):
    account, url = source
    try:
        (adapter.verify or adapter.fetch_records)(url, timeout)
    except (OSError, ValueError) as error:
        return error
    return account, url, datetime.now(timezone.utc).isoformat()


def discover(
    provider: str, limit: int, workers: int, timeout: float, known_accounts: set[str] | None = None,
    states: dict[str, dict] | None = None, database: sqlite3.Connection | None = None,
    collections: int = 1,
) -> list[tuple[str, str, str]]:
    if limit < 0 or workers < 1 or timeout <= 0:
        raise ValueError("limit must be >= 0; workers and timeout must be > 0")
    adapter = ADAPTERS[provider]
    if not adapter.domains:
        raise ValueError(f"{provider} does not support Common Crawl discovery")
    known_accounts = known_accounts or set()
    print("collecting candidates from Common Crawl", file=sys.stderr)
    candidates = {}
    states = states if states is not None else {}
    streams = deque(
        iter(records(domain, timeout, states.setdefault(domain, {}), collections))
        for domain in adapter.domains
    )
    while streams and (not limit or len(candidates) < limit):
        stream = streams.popleft()
        try:
            record = next(stream)
        except StopIteration:
            continue
        source = adapter.source(record.get("url", ""))
        if source is not None and source[0] not in known_accounts:
            candidates[source[0]] = source
        streams.append(stream)
    candidates = list(candidates.values())
    if database is not None:
        with database:
            candidates = queue_candidates(database, provider, candidates, limit)
    print(f"verifying {len(candidates)} candidates", file=sys.stderr)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        verify_source = partial(verify, adapter=adapter, timeout=timeout)
        candidates.sort()
        verified = zip(candidates, pool.map(verify_source, candidates))
        results = []
        for (account, _), result in verified:
            if isinstance(result, Exception):
                if database is not None:
                    with database:
                        fail_candidate(database, provider, account, result)
            elif result is not None:
                results.append(result)
        results.sort()
    print(f"verified {len(results)} feeds", file=sys.stderr)
    return results
