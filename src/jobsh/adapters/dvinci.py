"""Public d.vinci job publication API."""
import hashlib
import json
import re
from urllib.parse import urlencode, urlsplit

from ..http import fetch


def source(url: str) -> tuple[str, str] | None:
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    account, separator, domain = host.partition(".")
    if separator and domain == "dvinci.de" and re.fullmatch(r"[A-Za-z0-9-]+", account):
        parts = parsed.path.strip("/").split("/")
        portal = "/".join(parts[:2]) if len(parts) > 1 and parts[0] == "portal" else ""
        if portal and not re.fullmatch(r"portal/[A-Za-z0-9_-]+", portal):
            return None
        prefix = f"/{portal}" if portal else ""
        source_id = f"{account}:{parts[1]}" if portal else account
        return source_id, f"https://{host}{prefix}/jobPublication/list.json?{urlencode({'maxCacheAge': 3600})}"
    return None


def normalize_feed(data: bytes) -> list[dict[str, str | None]]:
    try:
        jobs = json.loads(data)
        if not isinstance(jobs, list):
            raise ValueError("invalid d.vinci jobs list")
        records, ids = [], set()
        for job in jobs:
            job_id, title, url = job["id"], job["position"], job["jobPublicationURL"]
            if type(job_id) is not int or job_id <= 0 or job_id in ids:
                raise ValueError("invalid or duplicate d.vinci job ID")
            if not isinstance(title, str) or not title.strip() or urlsplit(url).scheme not in ("http", "https"):
                raise ValueError("missing d.vinci title or URL")
            ids.add(job_id)
            opening = job["jobOpening"]
            locations = [item["name"] for item in opening.get("locations", [])]
            if not locations and opening.get("location"):
                locations = [opening["location"]]
            if any(not isinstance(item, str) for item in locations):
                raise ValueError("invalid d.vinci locations")
            locations = list(dict.fromkeys(filter(None, locations)))
            description = "\n\n".join(filter(None, (
                job.get("introduction"), job.get("tasks"), job.get("profile"),
                job.get("weOffer"), job.get("closingText"),
            )))
            searchable = " ".join(locations + [description]).lower()
            mode = "hybrid" if "hybrid" in searchable else (
                "remote" if re.search(r"\b(remote|homeoffice|mobiles arbeiten)\b", searchable) else "unknown"
            )
            record = {
                "external_id": str(job_id), "title": title.strip(), "description": description or None,
                "locations": json.dumps(locations, ensure_ascii=False),
                "location_text": "; ".join(locations) or None, "work_mode": mode,
                "employment_type": "; ".join(item["name"] for item in opening.get("workingTimes", [])) or None,
                "source_category": "; ".join(item["name"] for item in opening.get("categories", [])) or None,
                "original_url": url, "published_at": job.get("startDate"),
            }
            record["content_hash"] = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
            record["raw_record"] = json.dumps(job, ensure_ascii=False, sort_keys=True)
            records.append(record)
        return records
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError("invalid d.vinci feed") from error


def fetch_records(url: str, timeout: float) -> list[dict[str, str | None]]:
    return normalize_feed(fetch(url, timeout))
