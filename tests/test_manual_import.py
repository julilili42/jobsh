import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from threading import Barrier, Event, Lock
from time import sleep
from unittest.mock import Mock, patch

from jobsh.db import connect, register_source, save_jobs
from jobsh.adapters.personio import normalize_feed
from jobsh.sync import sync

FIXTURE = Path(__file__).parents[1] / "testdata" / "personio.xml"
FEED_URL = "https://example.jobs.personio.de/xml?language=de"


class ManualImportTest(unittest.TestCase):
    def test_sync_saves_completed_source_before_slow_source(self):
        database = connect(":memory:")
        self.addCleanup(database.close)
        saved = Event()

        def adapter(url, timeout):
            if "slow" in url:
                if not saved.wait(3):
                    raise ValueError("fast source was not saved")
            return []

        database.create_function("notify_saved", 0, lambda: saved.set() or 0)
        database.execute(
            "CREATE TEMP TRIGGER notify_sync AFTER INSERT ON sync_runs "
            "WHEN new.source_id = 2 BEGIN SELECT notify_saved(); END"
        )
        with database:
            for account in ("slow", "fast"):
                register_source(database, "example", account, f"https://{account}.example", "manual")
        with patch.dict("jobsh.sync.ADAPTERS", {"example": SimpleNamespace(fetch_records=adapter)}):
            self.assertEqual(sync(database, 3, workers=2), (2, 0))

    def test_sync_fetches_sources_concurrently(self) -> None:
        database = connect(":memory:")
        self.addCleanup(database.close)
        barrier = Barrier(2)

        def adapter(url, timeout):
            barrier.wait(timeout=1)
            return []

        with database, patch.dict("jobsh.sync.ADAPTERS", {"example": SimpleNamespace(fetch_records=adapter)}, clear=True):
            for account in ("one", "two"):
                register_source(database, "example", account, f"https://{account}.example", "manual")
            self.assertEqual(sync(database, 3, workers=2), (2, 0))

    def test_sync_uses_source_provider(self) -> None:
        database = connect(":memory:")
        self.addCleanup(database.close)
        adapter = Mock(return_value=[])
        with database, patch.dict("jobsh.sync.ADAPTERS", {"example": SimpleNamespace(fetch_records=adapter)}, clear=True):
            register_source(database, "example", "account", "https://example.test/jobs", "manual")
            self.assertEqual(sync(database, 3), (1, 0))
        adapter.assert_called_once_with("https://example.test/jobs", 3)

    def test_register_updates_feed_without_duplicating_company(self) -> None:
        database = connect(":memory:")
        self.addCleanup(database.close)
        register_source(database, "personio", "example", FEED_URL, "common-crawl", "2026-09-01")
        first = dict(database.execute("SELECT * FROM sources").fetchone())
        new_url = FEED_URL.replace("language=de", "language=en")
        register_source(database, "personio", "example", new_url, "manual")
        final = dict(database.execute("SELECT * FROM sources").fetchone())
        self.assertEqual(final, first | {"url": new_url, "discovery": "manual"})
        self.assertEqual(database.execute("SELECT count(*) FROM companies").fetchone()[0], 1)
        self.assertEqual(database.execute("SELECT count(*) FROM sources").fetchone()[0], 1)

    @patch("jobsh.adapters.personio.fetch")
    def test_sync_continues_after_invalid_feed(self, fetch) -> None:
        database = connect(":memory:")
        self.addCleanup(database.close)
        with database:
            register_source(database, "personio", "broken", FEED_URL.replace("example", "broken"), "manual")
            register_source(database, "personio", "example", FEED_URL, "manual")
        fetch.side_effect = [b"<broken", FIXTURE.read_bytes()]
        self.assertEqual(sync(database, 3), (1, 1))
        runs = database.execute("SELECT status, error FROM sync_runs ORDER BY id").fetchall()
        self.assertEqual([tuple(row) for row in runs], [
            ("failed", "invalid Personio XML"), ("succeeded", None),
        ])
        self.assertEqual(database.execute("SELECT count(*) FROM jobs").fetchone()[0], 1)

    def test_upsert_preserves_identity_and_first_seen(self) -> None:
        database = connect(":memory:")
        self.addCleanup(database.close)
        register_source(database, "personio", "example", FEED_URL, "common-crawl")
        source_id = database.execute("SELECT id FROM sources").fetchone()["id"]
        records = normalize_feed(FIXTURE.read_bytes(), FEED_URL)
        self.assertEqual(save_jobs(database, source_id, records, "2026-09-01"), (1, 0, 0))
        first = dict(database.execute("SELECT * FROM jobs").fetchone())
        self.assertEqual(save_jobs(database, source_id, records, "2026-09-02"), (0, 0, 1))
        changed = normalize_feed(
            FIXTURE.read_bytes().replace(b"Python Developer", b"Senior Developer"), FEED_URL
        )
        changed[0].update(
            description="New duties", locations='["Hamburg"]', location_text="Hamburg", work_mode="hybrid",
            employment_type="part-time", original_url="https://example.com/new-job",
            published_at="2026-09-02", source_category="IT",
            content_hash="updated-hash", raw_record="<position>updated</position>",
        )
        self.assertEqual(save_jobs(database, source_id, changed, "2026-09-03"), (0, 1, 0))
        final = dict(database.execute("SELECT * FROM jobs").fetchone())
        self.assertEqual(final["id"], first["id"])
        self.assertEqual(final["first_seen_at"], "2026-09-01")
        self.assertEqual(final["last_seen_at"], "2026-09-03")
        for key, value in changed[0].items():
            self.assertEqual(final[key], value, key)

    @patch("jobsh.adapters.personio.fetch")
    def test_reimport_keeps_the_job_and_updates_changed_content(self, fetch) -> None:
        original = FIXTURE.read_bytes()
        changed = original.replace(b"Python Developer", b"Senior Python Developer")
        fetch.side_effect = [original, original, changed]

        with tempfile.TemporaryDirectory() as directory:
            database = connect(Path(directory) / "jobsh.db")
            self.addCleanup(database.close)
            with database:
                register_source(database, "personio", "example", FEED_URL, "common-crawl")

            self.assertEqual(sync(database, 3), (1, 0))
            first = database.execute("SELECT id, title FROM jobs").fetchone()
            database.execute("UPDATE sources SET next_sync_at = NULL")
            self.assertEqual(sync(database, 3), (1, 0))
            second = database.execute("SELECT id, title FROM jobs").fetchone()
            database.execute("UPDATE sources SET next_sync_at = NULL")
            self.assertEqual(sync(database, 3), (1, 0))
            final = database.execute("SELECT id, title FROM jobs").fetchone()

            self.assertEqual(database.execute("SELECT count(*) FROM jobs").fetchone()[0], 1)
            self.assertEqual((first["id"], second["id"], final["id"]), (1, 1, 1))
            self.assertEqual(final["title"], "Senior Python Developer")
            self.assertEqual(
                [tuple(row) for row in database.execute(
                    """
                    SELECT created_count, updated_count, unchanged_count
                    FROM sync_runs ORDER BY id
                    """
                )],
                [(1, 0, 0), (0, 0, 1), (0, 1, 0)],
            )

    def test_sync_only_fetches_due_sources_and_limits_each_host(self):
        database = connect(":memory:")
        self.addCleanup(database.close)
        active = peak = calls = 0
        lock = Lock()

        def adapter(url, timeout):
            nonlocal active, peak, calls
            with lock:
                active += 1
                peak = max(peak, active)
                calls += 1
            sleep(.02)
            with lock:
                active -= 1
            return []

        with database:
            for account in ("one", "two", "three"):
                register_source(database, "example", account, f"https://example.test/{account}", "manual")
        with patch.dict("jobsh.sync.ADAPTERS", {"example": SimpleNamespace(fetch_records=adapter)}, clear=True):
            self.assertEqual(sync(database, 3, workers=3), (3, 0))
            self.assertEqual(sync(database, 3, workers=3), (0, 0))
        self.assertEqual((calls, peak), (3, 3))


if __name__ == "__main__":
    unittest.main()
