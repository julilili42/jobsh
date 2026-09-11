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


def _record(job: dict) -> dict:
    location = job["location"]["name"]
    # ponytail: location-only heuristic; structured work-mode metadata when available.
    mode = "hybrid" if re.search(r"\bhybrid\b", location, re.I) else (
        "remote" if re.search(r"\bremote\b", location, re.I) else "unknown"
    )
    return {
        "external_id": job["id"], "title": job["title"], "description": unescape(job["content"]),
        "locations": [location] if location else [], "work_mode": mode,
        "source_category": "; ".join(item["name"] for item in job.get("departments", [])) or None,
        "employment_type": None, "original_url": job["absolute_url"], "published_at": None,
    }


def _jobs(payload: dict) -> list:
    jobs = payload["jobs"]
    if payload.get("meta", {}).get("total", len(jobs)) != len(jobs):
        raise ValueError("incomplete Greenhouse feed")
    return jobs


def normalize_feed(data: bytes) -> list[dict[str, str | None]]:
    return normalize(data, name="Greenhouse", record=_record, jobs=_jobs, id_type=int)


def fetch_records(url: str, timeout: float) -> list[dict[str, str | None]]:
    return normalize_feed(fetch(url, timeout))
