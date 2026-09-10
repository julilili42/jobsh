import re
import sqlite3

NON_IT = re.compile(r"\b(recruit\w*|personalreferent\w*|talent acquisition|sales|vertrieb\w*|marketing|buchhalt\w*|accountant|pflege\w*|nurse|koch|cook|business development)\b", re.I)
IT_ROLE = re.compile(r"\b(softwareentwickler\w*|software developer|software engineer|programmierer\w*|fachinformatiker\w*|systemadministrator\w*|sysadmin|devops|sre|data engineer|data scientist|frontend\w*|backend\w*|full.?stack|it[ -](support|administrator|security|architect)|cybersecurity)\b", re.I)
TECH = re.compile(r"(?<!\w)(python|java|javascript|typescript|golang|go|c\+\+|c#|\.net|sql|linux|kubernetes)(?!\w)", re.I)
GENERIC_ROLE = re.compile(r"\b(developer|entwickler\w*|engineer|administrator)\b", re.I)
IT_CATEGORY = re.compile(r"\b(it|software|information technology|informatik)\b", re.I)
JOB_FIELDS = (
    "title", "description", "locations", "location_text", "work_mode", "employment_type",
    "original_url", "german_eligibility_evidence", "published_at", "content_hash", "raw_record",
    "source_category", "it_classification", "classification_rule",
)
UPSERT_JOB = f"""
    INSERT INTO jobs (source_id, external_id, first_seen_at, last_seen_at, {', '.join(JOB_FIELDS)})
    VALUES (:source_id, :external_id, :seen_at, :seen_at, {', '.join(':' + name for name in JOB_FIELDS)})
    ON CONFLICT (source_id, external_id) DO UPDATE SET
        last_seen_at = :seen_at, missing_imports = 0, closed_at = NULL,
        {', '.join(f'{name} = excluded.{name}' for name in JOB_FIELDS)}
"""


def classify(title: str, description: str = "", category: str = "") -> tuple[str, str]:
    if NON_IT.search(title):
        return "non_it", "title:non_it_role"
    if IT_ROLE.search(title):
        return "it", "title:it_role"
    if GENERIC_ROLE.search(title):
        if TECH.search(title):
            return "it", "title:technical_role"
        if IT_CATEGORY.search(category):
            return "it", "category:it_with_role"
        if IT_ROLE.search(description) and TECH.search(description):
            return "it", "description:it_role_and_technology"
    return "uncertain", "unmatched"


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
        classification, rule = classify(
            record["title"], record.get("description") or "", record.get("source_category") or ""
        )
        values = record | {
            "source_id": source_id, "seen_at": seen_at,
            "source_category": record.get("source_category"),
            "it_classification": classification, "classification_rule": rule,
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
