"""Public job pages backed by Schema.org JobPosting data."""
from collections.abc import Callable
from urllib.parse import urldefrag, urlsplit

from . import jsonld


def source(url: str, host: Callable[[str], bool], path: Callable[[str], bool]) -> tuple[str, str] | None:
    parsed = urlsplit(url)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username is not None
            or not host(parsed.hostname.lower()) or not path(parsed.path)):
        return None
    url = urldefrag(url).url
    return url, url


fetch_records = jsonld.fetch_records
