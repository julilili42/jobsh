import hashlib
import json
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit

from ..http import fetch


def _text(element: ET.Element, tag: str) -> str:
    return (element.findtext(f"{{*}}{tag}") or "").strip()


def validated_positions(data: bytes) -> list[ET.Element]:
    if b"<!DOCTYPE" in data.upper():
        raise ValueError("DOCTYPE is not allowed")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as error:
        raise ValueError("invalid Personio XML") from error
    if root.tag.rsplit("}", 1)[-1] != "workzag-jobs":
        raise ValueError("not a Personio jobs feed")
    positions = root.findall("{*}position")
    ids = set()
    for position in positions:
        job_id = _text(position, "id")
        name = _text(position, "name")
        if not job_id or not name:
            raise ValueError("position is missing id or name")
        if job_id in ids:
            raise ValueError(f"duplicate position id: {job_id}")
        ids.add(job_id)
    return positions


def _normalize_position(position: ET.Element, host: str) -> dict[str, str | None]:
    external_id = _text(position, "id")
    locations = [
        office.text.strip()
        for office in position.findall("{*}office")
        if office.text and office.text.strip()
    ]
    descriptions = [
        "\n".join(filter(None, (_text(section, "name"), _text(section, "value"))))
        for section in position.findall("{*}jobDescriptions/{*}jobDescription")
    ]
    location_text = "; ".join(locations)
    searchable = " ".join(locations + descriptions).lower()
    if "hybrid" in searchable:
        work_mode = "hybrid"
    elif "remote" in searchable or "homeoffice" in searchable:
        work_mode = "remote"
    else:
        work_mode = "onsite" if locations else "unknown"
    record = {
        "external_id": external_id,
        "title": _text(position, "name"),
        "description": "\n\n".join(filter(None, descriptions)) or None,
        "locations": json.dumps(locations, ensure_ascii=False),
        "location_text": location_text or None,
        "work_mode": work_mode,
        "employment_type": _text(position, "employmentType") or None,
        "source_category": _text(position, "department") or None,
        "original_url": f"https://{host}/job/{external_id}?display=de",
        "published_at": _text(position, "createdAt") or None,
    }
    record["content_hash"] = hashlib.sha256(
        json.dumps(record, sort_keys=True).encode()
    ).hexdigest()
    record["raw_record"] = ET.tostring(position, encoding="unicode")
    return record


def normalize_feed(data: bytes, feed_url: str) -> list[dict[str, str | None]]:
    host = urlsplit(feed_url).hostname or ""
    return [_normalize_position(position, host) for position in validated_positions(data)]


def fetch_records(feed_url: str, timeout: float) -> list[dict[str, str | None]]:
    return normalize_feed(fetch(feed_url, timeout), feed_url)


def source(url: str) -> tuple[str, str] | None:
    host = urlsplit(url).hostname or ""
    account, _, domain = host.partition(".")
    if account and domain in ("jobs.personio.de", "jobs.personio.com"):
        return account, f"https://{host}/xml?language=de"
    return None
