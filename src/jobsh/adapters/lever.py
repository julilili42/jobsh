"""Public Lever job boards on global and EU instances."""
import hashlib
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlencode, urlsplit

from ..http import fetch


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


def normalize_feed(data: bytes) -> list[dict[str, str | None]]:
    try:
        jobs = json.loads(data)
        if not isinstance(jobs, list):
            raise ValueError("invalid Lever jobs list")
        records, ids = [], set()
        for job in jobs:
            job_id, title, url = job["id"], job["text"], job["hostedUrl"]
            if not isinstance(job_id, str) or not job_id or job_id in ids:
                raise ValueError("invalid or duplicate Lever job ID")
            if not isinstance(title, str) or not title.strip() or urlsplit(url).scheme not in ("http", "https"):
                raise ValueError("missing Lever title or URL")
            ids.add(job_id)
            categories = job["categories"]
            locations = categories.get("allLocations") or [categories.get("location")]
            if not isinstance(locations, list) or any(not isinstance(item, str) for item in locations):
                raise ValueError("invalid Lever locations")
            locations = list(dict.fromkeys(filter(None, locations)))
            description = job["description"]
            if not isinstance(description, str):
                raise ValueError("invalid Lever description")
            mode = {"on-site": "onsite", "remote": "remote", "hybrid": "hybrid"}.get(job.get("workplaceType"), "unknown")
            created = job.get("createdAt")
            if created is not None and type(created) is not int:
                raise ValueError("invalid Lever publication date")
            record = {
                "external_id": job_id, "title": title.strip(), "description": description or None,
                "locations": json.dumps(locations, ensure_ascii=False),
                "location_text": "; ".join(locations) or None, "work_mode": mode,
                "employment_type": categories.get("commitment"),
                "source_category": categories.get("department") or categories.get("team"),
                "original_url": url,
                "published_at": datetime.fromtimestamp(created / 1000, timezone.utc).isoformat() if created is not None else None,
            }
            record["content_hash"] = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
            record["raw_record"] = json.dumps(job, ensure_ascii=False, sort_keys=True)
            records.append(record)
        return records
    except (KeyError, TypeError, AttributeError, OverflowError, OSError) as error:
        raise ValueError("invalid Lever feed") from error


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
