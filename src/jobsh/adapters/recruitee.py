"""Public Recruitee career sites."""
import re
from operator import itemgetter
from urllib.parse import urlsplit

from ..http import fetch
from .json_feed import normalize


def source(url: str) -> tuple[str, str] | None:
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    account = host.removesuffix(".recruitee.com")
    if parsed.path.startswith("/o/") and host.endswith(".recruitee.com") and re.fullmatch(r"[a-z0-9-]+", account):
        return account, f"https://{account}.recruitee.com/api/offers/"
    return None


def _record(job: dict) -> dict:
    locations = [
        ", ".join(filter(None, (item.get("city"), item.get("state"), item.get("country"))))
        for item in job["locations"]
    ]
    mode = "hybrid" if job.get("hybrid") is True else (
        "remote" if job.get("remote") is True else "onsite" if job.get("on_site") is True else "unknown"
    )
    return {
        "external_id": job["id"], "title": job["title"],
        "description": "\n".join(filter(None, (job["description"], job.get("requirements")))),
        "locations": locations or [job.get("location")], "work_mode": mode,
        "employment_type": job.get("employment_type_code"), "source_category": job.get("department"),
        "original_url": job["careers_url"], "published_at": job.get("published_at"),
    }


def normalize_feed(data: bytes) -> list[dict[str, str | None]]:
    return normalize(data, name="Recruitee", record=_record, jobs=itemgetter("offers"), id_type=int)


def fetch_records(url: str, timeout: float) -> list[dict[str, str | None]]:
    return normalize_feed(fetch(url, timeout))
