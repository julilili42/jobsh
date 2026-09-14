"""Public Workday career sites."""
import json
import re
from functools import partial
from urllib.parse import urlsplit

from ..http import fetch
from .json_feed import normalize


def source(url: str) -> tuple[str, str] | None:
    parsed = urlsplit(url)
    match = re.fullmatch(r"([a-z0-9-]+)\.wd\d+\.myworkdayjobs\.com", parsed.hostname or "")
    parts = parsed.path.strip("/").split("/")
    if match and "job" in parts:
        job = parts.index("job")
        if job and re.fullmatch(r"[A-Za-z0-9_-]+", parts[job - 1]):
            tenant, site = match.group(1), parts[job - 1]
            account = f"{parsed.hostname}:{site}"
            return account, f"https://{parsed.hostname}/wday/cxs/{tenant}/{site}/jobs"
    return None


def _page(offset: int, *, url: str, timeout: float) -> tuple[int, list[dict]]:
    try:
        page = json.loads(fetch(url, timeout, json={
            "appliedFacets": {}, "limit": 20, "offset": offset, "searchText": "",
        }))
        total, jobs = page["total"], page["jobPostings"]
        if type(total) is not int or total < 0 or not isinstance(jobs, list) or len(jobs) > 20:
            raise ValueError("incomplete Workday jobs list")
        if any(not isinstance(job["externalPath"], str) or not job["externalPath"].startswith("/job/") for job in jobs):
            raise ValueError("invalid Workday job path")
        return total, jobs
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError) as error:
        raise ValueError("invalid Workday jobs list") from error


def _postings(url: str, timeout: float) -> list[dict]:
    total, first = _page(0, url=url, timeout=timeout)
    pages = [(total, first)] + [
        _page(offset, url=url, timeout=timeout) for offset in range(20, total, 20)
    ]
    result = []
    for offset, (page_total, jobs) in zip(range(0, total or 1, 20), pages):
        expected = min(20, total - offset)
        if page_total not in (0, total) or len(jobs) != expected:
            raise ValueError("incomplete Workday jobs list")
        result.extend(jobs)
    paths = [job["externalPath"] for job in result]
    if len(set(paths)) != total:
        raise ValueError("duplicate or inconsistent Workday jobs")
    return result


def _record(job: dict, url: str) -> dict:
    parsed = urlsplit(url)
    site = parsed.path.rsplit("/", 2)[-2]
    return {
        "external_id": job["externalPath"], "title": job["title"], "description": "",
        "locations": [job["locationsText"]] if job.get("locationsText") else [],
        "work_mode": {"hybrid": "hybrid", "remote": "remote", "onsite": "onsite"}.get(
            str(job.get("remoteType", "")).lower(), "unknown"
        ),
        "employment_type": None, "source_category": None,
        "original_url": f"{parsed.scheme}://{parsed.netloc}/{site}{job['externalPath']}",
        "published_at": None,
    }


def fetch_records(url: str, timeout: float) -> list[dict[str, str | None]]:
    # ponytail: list-only bulk import; hydrate descriptions on demand when search quality requires it.
    return normalize(
        json.dumps({"jobs": _postings(url, timeout)}).encode(),
        name="Workday", record=partial(_record, url=url),
    )
