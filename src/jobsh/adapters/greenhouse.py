"""Public Greenhouse Job Board API adapter."""
import re
from html import unescape
from urllib.parse import parse_qs, urlsplit

from ..http import fetch
from .json_feed import normalize


def source(url: str) -> tuple[str, str] | None:
    parsed = urlsplit(url)
    if parsed.hostname not in ("boards.greenhouse.io", "job-boards.greenhouse.io"):
        return None
    account = parsed.path.strip("/").split("/")[0]
    if account == "embed":
        account = parse_qs(parsed.query).get("for", [""])[0]
    if not re.fullmatch(r"[A-Za-z0-9_-]+", account):
        return None
    return account, f"https://boards-api.greenhouse.io/v1/boards/{account}/jobs?content=true"


def _prepare(job: dict, record: dict) -> None:
    location = record["locations"]
    record["description"] = unescape(record["description"])
    record["locations"] = [location] if location else []
    record["source_category"] = "; ".join(item["name"] for item in job.get("departments", [])) or None
    # ponytail: location-only heuristic; structured work-mode metadata when available.
    record["work_mode"] = "hybrid" if re.search(r"\bhybrid\b", location, re.I) else (
        "remote" if re.search(r"\bremote\b", location, re.I) else "unknown"
    )


def normalize_feed(data: bytes) -> list[dict[str, str | None]]:
    return normalize(data, name="Greenhouse", jobs_path=("jobs",), prepare=_prepare,
                     valid_id=lambda job_id: type(job_id) is int and job_id > 0,
                     complete=lambda payload, jobs: payload.get("meta", {}).get("total", len(jobs)) == len(jobs),
                     fields={"external_id": ("id",), "title": ("title",),
                             "description": ("content",), "locations": ("location", "name"), "work_mode": None,
                             "employment_type": None, "source_category": None,
                             "original_url": ("absolute_url",), "published_at": None})


def fetch_records(url: str, timeout: float) -> list[dict[str, str | None]]:
    return normalize_feed(fetch(url, timeout))
