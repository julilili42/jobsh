"""Public onlyfy job pages."""
from . import job_page

fetch_records = job_page.fetch_records


def source(url: str) -> tuple[str, str] | None:
    return job_page.source(url, lambda host: host.endswith(".onlyfy.io"), lambda path: path.startswith("/job/"))
