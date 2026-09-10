import re
import sqlite3

JOB_SELECT = (
    "SELECT j.*, s.url AS feed_url, s.provider, s.provider_account, s.last_success_at "
    "FROM jobs j JOIN sources s ON s.id = j.source_id"
)


def search(
    database: sqlite3.Connection, query: str = "", *, title: str = "",
    location: str = "", work_mode: str | None = None, limit: int = 20, offset: int = 0,
) -> list[dict]:
    if not 1 <= limit <= 100 or offset < 0:
        raise ValueError("limit must be 1..100 and offset must be >= 0")
    if work_mode not in (None, "remote", "hybrid", "onsite", "unknown"):
        raise ValueError("invalid work mode")
    if len(query) > 1000:
        raise ValueError("query must be at most 1000 characters")
    conditions = ["j.it_classification = 'it'", "j.closed_at IS NULL"]
    parameters = []
    terms = []
    for term in query.split():
        if any(special in term.lower() for special in ("c++", "c#", ".net")):
            conditions.append("instr(lower(j.title || ' ' || coalesce(j.description, '')), ?) > 0")
            parameters.append(term.lower())
        elif re.search(r"\w", term):
            terms.append('"' + term.replace('"', '""') + '"')
        else:
            raise ValueError("query terms must contain letters or numbers")
    if terms:
        conditions.append("j.id IN (SELECT rowid FROM jobs_fts WHERE jobs_fts MATCH ?)")
        parameters.append(" AND ".join(terms))
    for column, value in (("title", title), ("location_text", location)):
        if value:
            conditions.append(f"instr(lower(coalesce(j.{column}, '')), lower(?)) > 0")
            parameters.append(value)
    if work_mode:
        conditions.append("j.work_mode = ?")
        parameters.append(work_mode)
    rows = database.execute(
        JOB_SELECT + " WHERE " + " AND ".join(conditions) + " ORDER BY j.id LIMIT ? OFFSET ?",
        parameters + [limit, offset],
    )
    return [dict(row) for row in rows]


def get_job(database: sqlite3.Connection, job_id: int) -> dict:
    if job_id < 1:
        raise ValueError("job ID must be positive")
    row = database.execute(
        JOB_SELECT + " WHERE j.id = ?", (job_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"job {job_id} not found")
    return dict(row)
