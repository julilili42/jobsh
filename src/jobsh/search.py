import re
import sqlite3

SUMMARY = (
    "j.id, j.title, j.location_text, j.work_mode, j.source_category, "
    "j.original_url, j.published_at, j.last_seen_at, s.provider, s.provider_account"
)
SOURCE_JOIN = " FROM jobs j JOIN sources s ON s.id = j.source_id"


def _validate(query: str, work_mode: str | None, limit: int, cursor: int) -> None:
    if not 1 <= limit <= 100 or not 0 <= cursor < 2**63:
        raise ValueError("limit must be 1..100 and cursor must be 0..2^63-1")
    if work_mode not in (None, "remote", "hybrid", "onsite", "unknown"):
        raise ValueError("invalid work mode")
    if len(query) > 1000:
        raise ValueError("query must be at most 1000 characters")


def _filters(
    query: str, title: str, location: str, work_mode: str | None,
) -> tuple[list[str], list[str]]:
    conditions = ["j.closed_at IS NULL"]
    parameters = []
    terms = []
    for term in query.split():
        if any(special in term.lower() for special in ("c++", "c#", ".net")):
            # ponytail: literal substring scans; add a trigram index if these dominate search time.
            conditions.append("instr(lower(j.title || ' ' || coalesce(j.description, '')), ?) > 0")
            parameters.append(term.lower())
        elif re.search(r"\w", term):
            terms.append('"' + term.replace('"', '""') + '"')
        else:
            raise ValueError("query terms must contain letters or numbers")
    if terms:
        conditions.append("jobs_fts MATCH ?")
        parameters.append(" AND ".join(terms))
    for column, value in (("title", title), ("location_text", location)):
        if value:
            conditions.append(f"instr(lower(coalesce(j.{column}, '')), lower(?)) > 0")
            parameters.append(value)
    if work_mode:
        conditions.append("j.work_mode = ?")
        parameters.append(work_mode)
    return conditions, parameters


def search(
    database: sqlite3.Connection, query: str = "", *, title: str = "",
    location: str = "", work_mode: str | None = None, limit: int = 20, cursor: int = 0,
) -> dict:
    _validate(query, work_mode, limit, cursor)
    if len(title) > 1000 or len(location) > 1000:
        raise ValueError("title and location must be at most 1000 characters")
    conditions, parameters = _filters(query, title, location, work_mode)
    full_text = "jobs_fts MATCH ?" in conditions
    join = " JOIN jobs_fts ON jobs_fts.rowid = j.id" if full_text else ""
    key = "jobs_fts.rowid" if full_text else "j.id"
    rows = database.execute(
        "SELECT " + SUMMARY + SOURCE_JOIN + join + " WHERE " + " AND ".join(conditions)
        + f" AND {key} > ? ORDER BY {key} LIMIT ?",
        parameters + [cursor, limit + 1],
    )
    jobs = [dict(row) for row in rows]
    return {"jobs": jobs[:limit], "next_cursor": jobs[limit - 1]["id"] if len(jobs) > limit else None}


def get_job(database: sqlite3.Connection, job_id: int) -> dict:
    if not 1 <= job_id < 2**63:
        raise ValueError("job ID must be 1..2^63-1")
    row = database.execute(
        "SELECT " + SUMMARY + ", j.description, j.locations, j.employment_type, "
        "j.external_id, j.first_seen_at, j.closed_at, s.url AS feed_url, s.last_success_at"
        + SOURCE_JOIN + " WHERE j.id = ?", (job_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"job {job_id} not found")
    return dict(row)
