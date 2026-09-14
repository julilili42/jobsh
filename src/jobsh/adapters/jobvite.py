"""Public Jobvite job pages."""
from . import job_page

fetch_records = job_page.fetch_records


def source(url: str) -> tuple[str, str] | None:
    return job_page.source(url, lambda host: host == "jobs.jobvite.com", lambda path: path.count("/") >= 3 and "/job/" in path)
