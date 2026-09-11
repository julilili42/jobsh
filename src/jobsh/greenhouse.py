"""Public Greenhouse Job Board API adapter."""
import hashlib
import json
import re
from html import unescape
from urllib.parse import parse_qs, urlsplit

from .http import fetch


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


def normalize_feed(data: bytes) -> list[dict[str, str | None]]:
    try:
        payload = json.loads(data)
        jobs = payload["jobs"]
        if not isinstance(jobs, list) or payload.get("meta", {}).get("total", len(jobs)) != len(jobs):
            raise ValueError("incomplete Greenhouse feed")
        records, ids = [], set()
        for job in jobs:
            job_id, title, url = job["id"], job["title"], job["absolute_url"]
            if type(job_id) is not int or job_id <= 0 or job_id in ids:
                raise ValueError("invalid or duplicate Greenhouse job ID")
            if not isinstance(title, str) or not title.strip() or urlsplit(url).scheme not in ("http", "https"):
                raise ValueError("missing Greenhouse title or URL")
            ids.add(job_id)
            location = job["location"]["name"]
            content = job["content"]
            if not isinstance(location, str) or not isinstance(content, str):
                raise ValueError("invalid Greenhouse location or content")
            category = "; ".join(item["name"] for item in job.get("departments", []))
            # ponytail: location-only heuristic; structured work-mode metadata when available.
            mode = "hybrid" if re.search(r"\bhybrid\b", location, re.I) else (
                "remote" if re.search(r"\bremote\b", location, re.I) else "unknown"
            )
            record = {
                "external_id": str(job_id), "title": title.strip(),
                "description": unescape(content) or None,
                "locations": json.dumps([location] if location else [], ensure_ascii=False),
                "location_text": location or None, "work_mode": mode,
                "employment_type": None, "source_category": category or None,
                "original_url": url, "published_at": None,
            }
            record["content_hash"] = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
            record["raw_record"] = json.dumps(job, ensure_ascii=False, sort_keys=True)
            records.append(record)
        return records
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError("invalid Greenhouse feed") from error


def fetch_records(url: str, timeout: float) -> list[dict[str, str | None]]:
    return normalize_feed(fetch(url, timeout))
