import json
import unittest
from unittest.mock import patch

from jobsh.db import connect
from jobsh.adapters.greenhouse import normalize_feed, source
from jobsh.sources import register_source, sync

JOB = {"id": 42, "title": "Software Engineer", "absolute_url": "https://example.org/jobs/42",
       "location": {"name": "Remote, Germany"}, "content": "&lt;p&gt;Python&lt;/p&gt;",
       "departments": [{"name": "Engineering"}]}


def feed(jobs):
    return json.dumps({"jobs": jobs, "meta": {"total": len(jobs)}}).encode()


class GreenhouseTest(unittest.TestCase):
    def test_board_urls(self):
        expected = ("acme", "https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true")
        for url in ("https://boards.greenhouse.io/acme/jobs/42",
                    "https://job-boards.greenhouse.io/acme",
                    "https://boards.greenhouse.io/embed/job_app?for=acme&token=42"):
            self.assertEqual(source(url), expected)
        for url in ("https://boards.greenhouse.io.evil/acme", "https://boards.greenhouse.io/",
                    "https://boards.greenhouse.io/embed/job_app"):
            self.assertIsNone(source(url))

    def test_normalization_and_validation(self):
        record = normalize_feed(feed([JOB]))[0]
        self.assertEqual(record["description"], "<p>Python</p>")
        self.assertEqual(record["work_mode"], "remote")
        self.assertEqual(record["location_text"], "Remote, Germany")
        self.assertIsNone(record["published_at"])
        for data in (b'{}', b'{"jobs": null}', feed([JOB, JOB]), feed([JOB | {"content": None}]),
                     b'{"jobs": [], "meta": {"total": 1}}'):
            with self.assertRaises(ValueError):
                normalize_feed(data)
        self.assertEqual(normalize_feed(feed([])), [])

    @patch("jobsh.adapters.greenhouse.fetch")
    def test_sync_and_failed_feed_preserve_jobs(self, fetch):
        database = connect(":memory:")
        self.addCleanup(database.close)
        with database:
            register_source(database, "greenhouse", "acme", source("https://boards.greenhouse.io/acme")[1], "manual")
        fetch.return_value = feed([JOB])
        self.assertEqual(sync(database, 3), (1, 0))
        self.assertEqual(database.execute("SELECT title FROM jobs").fetchone()[0], JOB["title"])
        fetch.return_value = b'{}'
        self.assertEqual(sync(database, 3), (0, 1))
        self.assertEqual(database.execute("SELECT missing_imports FROM jobs").fetchone()[0], 0)
