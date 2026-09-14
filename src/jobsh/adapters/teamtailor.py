"""Public Teamtailor job pages."""
from . import job_page

fetch_records = job_page.fetch_records


def source(url: str) -> tuple[str, str] | None:
    return job_page.source(url, lambda host: host.endswith(".teamtailor.com"), lambda path: path.startswith("/jobs/"))
