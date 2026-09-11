"""Public d.vinci job publication API."""
import re
from urllib.parse import urlsplit

from ..http import fetch
from .json_feed import normalize


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
        return source_id, f"https://{host}{prefix}/jobPublication/list.json?maxCacheAge=3600"
    return None


def _record(job: dict) -> dict:
    opening = job["jobOpening"]
    locations = [item["name"] for item in opening.get("locations", [])]
    if not locations and opening.get("location"):
        locations = [opening["location"]]
    description = "\n\n".join(filter(None, (
        job.get("introduction"), job.get("tasks"), job.get("profile"),
        job.get("weOffer"), job.get("closingText"),
    )))
    searchable = (" ".join(dict.fromkeys(filter(None, locations))) + " " + description).lower()
    mode = "hybrid" if "hybrid" in searchable else (
        "remote" if re.search(r"\b(remote|homeoffice|mobiles arbeiten)\b", searchable) else "unknown"
    )
    return {
        "external_id": job["id"], "title": job["position"], "description": description,
        "locations": locations, "work_mode": mode,
        "employment_type": "; ".join(item["name"] for item in opening.get("workingTimes", [])) or None,
        "source_category": "; ".join(item["name"] for item in opening.get("categories", [])) or None,
        "original_url": job["jobPublicationURL"], "published_at": job.get("startDate"),
    }


def normalize_feed(data: bytes) -> list[dict[str, str | None]]:
    return normalize(data, name="d.vinci", record=_record, id_type=int, jobs=lambda payload: payload)


def fetch_records(url: str, timeout: float) -> list[dict[str, str | None]]:
    return normalize_feed(fetch(url, timeout))
