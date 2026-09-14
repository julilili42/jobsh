import sqlite3
from datetime import UTC, datetime, timedelta


def stats(database: sqlite3.Connection) -> list[dict]:
    rows = database.execute(
        """WITH source_stats AS (
               SELECT provider, COUNT(*) AS sources FROM sources GROUP BY provider
           ), job_stats AS (
               SELECT s.provider,
                      SUM(j.closed_at IS NULL) AS open_jobs,
                      SUM(j.closed_at IS NULL AND j.description IS NOT NULL AND j.description <> '') AS described_open_jobs,
                      SUM(j.closed_at IS NULL AND s.last_success_at >= ?) AS fresh_open_jobs
               FROM jobs j JOIN sources s ON s.id = j.source_id GROUP BY s.provider
           ), run_stats AS (
               SELECT s.provider,
                      COUNT(r.id) AS syncs,
                      SUM(r.status = 'succeeded') AS successes,
                      MAX(CASE WHEN r.status = 'succeeded' THEN r.finished_at END) AS last_success_at
               FROM sources s LEFT JOIN sync_runs r ON r.source_id = s.id GROUP BY s.provider
           ), last_failures AS (
               SELECT provider, finished_at AS last_failure_at, error AS last_error FROM (
                   SELECT s.provider, r.finished_at, r.error,
                          ROW_NUMBER() OVER (PARTITION BY s.provider ORDER BY r.finished_at DESC, r.id DESC) AS rank
                   FROM sync_runs r JOIN sources s ON s.id = r.source_id WHERE r.status = 'failed'
               ) WHERE rank = 1
           )
           SELECT source_stats.provider, source_stats.sources,
                  COALESCE(job_stats.open_jobs, 0) AS open_jobs,
                  COALESCE(job_stats.described_open_jobs, 0) AS described_open_jobs,
                  COALESCE(job_stats.fresh_open_jobs, 0) AS fresh_open_jobs,
                  COALESCE(run_stats.syncs, 0) AS syncs,
                  COALESCE(run_stats.successes, 0) AS successes,
                  run_stats.last_success_at, last_failures.last_failure_at, last_failures.last_error
           FROM source_stats
           LEFT JOIN job_stats USING (provider)
           LEFT JOIN run_stats USING (provider)
           LEFT JOIN last_failures USING (provider)
           ORDER BY provider""",
        ((datetime.now(UTC) - timedelta(days=1)).isoformat(),),
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
