"""Public Lever job boards on global and EU instances."""
import re
from datetime import datetime, timezone
from urllib.parse import urlencode, urlsplit

from ..http import fetch
from .json_feed import normalize


def source(url: str) -> tuple[str, str] | None:
    parsed = urlsplit(url)
    if parsed.hostname not in ("jobs.lever.co", "jobs.eu.lever.co"):
        return None
    account = parsed.path.strip("/").split("/")[0]
    if not re.fullmatch(r"[A-Za-z0-9_-]+", account):
        return None
    region = ".eu" if parsed.hostname == "jobs.eu.lever.co" else ""
    return f"{region[1:] + ':' if region else ''}{account}", f"https://api{region}.lever.co/v0/postings/{account}"


def _fetch(url: str, timeout: float, skip: int, limit: int) -> bytes:
    return fetch(url + "?" + urlencode({"mode": "json", "skip": skip, "limit": limit}), timeout)


def verify_feed(url: str, timeout: float) -> None:
    normalize_feed(_fetch(url, timeout, 0, 1))


def _record(job: dict) -> dict:
    categories = job["categories"]
    created = job.get("createdAt")
    if created is not None and type(created) is not int:
        raise ValueError("invalid Lever publication date")
    return {
        "external_id": job["id"], "title": job["text"], "description": job["description"],
        "locations": categories.get("allLocations") or [categories.get("location")],
        "work_mode": {"on-site": "onsite", "remote": "remote", "hybrid": "hybrid"}.get(job.get("workplaceType"), "unknown"),
        "employment_type": categories.get("commitment"),
        "source_category": categories.get("department") or categories.get("team"),
        "original_url": job["hostedUrl"],
        "published_at": datetime.fromtimestamp(created / 1000, timezone.utc).isoformat() if created is not None else None,
    }


def normalize_feed(data: bytes) -> list[dict[str, str | None]]:
    return normalize(data, name="Lever", record=_record, jobs=lambda payload: payload)


def fetch_records(url: str, timeout: float) -> list[dict[str, str | None]]:
    records, ids = [], set()
    while True:
        page = normalize_feed(_fetch(url, timeout, len(records), 100))
        page_ids = {record["external_id"] for record in page}
        if ids.intersection(page_ids):
            raise ValueError("duplicate Lever jobs across pages")
        records.extend(page)
        ids.update(page_ids)
        if len(page) < 100:
            return records
