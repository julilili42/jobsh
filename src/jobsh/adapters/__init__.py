"""Provider registry shared by discovery and sync."""
from collections.abc import Callable
from dataclasses import dataclass

from . import (
    ashby,
    dvinci,
    greenhouse,
    jobvite,
    jsonld,
    lever,
    personio,
    recruitee,
    smartrecruiters,
    softgarden,
    teamtailor,
    workable,
    workday,
)


@dataclass(frozen=True)
class Adapter:
    domains: tuple[str, ...]
    source: Callable[[str], tuple[str, str] | None]
    fetch_records: Callable[[str, float], list[dict[str, str | None]]]
    verify: Callable[[str, float], object] | None = None


ADAPTERS = {
    "ashby": Adapter(("jobs.ashbyhq.com",), ashby.source, ashby.fetch_records),
    "dvinci": Adapter(("dvinci.de",), dvinci.source, dvinci.fetch_records),
    "greenhouse": Adapter(("boards.greenhouse.io", "job-boards.greenhouse.io"), greenhouse.source, greenhouse.fetch_records),
    "jsonld": Adapter((), jsonld.source, jsonld.fetch_records),
    "jobvite": Adapter(("jobs.jobvite.com",), jobvite.source, jobvite.fetch_records),
    "lever": Adapter(("jobs.lever.co", "jobs.eu.lever.co"), lever.source, lever.fetch_records, lever.verify_feed),
    "personio": Adapter(("jobs.personio.de", "jobs.personio.com"), personio.source, personio.fetch_records),
    "recruitee": Adapter(("recruitee.com",), recruitee.source, recruitee.fetch_records),
    "smartrecruiters": Adapter(("jobs.smartrecruiters.com", "careers.smartrecruiters.com"), smartrecruiters.source,
                               smartrecruiters.fetch_records, smartrecruiters.verify_feed),
    "softgarden": Adapter(("softgarden.io",), softgarden.source, softgarden.fetch_records),
    "teamtailor": Adapter(("teamtailor.com",), teamtailor.source, teamtailor.fetch_records),
    "workable": Adapter(("apply.workable.com",), workable.source, workable.fetch_records),
    "workday": Adapter(("myworkdayjobs.com",), workday.source, workday.fetch_records),
}
