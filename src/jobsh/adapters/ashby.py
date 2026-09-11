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


def _include(job: dict) -> bool:
    if type(job["isListed"]) is not bool:
        raise ValueError("invalid Ashby listing visibility")
    return job["isListed"]


def _prepare(job: dict, record: dict) -> None:
    record["locations"] = [record["locations"]] + [item["location"] for item in job.get("secondaryLocations", [])]
    mode = {"OnSite": "onsite", "Remote": "remote", "Hybrid": "hybrid"}.get(job.get("workplaceType"))
    record["work_mode"] = mode or ("remote" if job.get("isRemote") is True else "unknown")


def normalize_feed(data: bytes) -> list[dict[str, str | None]]:
    return normalize(data, name="Ashby", jobs_path=("jobs",), include=_include, prepare=_prepare,
                     valid_id=lambda job_id: isinstance(job_id, str) and bool(job_id),
                     fields={"external_id": ("id",), "title": ("title",),
                             "description": ("descriptionHtml",), "locations": ("location",),
                             "work_mode": None, "employment_type": ("employmentType",),
                             "source_category": ("department",), "original_url": ("jobUrl",),
                             "published_at": ("publishedAt",)})


def fetch_records(url: str, timeout: float) -> list[dict[str, str | None]]:
    return normalize_feed(fetch(url, timeout))
