import json
import unittest
from unittest.mock import patch

from jobsh.adapters import ashby, dvinci, greenhouse, lever
from tests.test_dvinci_lever import DVINCI, LEVER
from tests.test_greenhouse import JOB
from tests.test_new_adapters import ASHBY


class JsonFeedTest(unittest.TestCase):
    def test_adapters_reject_invalid_jobs_without_returning_partial_feeds(self):
        for adapter, job, title, url, description in (
            (ashby, ASHBY, "title", "jobUrl", "descriptionHtml"),
            (greenhouse, JOB, "title", "absolute_url", "content"),
            (lever, LEVER, "text", "hostedUrl", "description"),
            (dvinci, DVINCI, "position", "jobPublicationURL", "tasks"),
        ):
            wrapped = adapter in (ashby, greenhouse)

            def feed(jobs, wrapped=wrapped):
                return json.dumps({"jobs": jobs} if wrapped else jobs).encode()

            with self.subTest(adapter=adapter.__name__):
                self.assertEqual(adapter.normalize_feed(feed([])), [])
                wrong_id = 1 if isinstance(job["id"], str) else "1"
                for field, value in (
                    ("id", None), ("id", True), ("id", wrong_id), ("id", ""), ("id", -1),
                    (title, " "), (title, None), (url, "file:///tmp/job"), (url, None),
                    (description, {"unexpected": "object"}),
                ):
                    with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                        changed = job | {"id": "second" if isinstance(job["id"], str) else 100}
                        adapter.normalize_feed(feed([job, changed | {field: value}]))
                for invalid in (b"{}", b"null", b"[", feed([job, job]), feed([job, {}])):
                    with self.subTest(payload=invalid[:50]), self.assertRaises(ValueError):
                        adapter.normalize_feed(invalid)

    def test_lever_rejects_duplicates_across_pages(self):
        first = [LEVER | {"id": str(i)} for i in range(100)]
        with patch("jobsh.adapters.lever.fetch", side_effect=[
            json.dumps(first).encode(), json.dumps(first[:1]).encode(),
        ]), self.assertRaisesRegex(ValueError, "across pages"):
            lever.fetch_records("https://api.lever.co/v0/postings/acme", 3)
