import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import urlsplit

from .common_crawl import records
from .http import fetch
from .personio_feed import validated_positions

PERSONIO_SUFFIX = ".jobs.personio.de"


def candidate_hosts(records: list[dict[str, str]], domain: str) -> list[str]:
    """Return unique, sorted hosts exactly one subdomain below domain."""
    domain = domain.lower()
    hosts = set()
    for record in records:
        host = (urlsplit(record.get("url", "")).hostname or "").lower()
        account, separator, parent = host.partition(".")
        if account and separator and parent == domain:
            hosts.add(host)
    return sorted(hosts)


def verify(host: str, timeout: float) -> tuple[str, str, str] | None:
    feed_url = f"https://{host}/xml?language=de"
    try:
        validated_positions(fetch(feed_url, timeout))
    except (OSError, ValueError):
        return None
    return (
        host.removesuffix(PERSONIO_SUFFIX),
        feed_url,
        datetime.now(timezone.utc).isoformat(),
    )


def discover(limit: int, workers: int, timeout: float) -> list[tuple[str, str, str]]:
    if limit < 0 or workers < 1 or timeout <= 0:
        raise SystemExit("limit must be >= 0; workers and timeout must be > 0")
    hosts = candidate_hosts(records("jobs.personio.de", timeout), "jobs.personio.de")
    if limit:
        hosts = hosts[:limit]
    print(f"verifying {len(hosts)} candidate hosts", file=sys.stderr)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = sorted(filter(None, pool.map(lambda host: verify(host, timeout), hosts)))
    print(f"verified {len(results)} feeds", file=sys.stderr)
    return results
