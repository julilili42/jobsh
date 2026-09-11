"""Public Ashby job boards."""
import re
from urllib.parse import urlsplit

from ..http import fetch
from .json_feed import normalize


def source(url: str) -> tuple[str, str] | None:
    parsed = urlsplit(url)
    account = parsed.path.strip("/").split("/")[0]
    if parsed.hostname == "jobs.ashbyhq.com" and re.fullmatch(r"[A-Za-z0-9_-]+", account):
        return account, f"https://api.ashbyhq.com/posting-api/job-board/{account}"
    return None


def _record(job: dict) -> dict | None:
    if type(job["isListed"]) is not bool:
        raise ValueError("invalid Ashby listing visibility")
    if not job["isListed"]:
        return None
    mode = {"OnSite": "onsite", "Remote": "remote", "Hybrid": "hybrid"}.get(job.get("workplaceType"))
    return {
        "external_id": job["id"], "title": job["title"], "description": job["descriptionHtml"],
        "locations": [job["location"]] + [item["location"] for item in job.get("secondaryLocations", [])],
        "work_mode": mode or ("remote" if job.get("isRemote") is True else "unknown"),
        "employment_type": job["employmentType"], "source_category": job["department"],
        "original_url": job["jobUrl"], "published_at": job["publishedAt"],
    }


def normalize_feed(data: bytes) -> list[dict[str, str | None]]:
    return normalize(data, name="Ashby", record=_record)


def fetch_records(url: str, timeout: float) -> list[dict[str, str | None]]:
    return normalize_feed(fetch(url, timeout))
