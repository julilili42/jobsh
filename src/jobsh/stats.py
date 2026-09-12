import sqlite3


def stats(database: sqlite3.Connection) -> list[dict]:
    rows = database.execute(
        """SELECT s.provider,
                  COUNT(*) AS sources,
                  (SELECT COUNT(*) FROM jobs j
                   JOIN sources js ON js.id = j.source_id
                   WHERE js.provider = s.provider AND j.closed_at IS NULL) AS open_jobs,
                  (SELECT COUNT(*) FROM sync_runs r
                   JOIN sources rs ON rs.id = r.source_id
                   WHERE rs.provider = s.provider) AS syncs,
                  (SELECT COUNT(*) FROM sync_runs r
                   JOIN sources rs ON rs.id = r.source_id
                   WHERE rs.provider = s.provider AND r.status = 'succeeded') AS successes,
                  (SELECT MAX(r.finished_at) FROM sync_runs r
                   JOIN sources rs ON rs.id = r.source_id
                   WHERE rs.provider = s.provider AND r.status = 'succeeded') AS last_success_at,
                  (SELECT r.finished_at FROM sync_runs r
                   JOIN sources rs ON rs.id = r.source_id
                   WHERE rs.provider = s.provider AND r.status = 'failed'
                   ORDER BY r.finished_at DESC, r.id DESC LIMIT 1) AS last_failure_at,
                  (SELECT r.error FROM sync_runs r
                   JOIN sources rs ON rs.id = r.source_id
                   WHERE rs.provider = s.provider AND r.status = 'failed'
                   ORDER BY r.finished_at DESC, r.id DESC LIMIT 1) AS last_error
           FROM sources s GROUP BY s.provider ORDER BY s.provider"""
    )
    result = []
    for row in rows:
        item = dict(row)
        successes = item.pop("successes")
        item["success_rate"] = successes / item["syncs"] if item["syncs"] else None
        result.append(item)
    return result


def candidate_errors(database: sqlite3.Connection) -> list[dict]:
    return [
        dict(row)
        for row in database.execute(
            """SELECT provider, error, COUNT(*) AS candidates, MIN(url) AS example_url
               FROM discovery_candidates WHERE error IS NOT NULL
               GROUP BY provider, error
               ORDER BY candidates DESC, provider, error"""
        )
    ]
