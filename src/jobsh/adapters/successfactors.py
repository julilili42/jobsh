"""Public SAP SuccessFactors job pages."""
from urllib.parse import parse_qs, urlsplit

from . import job_page

fetch_records = job_page.fetch_records


def source(url: str) -> tuple[str, str] | None:
    return job_page.source(
        url, lambda host: ".successfactors." in host,
        lambda path: path.endswith("/jobreq") and bool(parse_qs(urlsplit(url).query).get("jobId")),
    )
