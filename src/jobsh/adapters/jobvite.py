"""Public Jobvite career boards."""
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.parse import urlsplit

from ..http import fetch

_COMPANY_EID = re.compile(r"\bcompanyEId\s*[:=]\s*['\"]([A-Za-z0-9]+)")


def _text(job: ET.Element, tag: str) -> str:
    return (job.findtext(f"{{*}}{tag}") or "").strip()


def validated_jobs(data: bytes) -> list[ET.Element]:
    if b"<!DOCTYPE" in data.upper():
        raise ValueError("DOCTYPE is not allowed")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as error:
        raise ValueError("invalid Jobvite XML") from error
    if root.tag.rsplit("}", 1)[-1] != "result":
        raise ValueError("not a Jobvite jobs feed")
    jobs, ids = root.findall("{*}job"), set()
    for job in jobs:
        job_id, title = _text(job, "id"), _text(job, "title")
        if not job_id or not title or job_id in ids:
            raise ValueError("Jobvite job is missing a unique id or title")
        ids.add(job_id)
    return jobs


def _record(job: ET.Element, account: str) -> dict[str, str | None]:
    job_id, location = _text(job, "id"), _text(job, "location")
    published = _text(job, "date")
    if published:
        try:
            published = datetime.strptime(published, "%m/%d/%Y").date().isoformat()  # noqa: DTZ007
        except ValueError:
            published = None
    record = {
        "external_id": job_id,
        "title": _text(job, "title"),
        "description": _text(job, "description") or None,
        "locations": json.dumps([location] if location else [], ensure_ascii=False),
        "location_text": location or None,
        "work_mode": "remote" if "remote" in location.lower() else "onsite" if location else "unknown",
        "employment_type": _text(job, "jobtype") or None,
        "source_category": _text(job, "category") or None,
        "original_url": f"https://jobs.jobvite.com/{account}/job/{job_id}",
        "published_at": published,
    }
    record["content_hash"] = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
    record["raw_record"] = ET.tostring(job, encoding="unicode")
    return record


def normalize_feed(data: bytes, board_url: str) -> list[dict[str, str | None]]:
    account = urlsplit(board_url).path.strip("/").split("/")[0]
    return [_record(job, account) for job in validated_jobs(data)]


def fetch_records(board_url: str, timeout: float) -> list[dict[str, str | None]]:
    page = fetch(board_url, timeout).decode("utf-8", "replace")
    match = _COMPANY_EID.search(page)
    if match is None:
        raise ValueError("Jobvite board is missing companyEId")
    feed = fetch(f"https://app.jobvite.com/CompanyJobs/Xml.aspx?c={match.group(1)}", timeout)
    return normalize_feed(feed, board_url)


def source(url: str) -> tuple[str, str] | None:
    parsed = urlsplit(url)
    account = parsed.path.strip("/").split("/")[0]
    if (parsed.scheme in ("http", "https") and parsed.username is None and parsed.hostname == "jobs.jobvite.com"
            and re.fullmatch(r"[A-Za-z0-9_-]+", account)):
        return account, f"https://jobs.jobvite.com/{account}"
    return None
