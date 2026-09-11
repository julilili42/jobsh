"""Shared validation and normalization for complete JSON job feeds."""
import hashlib
import json
from collections.abc import Callable
from operator import itemgetter
from urllib.parse import urlsplit


def normalize(
    data: bytes,
    *,
    name: str,
    record: Callable[[dict], dict | None],
    id_type: type = str,
    jobs: Callable = itemgetter("jobs"),
) -> list[dict[str, str | None]]:
    try:
        items = jobs(json.loads(data))
        if not isinstance(items, list):
            raise ValueError(f"invalid or incomplete {name} jobs list")
        records, ids = [], set()
        for job in items:
            normalized = record(job)
            if normalized is None:
                continue
            job_id, title, url = normalized["external_id"], normalized["title"], normalized["original_url"]
            if type(job_id) is not id_type or not job_id or (id_type is int and job_id < 0) or job_id in ids:
                raise ValueError(f"invalid or duplicate {name} job ID")
            if not isinstance(title, str) or not title.strip() or urlsplit(url).scheme not in ("http", "https"):
                raise ValueError(f"missing {name} title or URL")
            locations, description = normalized["locations"], normalized["description"]
            if (not isinstance(locations, list) or any(not isinstance(item, str) for item in locations)
                    or not isinstance(description, str)):
                raise ValueError(f"invalid {name} description or locations")
            ids.add(job_id)
            locations = list(dict.fromkeys(filter(None, locations)))
            normalized.update(
                external_id=str(job_id), title=title.strip(), description=description or None,
                locations=json.dumps(locations, ensure_ascii=False), location_text="; ".join(locations) or None,
            )
            normalized["content_hash"] = hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest()
            normalized["raw_record"] = json.dumps(job, ensure_ascii=False, sort_keys=True)
            records.append(normalized)
        return records
    except (KeyError, TypeError, AttributeError, OverflowError, OSError) as error:
        raise ValueError(f"invalid {name} feed") from error
