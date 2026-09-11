import json
import unittest
from contextlib import closing
from threading import Barrier
from unittest.mock import patch

from jobsh import ashby, smartrecruiters
from jobsh.adapters import ADAPTERS
from jobsh.db import connect
from jobsh.discovery import discover
from jobsh.sources import register_source, sync


def encoded(value):
    return json.dumps(value).encode()


ASHBY = {
    "id": "job-1", "title": "Python Engineer", "isListed": True,
    "jobUrl": "https://jobs.ashbyhq.com/acme/job-1", "descriptionHtml": "<p>Python</p>",
    "location": "Berlin", "secondaryLocations": [{"location": "Hamburg"}],
    "workplaceType": "Hybrid", "isRemote": True, "department": "Engineering",
    "employmentType": "FullTime", "publishedAt": "2026-09-11",
}
SMART = {
    "id": "1", "name": "Python Engineer", "active": True, "visibility": "PUBLIC",
    "location": {"city": "Berlin", "country": "de", "remote": True},
    "jobAd": {"sections": {"jobDescription": {"title": "Tasks", "text": "<p>Python</p>"}}},
}
SMART_URL = "https://api.smartrecruiters.com/v1/companies/acme/postings"


class NewAdaptersTest(unittest.TestCase):
    def test_sources_and_discovery(self):
        for provider, urls in (
            ("ashby", ["https://jobs.ashbyhq.com/acme/job-1/application"]),
            ("smartrecruiters", ["https://jobs.smartrecruiters.com/acme/1-title",
                                 "https://careers.smartrecruiters.com/acme/engineering"]),
        ):
            adapter = ADAPTERS[provider]
            for url in urls:
                self.assertEqual(adapter.source(url)[0], "acme")
                self.assertIsNone(adapter.source(url.replace(".com/", ".com.evil/")))
                self.assertIsNone(adapter.source(url.split("/acme")[0] + "/"))
            response = {"jobs": []} if provider == "ashby" else {"offset": 0, "totalFound": 100, "content": [{"id": "1"}]}
            with patch("jobsh.discovery.records", return_value=[{"url": url} for url in urls]), \
                    patch(f"jobsh.{provider}.fetch", return_value=encoded(response)) as fetch:
                result = discover(provider, 1, 1, 3)
                self.assertEqual(len(result), 1)
                self.assertEqual(result[0][0], "acme")
                self.assertEqual(fetch.call_count, 1)

    def test_ashby_normalization_and_validation(self):
        record, = ashby.normalize_feed(encoded({"jobs": [ASHBY, ASHBY | {"isListed": False}]}))
        self.assertEqual(record["work_mode"], "hybrid")
        self.assertEqual(json.loads(record["locations"]), ["Berlin", "Hamburg"])
        self.assertEqual(record["published_at"], "2026-09-11")
        self.assertEqual(json.loads(record["raw_record"]), ASHBY)
        for jobs in (None, [ASHBY, ASHBY], [ASHBY | {"descriptionHtml": None}],
                     [ASHBY | {"isListed": "false"}], [ASHBY | {"id": ""}],
                     [ASHBY | {"secondaryLocations": None}]):
            with self.assertRaises(ValueError):
                ashby.normalize_feed(encoded({"jobs": jobs}))
        self.assertEqual(ashby.normalize_feed(encoded({"jobs": []})), [])

    def test_smartrecruiters_pagination_and_parallel_details(self):
        barrier = Barrier(2)

        def fetch(url, timeout):
            if "offset=0" in url:
                return encoded({"offset": 0, "totalFound": 3, "content": [{"id": "1"}, {"id": "2"}]})
            if "offset=2" in url:
                return encoded({"offset": 2, "totalFound": 3, "content": [{"id": "3", "releasedDate": "2026-09-11"}]})
            job_id = url.rsplit("/", 1)[-1]
            if job_id in ("1", "2"):
                barrier.wait(timeout=3)
            return encoded(SMART | {"id": job_id})

        with patch("jobsh.smartrecruiters.fetch", side_effect=fetch):
            records = smartrecruiters.fetch_records(SMART_URL, 3)
        self.assertEqual([r["external_id"] for r in records], ["1", "2", "3"])
        self.assertEqual(records[0]["description"], "Tasks\n<p>Python</p>")
        self.assertEqual(records[0]["work_mode"], "remote")
        self.assertEqual(records[0]["location_text"], "Berlin, de")
        self.assertEqual(records[2]["published_at"], "2026-09-11")
        for page in ({}, {"offset": 0, "totalFound": 1, "content": []},
                     {"offset": 0, "totalFound": 1, "content": [{"id": "../x"}]},
                     {"offset": 0, "totalFound": 2, "content": [{"id": "1"}, {"id": "1"}]}):
            with patch("jobsh.smartrecruiters.fetch", return_value=encoded(page)), self.assertRaises(ValueError):
                smartrecruiters.fetch_records(SMART_URL, 3)
        with patch("jobsh.smartrecruiters.fetch", return_value=encoded({"offset": 0, "totalFound": 0, "content": []})):
            self.assertEqual(smartrecruiters.fetch_records(SMART_URL, 3), [])
        for second in ({"offset": 1, "totalFound": 3, "content": [{"id": "2"}]},
                       {"offset": 1, "totalFound": 2, "content": [{"id": "1"}]},
                       {"offset": 1, "totalFound": 2, "content": []}):
            responses = [encoded({"offset": 0, "totalFound": 2, "content": [{"id": "1"}]}),
                         encoded(SMART), encoded(second)]
            with patch("jobsh.smartrecruiters.fetch", side_effect=responses), self.assertRaises(ValueError):
                smartrecruiters.fetch_records(SMART_URL, 3)

    def test_failed_imports_preserve_jobs_for_both_providers(self):
        for provider in ("ashby", "smartrecruiters"):
            with self.subTest(provider=provider), closing(connect(":memory:")) as database:
                with database:
                    register_source(database, provider, "acme", SMART_URL if provider == "smartrecruiters" else "https://api.ashbyhq.com/posting-api/job-board/acme", "manual")
                payloads = [encoded({"jobs": [ASHBY]})] if provider == "ashby" else [
                    encoded({"offset": 0, "totalFound": 1, "content": [{"id": "1"}]}), encoded(SMART),
                ]
                with patch(f"jobsh.{provider}.fetch", side_effect=payloads):
                    self.assertEqual(sync(database, 3), (1, 0))
                failures = [encoded({})] if provider == "ashby" else [
                    encoded({"offset": 0, "totalFound": 1, "content": [{"id": "1"}]}), OSError("timeout"),
                ]
                with patch(f"jobsh.{provider}.fetch", side_effect=failures):
                    self.assertEqual(sync(database, 3), (0, 1))
                self.assertEqual(tuple(database.execute("SELECT missing_imports, closed_at FROM jobs").fetchone()), (0, None))
