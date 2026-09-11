import json
import sys
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import partial
from urllib.parse import urlencode, urlsplit

from .http import HTTPStatusError, fetch
from .adapters import ADAPTERS, Adapter

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


def records(domain: str, timeout: float, state: dict | None = None):
    collections = sorted(_read_json(COLLECTIONS_URL, timeout), key=lambda item: item["to"], reverse=True)
    state = state if state is not None else {}
    query = {"url": domain, "matchType": "domain", "filter": "status:200",
             "output": "json", "pageSize": 1}
    last_error = None
    for collection in collections:
        endpoint = collection["cdx-api"]
        try:
            pages = _read_json(f"{endpoint}?{urlencode(query | {'showNumPages': 'true'})}", timeout)["pages"]
            break
        except HTTPStatusError as error:
            if error.status_code not in RETRYABLE_INDEX_ERRORS | {429, 503}:
                raise
            last_error = error
    else:
        raise last_error or ValueError("Common Crawl has no collections")
    if state.get("endpoint") != endpoint:
        state.update(endpoint=endpoint, page=0, offset=0)
    for page in range(state["page"], pages):
        try:
            rows = _read_json(
                f"{endpoint}?{urlencode(query | {'page': page, 'fl': 'url'})}", timeout, lines=True
            )
        except HTTPStatusError as error:
            if error.status_code != 404:
                raise
            rows = []
        for offset in range(state["offset"], len(rows)):
            state.update(page=page, offset=offset + 1)
            yield rows[offset]
        state.update(page=page + 1, offset=0)
        if page + 1 < pages:
            time.sleep(1)


def candidate_hosts(
    records: Iterable[dict[str, str]], domain: str, limit: int = 0,
    known_hosts: set[str] | None = None,
) -> list[str]:
    """Collect up to limit distinct hosts in input order, then sort the selection."""
    if limit < 0:
        raise ValueError("limit must be >= 0")
    domain = domain.lower()
    hosts = set()
    known_hosts = known_hosts or set()
    for record in records:
        host = (urlsplit(record.get("url", "")).hostname or "").lower()
        account, separator, parent = host.partition(".")
        if account and separator and parent == domain and host not in known_hosts:
            hosts.add(host)
            if limit and len(hosts) >= limit:
                break
    return sorted(hosts)


def verify(source: tuple[str, str], adapter: Adapter, timeout: float):
    account, url = source
    try:
        (adapter.verify or adapter.fetch_records)(url, timeout)
    except (OSError, ValueError):
        return None
    return account, url, datetime.now(timezone.utc).isoformat()


def discover(
    provider: str, limit: int, workers: int, timeout: float, known_accounts: set[str] | None = None,
    state: dict | None = None,
) -> list[tuple[str, str, str]]:
    if limit < 0 or workers < 1 or timeout <= 0:
        raise ValueError("limit must be >= 0; workers and timeout must be > 0")
    adapter = ADAPTERS[provider]
    known_accounts = known_accounts or set()
    print("collecting candidates from Common Crawl", file=sys.stderr)
    candidates = {}
    for record in records(adapter.domain, timeout, state):
        source = adapter.source(record.get("url", ""))
        if source is not None and source[0] not in known_accounts:
            candidates[source[0]] = source
            if limit and len(candidates) >= limit:
                break
    print(f"verifying {len(candidates)} candidates", file=sys.stderr)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        verify_source = partial(verify, adapter=adapter, timeout=timeout)
        verified = pool.map(verify_source, sorted(candidates.values()))
        results = sorted(result for result in verified if result)
    print(f"verified {len(results)} feeds", file=sys.stderr)
    return results
