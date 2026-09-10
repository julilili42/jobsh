"""Provider registry shared by discovery and sync."""
from collections.abc import Callable
from dataclasses import dataclass

from . import personio_feed


@dataclass(frozen=True)
class Adapter:
    domain: str
    source: Callable[[str], tuple[str, str] | None]
    fetch_records: Callable[[str, float], list[dict[str, str | None]]]


ADAPTERS = {
    "personio": Adapter("jobs.personio.de", personio_feed.source, personio_feed.fetch_records),
}
