"""Public Workable career sites."""
import re
from urllib.parse import urlsplit

from ..http import fetch
from .json_feed import normalize


def source(url: str) -> tuple[str, str] | None:
    parsed = urlsplit(url)
    account = parsed.path.strip("/").split("/")[0]
    if parsed.hostname == "apply.workable.com" and account != "j" and re.fullmatch(r"[A-Za-z0-9_-]+", account):
        return account, f"https://apply.workable.com/api/v1/widget/accounts/{account}?details=true"
    return None


def _record(job: dict) -> dict:
    locations = [
        ", ".join(filter(None, (item.get("city"), item.get("region"), item.get("country"))))
        for item in job["locations"] if item.get("hidden") is not True
    ]
    mode = "remote" if job.get("telecommuting") is True else "onsite" if locations else "unknown"
    return {
        "external_id": job["shortcode"], "title": job["title"], "description": job["description"],
        "locations": locations, "work_mode": mode,
        "employment_type": job.get("employment_type"),
        "source_category": job.get("department") or job.get("function"),
        "original_url": job["url"], "published_at": job.get("published_on"),
    }


def normalize_feed(data: bytes) -> list[dict[str, str | None]]:
    return normalize(data, name="Workable", record=_record)


def fetch_records(url: str, timeout: float) -> list[dict[str, str | None]]:
    return normalize_feed(fetch(url, timeout))
