"""Schema.org JobPosting pages."""
import json
import re
from html.parser import HTMLParser
from urllib.parse import urldefrag, urljoin, urlsplit

from ..http import fetch
from .json_feed import normalize


class _Scripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "script" and attributes.get("type", "").split(";", 1)[0].strip().lower() == "application/ld+json":
            self.current = []

    def handle_endtag(self, tag):
        if tag == "script" and self.current is not None:
            self.scripts.append("".join(self.current))
            self.current = None

    def handle_data(self, data):
        if self.current is not None:
            self.current.append(data)


def source(url: str) -> tuple[str, str] | None:
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username is not None:
        return None
    url = urldefrag(url).url
    return url, url


def _is_posting(value: dict) -> bool:
    types = value.get("@type", [])
    types = [types] if isinstance(types, str) else types
    return isinstance(types, list) and any(
        isinstance(item, str) and item.rstrip("/").rsplit("/", 1)[-1] == "JobPosting"
        for item in types
    )


def _postings(value):
    if isinstance(value, dict):
        if _is_posting(value):
            yield value
        for child in value.values():
            yield from _postings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _postings(child)


def _label(value) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        return _label(value.get("name"))
    return None


def _location(value) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if not isinstance(value, dict):
        return None
    address = value.get("address")
    if isinstance(address, str):
        return address.strip() or None
    if isinstance(address, dict):
        parts = [
            _label(address.get(name))
            for name in ("streetAddress", "postalCode", "addressLocality", "addressRegion", "addressCountry")
        ]
        if any(parts):
            return ", ".join(dict.fromkeys(filter(None, parts)))
    return _label(value)


def _record(job: dict, page_url: str) -> dict:
    identifier = job.get("identifier")
    if isinstance(identifier, dict):
        identifier = identifier.get("value", identifier.get("@value"))
    if (not isinstance(identifier, (str, int)) or isinstance(identifier, bool)
            or not str(identifier).strip()):
        identifier = job.get("url") or page_url
    locations = [_location(item) for key in ("jobLocation", "applicantLocationRequirements")
                 for item in (job.get(key) if isinstance(job.get(key), list) else [job.get(key)])]
    locations = list(filter(None, locations))
    description = job.get("description", "")
    searchable = " ".join(locations + ([description] if isinstance(description, str) else []))
    remote = job.get("jobLocationType")
    remote = {value.upper() for value in (remote if isinstance(remote, list) else [remote])
              if isinstance(value, str)}
    mode = "hybrid" if re.search(r"\bhybrid\b", searchable, re.IGNORECASE) else (
        "remote" if "TELECOMMUTE" in remote or re.search(r"\bremote\b", searchable, re.IGNORECASE)
        else "onsite" if locations else "unknown"
    )

    def joined(name):
        values = job.get(name)
        values = values if isinstance(values, list) else [values]
        return "; ".join(value for value in values if isinstance(value, str)) or None

    return {
        "external_id": str(identifier), "title": job["title"], "description": description,
        "locations": locations, "work_mode": mode, "employment_type": joined("employmentType"),
        "source_category": joined("occupationalCategory"),
        "original_url": urljoin(page_url, job.get("url") or page_url),
        "published_at": job.get("datePosted"),
    }


def normalize_page(data: bytes, url: str) -> list[dict[str, str | None]]:
    parser = _Scripts()
    parser.feed(data.decode("utf-8", "replace"))
    parser.close()
    postings = []
    for script in parser.scripts:
        try:
            value = json.loads(
                script.strip().removeprefix("<!--").removesuffix("-->").strip().removesuffix(";")
            )
        except json.JSONDecodeError:
            continue
        postings.extend(_postings(value))
    postings = {json.dumps(job, sort_keys=True): job for job in postings}
    if len(postings) != 1:
        raise ValueError(f"expected one JobPosting, found {len(postings)}")
    return normalize(
        json.dumps({"jobs": list(postings.values())}, ensure_ascii=False).encode(), name="JobPosting",
        record=lambda job: _record(job, url),
    )


def fetch_records(url: str, timeout: float) -> list[dict[str, str | None]]:
    return normalize_page(fetch(url, timeout), url)
