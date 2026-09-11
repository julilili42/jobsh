"""Shared validation and normalization for complete JSON job feeds."""
import hashlib
import json
from collections.abc import Callable
from urllib.parse import urlsplit

Path = tuple[str, ...]


def _get(value: dict, path: Path | None):
    for key in path or ():
        value = value[key]
    return value if path else None


def normalize(
    data: bytes,
    *,
    name: str,
    jobs_path: Path,
    fields: dict[str, Path | None],
    prepare: Callable[[dict, dict], None] = lambda job, record: None,
    include: Callable[[dict], bool] = lambda job: True,
    complete: Callable[[dict, list], bool] = lambda payload, jobs: True,
    valid_id: Callable[[object], bool] = lambda job_id: type(job_id) in (str, int) and str(job_id) != "",
) -> list[dict[str, str | None]]:
    try:
        payload = json.loads(data)
        jobs = _get(payload, jobs_path)
        if not isinstance(jobs, list) or not complete(payload, jobs):
            raise ValueError(f"invalid or incomplete {name} jobs list")
        records, ids = [], set()
        for job in jobs:
            if not include(job):
                continue
            record = {field: _get(job, path) for field, path in fields.items()}
            prepare(job, record)
            job_id, title, url = record["external_id"], record["title"], record["original_url"]
            if not valid_id(job_id) or job_id in ids:
                raise ValueError(f"invalid or duplicate {name} job ID")
            if not isinstance(title, str) or not title.strip() or urlsplit(url).scheme not in ("http", "https"):
                raise ValueError(f"missing {name} title or URL")
            locations, description = record["locations"], record["description"]
            if (not isinstance(locations, list) or any(not isinstance(item, str) for item in locations)
                    or not isinstance(description, str)):
                raise ValueError(f"invalid {name} description or locations")
            ids.add(job_id)
            locations = list(dict.fromkeys(filter(None, locations)))
            record.update(external_id=str(job_id), title=title.strip(),
                          description=description or None,
                          locations=json.dumps(locations, ensure_ascii=False),
                          location_text="; ".join(locations) or None)
            record["content_hash"] = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
            record["raw_record"] = json.dumps(job, ensure_ascii=False, sort_keys=True)
            records.append(record)
        return records
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError(f"invalid {name} feed") from error
