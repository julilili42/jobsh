import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from jobsh.cli import main
from jobsh.db import connect, fail_candidate, queue_candidates, register_source


class StatsTest(unittest.TestCase):
    def test_stats_reports_provider_coverage_and_sync_health(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "jobs.db"
            database = connect(path)
            with database:
                register_source(database, "personio", "one", "https://one.test", "manual")
                register_source(database, "personio", "two", "https://two.test", "manual")
                register_source(database, "greenhouse", "three", "https://three.test", "manual")
                source_id = database.execute(
                    "SELECT id FROM sources WHERE provider_account = 'one'"
                ).fetchone()[0]
                database.execute(
                    """INSERT INTO jobs
                       (source_id, external_id, title, locations, work_mode, original_url,
                        first_seen_at, last_seen_at, content_hash, raw_record)
                       VALUES (?, '1', 'Developer', '[]', 'remote', 'https://job.test',
                               '2026-01-01', '2026-01-01', 'hash', '{}')""",
                    (source_id,),
                )
                for status, finished, error in (
                    ("succeeded", "2026-01-01", None),
                    ("failed", "2026-01-02", "offline"),
                ):
                    database.execute(
                        """INSERT INTO sync_runs
                           (source_id, started_at, finished_at, status, duration_ms, error)
                           VALUES (?, ?, ?, ?, 1, ?)""",
                        (source_id, finished, finished, status, error),
                    )
            database.close()

            output = io.StringIO()
            with patch("sys.argv", ["jobsh", "--db", str(path), "stats", "--json"]), redirect_stdout(output):
                main()

            providers = {item["provider"]: item for item in json.loads(output.getvalue())}
            self.assertEqual(providers["personio"], {
                "provider": "personio", "sources": 2, "open_jobs": 1, "syncs": 2,
                "last_success_at": "2026-01-01", "last_failure_at": "2026-01-02",
                "last_error": "offline", "success_rate": 0.5,
            })
            self.assertIsNone(providers["greenhouse"]["success_rate"])

    def test_stats_ranks_discovery_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "jobs.db"
            database = connect(path)
            with database:
                queue_candidates(database, "personio", [
                    ("one", "https://one.jobs.personio.de"),
                    ("two", "https://two.jobs.personio.de"),
                    ("three", "https://three.jobs.personio.de"),
                ], 0)
                fail_candidate(database, "personio", "one", ValueError("invalid feed"))
                fail_candidate(database, "personio", "two", ValueError("invalid feed"))
                fail_candidate(database, "personio", "three", OSError("offline"))
            database.close()

            output = io.StringIO()
            with patch("sys.argv", ["jobsh", "--db", str(path), "stats", "--errors", "--json"]), \
                    redirect_stdout(output):
                main()

            self.assertEqual(json.loads(output.getvalue()), [
                {"provider": "personio", "error": "invalid feed", "candidates": 2,
                 "example_url": "https://one.jobs.personio.de"},
                {"provider": "personio", "error": "offline", "candidates": 1,
                 "example_url": "https://three.jobs.personio.de"},
            ])


if __name__ == "__main__":
    unittest.main()
