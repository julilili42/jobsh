import json
import sys
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import partial
from urllib.parse import urlencode, urlsplit

from .http import fetch
from .personio_feed import validated_positions

COLLECTIONS_URL = "https://index.commoncrawl.org/collinfo.json"


def _read_json(url: str, timeout: float, *, lines: bool = False):
    for attempt in range(3):
        try:
            data = fetch(url, timeout)
            return [json.loads(line) for line in data.splitlines()] if lines else json.loads(data)
        except json.JSONDecodeError as error:
            if attempt == 2:
                raise ValueError(f"invalid Common Crawl JSON from {url}: {error}") from error
            time.sleep(1)


def records(domain: str, timeout: float):
    collections = _read_json(COLLECTIONS_URL, timeout)
    endpoint = max(collections, key=lambda item: item["to"])["cdx-api"]
    query = {"url": domain, "matchType": "domain", "filter": "status:200",
             "output": "json", "pageSize": 1}
    pages = _read_json(f"{endpoint}?{urlencode(query | {'showNumPages': 'true'})}", timeout)["pages"]
    for page in range(pages):
        yield from _read_json(
            f"{endpoint}?{urlencode(query | {'page': page, 'fl': 'url'})}", timeout, lines=True
        )
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


def verify(host: str, domain: str, timeout: float) -> tuple[str, str, str] | None:
    feed_url = f"https://{host}/xml?language=de"
    try:
        validated_positions(fetch(feed_url, timeout))
    except (OSError, ValueError):
        return None
    return host.removesuffix(f".{domain}"), feed_url, datetime.now(timezone.utc).isoformat()


def discover(
    domain: str, limit: int, workers: int, timeout: float, known_hosts: set[str] | None = None,
) -> list[tuple[str, str, str]]:
    if limit < 0 or workers < 1 or timeout <= 0:
        raise ValueError("limit must be >= 0; workers and timeout must be > 0")
    print("collecting candidate hosts from Common Crawl", file=sys.stderr)
    crawl_records = records(domain, timeout)
    hosts = candidate_hosts(crawl_records, domain, limit, known_hosts)
    print(f"verifying {len(hosts)} candidate hosts", file=sys.stderr)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        verify_host = partial(verify, domain=domain, timeout=timeout)
        verified = pool.map(verify_host, hosts)
        results = sorted(result for result in verified if result)
    print(f"verified {len(results)} feeds", file=sys.stderr)
    return results
