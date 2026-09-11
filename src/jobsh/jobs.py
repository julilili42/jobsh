import sqlite3

JOB_FIELDS = (
    "title", "description", "locations", "location_text", "work_mode", "employment_type",
    "original_url", "published_at", "content_hash", "raw_record", "source_category",
)
UPSERT_JOB = f"""
    INSERT INTO jobs (source_id, external_id, first_seen_at, last_seen_at, {', '.join(JOB_FIELDS)})
    VALUES (:source_id, :external_id, :seen_at, :seen_at, {', '.join(':' + name for name in JOB_FIELDS)})
    ON CONFLICT (source_id, external_id) DO UPDATE SET
        last_seen_at = :seen_at, missing_imports = 0, closed_at = NULL,
        {', '.join(f'{name} = excluded.{name}' for name in JOB_FIELDS)}
"""


def save_jobs(
    database: sqlite3.Connection,
    source_id: int,
    records: list[dict[str, str | None]],
    seen_at: str,
) -> tuple[int, int, int]:
    existing = {
        row["external_id"]: row
        for row in database.execute(
            f"SELECT external_id, {', '.join(JOB_FIELDS)} FROM jobs WHERE source_id = ?",
            (source_id,),
        )
    }
    created = updated = 0
    unchanged = []
    for record in records:
        values = record | {
            "source_id": source_id, "seen_at": seen_at,
            "source_category": record.get("source_category"),
        }
        previous = existing.get(record["external_id"])
        if previous is not None and all(previous[name] == values[name] for name in JOB_FIELDS):
            unchanged.append((seen_at, source_id, record["external_id"]))
            continue
        database.execute(UPSERT_JOB, values)
        if previous is None:
            created += 1
        else:
            updated += 1
    database.executemany(
        "UPDATE jobs SET last_seen_at = ?, missing_imports = 0, closed_at = NULL "
        "WHERE source_id = ? AND external_id = ?",
        unchanged,
    )
    return created, updated, len(unchanged)
