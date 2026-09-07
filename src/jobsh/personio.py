import json
import sys
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import urlsplit

from .common_crawl import records
from .http import fetch

PERSONIO_SUFFIX = ".jobs.personio.de"


def personio_hosts(records: list[dict[str, str]]) -> list[str]:
    hosts = set()
    for record in records:
        host = (urlsplit(record.get("url", "")).hostname or "").lower()
        account = host.removesuffix(PERSONIO_SUFFIX)
        if host.endswith(PERSONIO_SUFFIX) and account and "." not in account:
            hosts.add(host)
    return sorted(hosts)


def parse_feed(data: bytes) -> int:
    if b"<!DOCTYPE" in data.upper():
        raise ValueError("DOCTYPE is not allowed")
    root = ET.fromstring(data)
    if root.tag.rsplit("}", 1)[-1] != "workzag-jobs":
        raise ValueError("not a Personio jobs feed")
    positions = root.findall("{*}position")
    ids = set()
    for position in positions:
        job_id = (position.findtext("{*}id") or "").strip()
        name = (position.findtext("{*}name") or "").strip()
        if not job_id or not name:
            raise ValueError("position is missing id or name")
        if job_id in ids:
            raise ValueError(f"duplicate position id: {job_id}")
        ids.add(job_id)
    return len(positions)


def candidate_hosts(timeout: float, limit: int) -> list[str]:
    archived = records("jobs.personio.de", timeout)
    hosts = personio_hosts(archived)
    return hosts[:limit] if limit else hosts


def verify(host: str, timeout: float) -> dict[str, str | int] | None:
    feed_url = f"https://{host}/xml?language=de"
    try:
        positions = parse_feed(fetch(feed_url, timeout))
    except (OSError, TimeoutError, ET.ParseError, ValueError):
        return None
    return {
        "account": host.removesuffix(PERSONIO_SUFFIX),
        "feed_url": feed_url,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "positions": positions,
    }


def discover(limit: int, workers: int, timeout: float) -> None:
    if limit < 0 or workers < 1 or timeout <= 0:
        raise SystemExit("limit must be >= 0; workers and timeout must be > 0")
    hosts = candidate_hosts(timeout, limit)
    print(f"verifying {len(hosts)} candidate hosts", file=sys.stderr)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        verified = filter(
            None,
            pool.map(lambda host: verify(host, timeout), hosts),
        )
        results = sorted(verified, key=lambda item: item["account"])
    for result in results:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    print(f"verified {len(results)} feeds", file=sys.stderr)
