import json
import time
from urllib.parse import urlencode

from .http import fetch

COLLECTIONS_URL = "https://index.commoncrawl.org/collinfo.json"


def latest_snapshot(timeout: float) -> str:
    collections = json.loads(fetch(COLLECTIONS_URL, timeout))
    return max(collections, key=lambda item: item["to"])["cdx-api"]


def records(domain: str, timeout: float) -> list[dict[str, str]]:
    endpoint = latest_snapshot(timeout)

    query = {
        "url": domain,
        "matchType": "domain",
        "filter": "status:200",
        "output": "json",
        "pageSize": 1,
    }
    pagination_url = f"{endpoint}?{urlencode(query | {'showNumPages': 'true'})}"
    pages = json.loads(fetch(pagination_url, timeout))["pages"]
    found = []

    for page in range(pages):
        page_url = f"{endpoint}?{urlencode(query | {'page': page, 'fl': 'url'})}"
        found.extend(json.loads(line) for line in fetch(page_url, timeout).splitlines())
        if page + 1 < pages:
            time.sleep(1)

    return found
