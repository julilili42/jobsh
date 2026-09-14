"""Public BambooHR job pages."""
from . import job_page

fetch_records = job_page.fetch_records


def source(url: str) -> tuple[str, str] | None:
    return job_page.source(url, lambda host: host.endswith(".bamboohr.com"), lambda path: path.startswith("/careers/") and path.count("/") >= 2)
