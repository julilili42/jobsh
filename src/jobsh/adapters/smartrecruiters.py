"""Public SmartRecruiters postings, with bounded detail downloads."""
import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from urllib.parse import urlencode, urlsplit

from ..http import fetch

# Shared across source workers. Small submissions leave threads for other boards.
DETAILS = ThreadPoolExecutor(max_workers=8, thread_name_prefix="smartrecruiters")
DETAIL_BATCH = 4


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


def _detail(posting: dict, *, url: str, timeout: float) -> dict[str, str | None]:
    job_id = posting["id"]
    try:
        job = json.loads(fetch(f"{url}/{job_id}", timeout))
        if job["id"] != job_id or job["active"] is not True or job["visibility"] != "PUBLIC":
            raise ValueError("SmartRecruiters posting changed during import")
        title, location = job["name"], job["location"]
        if not isinstance(title, str) or not title.strip():
            raise ValueError("missing SmartRecruiters title")
        locations = [location.get("fullLocation") or ", ".join(filter(None, (
            location.get("city"), location.get("region"), location.get("country"),
        )))]
        if not isinstance(locations[0], str):
            raise ValueError("invalid SmartRecruiters location")
        locations = list(filter(None, locations))
        sections = job["jobAd"]["sections"]
        employment = job.get("typeOfEmployment")
        department = job.get("department")
        if employment is not None and not isinstance(employment, dict):
            raise ValueError("invalid SmartRecruiters employment type")
        if department is not None and not isinstance(department, dict):
            raise ValueError("invalid SmartRecruiters department")
        description = "\n\n".join(
            "\n".join(filter(None, (section.get("title"), section["text"])))
            for section in sections.values() if "text" in section
        )
        account = urlsplit(url).path.split("/")[-2]
        record = {
            "external_id": job_id, "title": title.strip(), "description": description or None,
            "locations": json.dumps(locations, ensure_ascii=False),
            "location_text": "; ".join(locations) or None,
            "work_mode": "hybrid" if location.get("hybrid") is True else (
                "remote" if location.get("remote") is True else "unknown"
            ),
            "employment_type": (employment or {}).get("label"),
            "source_category": (department or {}).get("label"),
            "original_url": f"https://jobs.smartrecruiters.com/{account}/{job_id}",
            "published_at": job.get("releasedDate") or posting.get("releasedDate"),
        }
        record["content_hash"] = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
        record["raw_record"] = json.dumps(job, ensure_ascii=False, sort_keys=True)
        return record
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError(f"invalid SmartRecruiters posting {job_id}: {error}") from error


def postings(url: str, timeout: float) -> list[dict]:
    result, ids = [], set()
    offset, total = 0, None
    while True:
        page = _page(url, timeout, offset)
        if total is not None and page["totalFound"] != total:
            raise ValueError("SmartRecruiters postings changed during import")
        total = page["totalFound"]
        batch = [job["id"] for job in page["content"]]
        if ids.intersection(batch) or len(set(batch)) != len(batch) or offset + len(batch) > total:
            raise ValueError("duplicate or inconsistent SmartRecruiters postings")
        ids.update(batch)
        result.extend(page["content"])
        offset += len(batch)
        if offset == total:
            return result


def fetch_records(url: str, timeout: float) -> list[dict[str, str | None]]:
    postings_ = postings(url, timeout)
    records = []
    for start in range(0, len(postings_), DETAIL_BATCH):
        records.extend(DETAILS.map(partial(_detail, url=url, timeout=timeout), postings_[start:start + DETAIL_BATCH]))
    return records
