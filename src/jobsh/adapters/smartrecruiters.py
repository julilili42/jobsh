"""Public SmartRecruiters postings."""
import json
import re
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from urllib.parse import urlencode, urlsplit

from ..http import fetch
from .json_feed import normalize

PAGES = ThreadPoolExecutor(max_workers=16, thread_name_prefix="smartrecruiters")


def source(url: str) -> tuple[str, str] | None:
    parsed = urlsplit(url)
    account = parsed.path.strip("/").split("/")[0]
    if parsed.hostname in ("jobs.smartrecruiters.com", "careers.smartrecruiters.com") and re.fullmatch(r"[A-Za-z0-9_-]+", account):
        return account, f"https://api.smartrecruiters.com/v1/companies/{account}/postings"
    return None


def _page(url: str, timeout: float, offset: int = 0, limit: int = 100) -> dict:
    try:
        page = json.loads(fetch(url + "?" + urlencode({"offset": offset, "limit": limit}), timeout))
        if (type(page["totalFound"]) is not int or page["totalFound"] < 0
                or page["offset"] != offset or not isinstance(page["content"], list)
                or len(page["content"]) > limit
                or (not page["content"] and offset < page["totalFound"])):
            raise ValueError("incomplete SmartRecruiters page")
        for job in page["content"]:
            if not isinstance(job["id"], str) or not re.fullmatch(r"[A-Za-z0-9-]+", job["id"]):
                raise ValueError("invalid SmartRecruiters job ID")
        return page
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError("invalid SmartRecruiters page") from error


def verify_feed(url: str, timeout: float) -> None:
    _page(url, timeout, limit=1)


def _record(job: dict, account: str) -> dict:
    location = job["location"]
    return {
        "external_id": job["id"], "title": job["name"], "description": "",
        "locations": [location.get("fullLocation") or ", ".join(filter(None, (
            location.get("city"), location.get("region"), location.get("country"),
        )))],
        "work_mode": "hybrid" if location.get("hybrid") is True else (
            "remote" if location.get("remote") is True else "unknown"
        ),
        "employment_type": (job.get("typeOfEmployment") or {}).get("label"),
        "source_category": (job.get("department") or job.get("function") or {}).get("label"),
        "original_url": f"https://jobs.smartrecruiters.com/{account}/{job['id']}",
        "published_at": job.get("releasedDate"),
    }


def postings(url: str, timeout: float) -> list[dict]:
    first = _page(url, timeout)
    total = first["totalFound"]
    pages = [first, *PAGES.map(partial(_page, url, timeout), range(100, total, 100))]
    result, ids = [], set()
    for offset, page in zip(range(0, total or 1, 100), pages):
        if page["totalFound"] != total:
            raise ValueError("SmartRecruiters postings changed during import")
        batch = [job["id"] for job in page["content"]]
        if (page["offset"] != offset or ids.intersection(batch) or len(set(batch)) != len(batch)
                or len(batch) != min(100, total - offset)):
            raise ValueError("duplicate or inconsistent SmartRecruiters postings")
        ids.update(batch)
        result.extend(page["content"])
    return result


def fetch_records(url: str, timeout: float) -> list[dict[str, str | None]]:
    # ponytail: list-only bulk import; hydrate descriptions on demand when search quality requires it.
    account = urlsplit(url).path.split("/")[-2]
    return normalize(
        json.dumps({"jobs": postings(url, timeout)}).encode(), name="SmartRecruiters",
        record=lambda job: _record(job, account),
    )
