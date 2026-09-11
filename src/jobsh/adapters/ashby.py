"""Public Ashby job boards."""
import hashlib
import json
import re
from urllib.parse import urlsplit

from ..http import fetch


def source(url: str) -> tuple[str, str] | None:
    parsed = urlsplit(url)
    account = parsed.path.strip("/").split("/")[0]
    if parsed.hostname == "jobs.ashbyhq.com" and re.fullmatch(r"[A-Za-z0-9_-]+", account):
        return account, f"https://api.ashbyhq.com/posting-api/job-board/{account}"
    return None


def normalize_feed(data: bytes) -> list[dict[str, str | None]]:
    try:
        jobs = json.loads(data)["jobs"]
        if not isinstance(jobs, list):
            raise ValueError("invalid Ashby jobs list")
        records, ids = [], set()
        for job in jobs:
            if type(job["isListed"]) is not bool:
                raise ValueError("invalid Ashby listing visibility")
            if not job["isListed"]:
                continue
            job_id, title, url = job["id"], job["title"], job["jobUrl"]
            if not isinstance(job_id, str) or not job_id or job_id in ids:
                raise ValueError("invalid or duplicate Ashby job ID")
            if not isinstance(title, str) or not title.strip() or urlsplit(url).scheme not in ("http", "https"):
                raise ValueError("missing Ashby title or URL")
            ids.add(job_id)
            description = job["descriptionHtml"]
            locations = [job["location"]] + [item["location"] for item in job.get("secondaryLocations", [])]
            if not isinstance(description, str) or any(not isinstance(item, str) for item in locations):
                raise ValueError("invalid Ashby description or location")
            locations = list(dict.fromkeys(filter(None, locations)))
            mode = {"OnSite": "onsite", "Remote": "remote", "Hybrid": "hybrid"}.get(job.get("workplaceType"))
            record = {
                "external_id": job_id, "title": title.strip(), "description": description or None,
                "locations": json.dumps(locations, ensure_ascii=False),
                "location_text": "; ".join(locations) or None,
                "work_mode": mode or ("remote" if job.get("isRemote") is True else "unknown"),
                "employment_type": job.get("employmentType"), "source_category": job.get("department"),
                "original_url": url, "published_at": job.get("publishedAt"),
            }
            record["content_hash"] = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
            record["raw_record"] = json.dumps(job, ensure_ascii=False, sort_keys=True)
            records.append(record)
        return records
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError("invalid Ashby feed") from error


def fetch_records(url: str, timeout: float) -> list[dict[str, str | None]]:
    return normalize_feed(fetch(url, timeout))
