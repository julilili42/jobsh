import json
import time
from collections.abc import Iterator
from urllib.parse import urlencode

from .http import fetch

COLLECTIONS_URL = "https://index.commoncrawl.org/collinfo.json"


def _read_json(url: str, timeout: float, *, lines: bool = False):
    for attempt in range(3):
        data = fetch(url, timeout)
        try:
            return [json.loads(line) for line in data.splitlines()] if lines else json.loads(data)
        except json.JSONDecodeError as error:
            if attempt == 2:
                raise ValueError(f"invalid Common Crawl JSON from {url}: {error}") from error
            time.sleep(1)


def latest_snapshot(timeout: float) -> str:
    collections = _read_json(COLLECTIONS_URL, timeout)
    return max(collections, key=lambda item: item["to"])["cdx-api"]


def records(domain: str, timeout: float) -> Iterator[dict[str, str]]:
    endpoint = latest_snapshot(timeout)

    query = {
        "url": domain,
        "matchType": "domain",
        "filter": "status:200",
        "output": "json",
        "pageSize": 1,
    }
    pagination_url = f"{endpoint}?{urlencode(query | {'showNumPages': 'true'})}"
    pages = _read_json(pagination_url, timeout)["pages"]

    for page in range(pages):
        page_url = f"{endpoint}?{urlencode(query | {'page': page, 'fl': 'url'})}"
        yield from _read_json(page_url, timeout, lines=True)
        if page + 1 < pages:
            time.sleep(1)
