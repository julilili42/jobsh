import tempfile
import unittest
from unittest.mock import Mock
from pathlib import Path
from unittest.mock import patch

from jobsh.db import connect, register_source
from jobsh.http import fetch as http_fetch
from jobsh.sync import sync
import httpx

FEED_URL = "https://example.jobs.personio.de/xml?language=de"
FEED = (Path(__file__).parents[1] / "testdata/personio.xml").read_bytes()
EMPTY = b"<workzag-jobs />"


class SafeReimportsTest(unittest.TestCase):
    @patch("jobsh.adapters.personio.fetch")
    def test_same_external_id_is_isolated_between_sources(self, fetch):
        database = connect(":memory:")
        self.addCleanup(database.close)
        with database:
            for account in ("alpha", "beta"):
                register_source(database, "personio", account, f"https://{account}.jobs.personio.de/xml", "manual")
        fetch.return_value = FEED
        self.assertEqual(sync(database, 3), (2, 0))
        initial = database.execute("SELECT id, external_id FROM jobs ORDER BY source_id").fetchall()
        self.assertNotEqual(initial[0]["id"], initial[1]["id"])
        self.assertEqual(initial[0]["external_id"], initial[1]["external_id"])
        fetch.side_effect = lambda url, timeout: EMPTY if "alpha." in url else FEED
        for _ in range(2):
            database.execute("UPDATE sources SET next_sync_at = NULL")
            self.assertEqual(sync(database, 3), (2, 0))
        jobs = database.execute("SELECT id, closed_at, missing_imports FROM jobs ORDER BY source_id").fetchall()
        self.assertIsNotNone(jobs[0]["closed_at"])
        self.assertIsNone(jobs[1]["closed_at"])
        self.assertEqual(jobs[1]["missing_imports"], 0)
        self.assertEqual([job["id"] for job in jobs], [job["id"] for job in initial])

    def test_interrupted_or_oversized_download_preserves_existing_data(self):
        database = connect(":memory:")
        self.addCleanup(database.close)
        with database:
            register_source(database, "personio", "example", FEED_URL, "manual")
        with patch("jobsh.adapters.personio.fetch", return_value=FEED):
            self.assertEqual(sync(database, 3), (1, 0))
        before = dict(database.execute("SELECT * FROM jobs").fetchone())
        source = dict(database.execute("SELECT * FROM sources").fetchone())
        retries = []

        def interrupted():
            yield b"<workzag-jobs>"
            raise httpx.ReadTimeout("interrupted")

        for chunks in (interrupted(), iter([b"123456789012", b"123456789012"])):
            database.execute("UPDATE sources SET next_sync_at = NULL")
            response = Mock()
            response.iter_bytes.return_value = chunks
            with patch("jobsh.http.CLIENT.stream") as stream, patch(
                "jobsh.adapters.personio.fetch", side_effect=lambda url, timeout: http_fetch(url, timeout, limit=20)
            ):
                stream.return_value.__enter__.return_value = response
                self.assertEqual(sync(database, 3), (0, 1))
            self.assertEqual(dict(database.execute("SELECT * FROM jobs").fetchone()), before)
            final_source = dict(database.execute("SELECT * FROM sources").fetchone())
            self.assertEqual(
                {key: value for key, value in final_source.items() if key not in {"next_sync_at", "failure_count"}},
                {key: value for key, value in source.items() if key not in {"next_sync_at", "failure_count"}},
            )
            self.assertGreater(final_source["failure_count"], source["failure_count"])
            retries.append(final_source["next_sync_at"])
            source = final_source
        self.assertGreater(retries[1], retries[0])

    def test_existing_database_is_upgraded_without_losing_jobs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "old.db"
            database = connect(path)
            with database:
                register_source(database, "personio", "example", FEED_URL, "manual")
            with patch("jobsh.adapters.personio.fetch", return_value=FEED):
                self.assertEqual(sync(database, 3), (1, 0))
            database.execute("ALTER TABLE jobs DROP COLUMN missing_imports")
            database.execute("DROP INDEX sources_due")
            database.execute("ALTER TABLE sources DROP COLUMN next_sync_at")
            database.execute("ALTER TABLE sources DROP COLUMN failure_count")
            before = dict(database.execute("SELECT * FROM jobs").fetchone())
            database.close()
            for _ in range(2):
                database = connect(path)
                self.assertEqual(
                    dict(database.execute("SELECT * FROM jobs").fetchone()),
                    before | {"missing_imports": 0},
                )
                self.assertEqual(
                    tuple(database.execute(
                        "SELECT next_sync_at, failure_count FROM sources"
                    ).fetchone()),
                    (None, 0),
                )
                database.close()

    @patch("jobsh.adapters.personio.fetch")
    def test_job_lifecycle_and_failed_imports(self, fetch):
        database = connect(":memory:")
        self.addCleanup(database.close)
        with database:
            register_source(database, "personio", "example", FEED_URL, "manual")

        def run(data):
            database.execute("UPDATE sources SET next_sync_at = NULL")
            fetch.side_effect = data if isinstance(data, Exception) else None
            fetch.return_value = data
            return sync(database, 3)

        def job():
            return dict(database.execute("SELECT * FROM jobs").fetchone())

        self.assertEqual(run(FEED), (1, 0))
        first = job()
        changed = FEED.replace(b"Python Developer", b"Senior Developer")
        self.assertEqual(run(changed), (1, 0))
        self.assertEqual(job()["title"], "Senior Developer")
        self.assertEqual(run(EMPTY), (1, 0))
        self.assertEqual(job()["missing_imports"], 1)
        self.assertIsNone(job()["closed_at"])
        before_failure = job()
        source = dict(database.execute("SELECT * FROM sources").fetchone())
        invalid = FEED.replace(b"</workzag-jobs>", b"<position><id>2</id></position></workzag-jobs>")
        for failure in (TimeoutError("timeout"), b"<broken", invalid):
            self.assertEqual(run(failure), (0, 1))
            self.assertEqual(job(), before_failure)
            failed_source = dict(database.execute("SELECT * FROM sources").fetchone())
            self.assertEqual(failed_source["last_success_at"], source["last_success_at"])
            self.assertGreater(failed_source["failure_count"], source["failure_count"])
            source = failed_source

        # A returning job resets the count before it ever closes.
        self.assertEqual(run(changed), (1, 0))
        self.assertEqual(job()["missing_imports"], 0)
        self.assertEqual(run(EMPTY), (1, 0))
        self.assertIsNone(job()["closed_at"])
        self.assertEqual(run(EMPTY), (1, 0))
        closed = job()
        self.assertIsNotNone(closed["closed_at"])
        self.assertEqual(run(EMPTY), (1, 0))
        self.assertEqual(job(), closed)
        self.assertEqual(run(changed), (1, 0))
        self.assertEqual(job()["id"], first["id"])
        self.assertEqual(job()["first_seen_at"], first["first_seen_at"])
        self.assertEqual(job()["missing_imports"], 0)
        self.assertIsNone(job()["closed_at"])

        # Even a failure after the upserts rolls back jobs and the success marker.
        before_failure = job()
        source = dict(database.execute("SELECT * FROM sources").fetchone())
        database.execute(
            "CREATE TRIGGER reject_success BEFORE INSERT ON sync_runs "
            "WHEN NEW.status = 'succeeded' BEGIN SELECT RAISE(ABORT, 'test failure'); END"
        )
        self.assertEqual(run(FEED), (0, 1))
        self.assertEqual(job(), before_failure)
        failed_source = dict(database.execute("SELECT * FROM sources").fetchone())
        self.assertEqual(failed_source["last_success_at"], source["last_success_at"])
        self.assertEqual(failed_source["failure_count"], source["failure_count"] + 1)
        self.assertEqual(database.execute(
            "SELECT status FROM sync_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()["status"], "failed")
