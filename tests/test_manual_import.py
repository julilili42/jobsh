import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jobsh.db import connect
from jobsh.jobs import register_feed, save_jobs, sync
from jobsh.personio_feed import normalize_feed

FIXTURE = Path(__file__).parents[1] / "testdata" / "personio.xml"
FEED_URL = "https://example.jobs.personio.de/xml?language=de"


class ManualImportTest(unittest.TestCase):
    def test_register_updates_feed_without_duplicating_company(self) -> None:
        database = connect(":memory:")
        self.addCleanup(database.close)
        register_feed(database, "example", FEED_URL, "common-crawl", "2026-09-01")
        first = dict(database.execute("SELECT * FROM sources").fetchone())
        new_url = FEED_URL.replace("language=de", "language=en")
        register_feed(database, "example", new_url, "manual")
        final = dict(database.execute("SELECT * FROM sources").fetchone())
        self.assertEqual(final, first | {"url": new_url, "discovery": "manual"})
        self.assertEqual(database.execute("SELECT count(*) FROM companies").fetchone()[0], 1)
        self.assertEqual(database.execute("SELECT count(*) FROM sources").fetchone()[0], 1)

    @patch("jobsh.personio_feed.fetch")
    def test_sync_continues_after_invalid_feed(self, fetch) -> None:
        database = connect(":memory:")
        self.addCleanup(database.close)
        with database:
            register_feed(database, "broken", FEED_URL.replace("example", "broken"), "manual")
            register_feed(database, "example", FEED_URL, "manual")
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
        register_feed(database, "example", FEED_URL, "common-crawl")
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
            german_eligibility_evidence="Germany", published_at="2026-09-02", source_category="IT",
            content_hash="updated-hash", raw_record="<position>updated</position>",
        )
        self.assertEqual(save_jobs(database, source_id, changed, "2026-09-03"), (0, 1, 0))
        final = dict(database.execute("SELECT * FROM jobs").fetchone())
        self.assertEqual(final["id"], first["id"])
        self.assertEqual(final["first_seen_at"], "2026-09-01")
        self.assertEqual(final["last_seen_at"], "2026-09-03")
        for key, value in changed[0].items():
            self.assertEqual(final[key], value, key)
        self.assertEqual((final["it_classification"], final["classification_rule"]), ("it", "category:it_with_role"))

    @patch("jobsh.personio_feed.fetch")
    def test_reimport_keeps_the_job_and_updates_changed_content(self, fetch) -> None:
        original = FIXTURE.read_bytes()
        changed = original.replace(b"Python Developer", b"Senior Python Developer")
        fetch.side_effect = [original, original, changed]

        with tempfile.TemporaryDirectory() as directory:
            database = connect(Path(directory) / "jobsh.db")
            self.addCleanup(database.close)
            with database:
                register_feed(database, "example", FEED_URL, "common-crawl")

            self.assertEqual(sync(database, 3), (1, 0))
            first = database.execute("SELECT id, title FROM jobs").fetchone()
            self.assertEqual(sync(database, 3), (1, 0))
            second = database.execute("SELECT id, title FROM jobs").fetchone()
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


if __name__ == "__main__":
    unittest.main()
