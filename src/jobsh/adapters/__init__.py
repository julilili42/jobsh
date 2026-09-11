"""Provider registry shared by discovery and sync."""
from collections.abc import Callable
from dataclasses import dataclass

from . import ashby, greenhouse, personio, smartrecruiters


@dataclass(frozen=True)
class Adapter:
    domain: str
    source: Callable[[str], tuple[str, str] | None]
    fetch_records: Callable[[str, float], list[dict[str, str | None]]]
    verify: Callable[[str, float], object] | None = None


ADAPTERS = {
    "ashby": Adapter("jobs.ashbyhq.com", ashby.source, ashby.fetch_records),
    "greenhouse": Adapter("greenhouse.io", greenhouse.source, greenhouse.fetch_records),
    "personio": Adapter("jobs.personio.de", personio.source, personio.fetch_records),
    "smartrecruiters": Adapter("smartrecruiters.com", smartrecruiters.source,
                               smartrecruiters.fetch_records, smartrecruiters.verify_feed),
}
