import json
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from jobsh.adapters import ADAPTERS


class PlatformPagesTest(unittest.TestCase):
    def test_sources_are_limited_to_job_pages(self):
        cases = {
            "jobvite": "https://jobs.jobvite.com/acme/job/abc",
            "onlyfy": "https://acme.onlyfy.io/job/abc",
            "softgarden": "https://acme.softgarden.io/job/abc",
            "teamtailor": "https://acme.teamtailor.com/jobs/abc",
            "successfactors": "https://career8.successfactors.eu/career/jobreq?jobId=abc",
            "bamboohr": "https://acme.bamboohr.com/careers/123",
            "icims": "https://careers-acme.icims.com/jobs/123/title",
        }
        for provider, url in cases.items():
            with self.subTest(provider=provider):
                self.assertEqual(ADAPTERS[provider].source(url), (url, url))
                parsed = urlsplit(url)
                invalid = f"https://example.invalid{parsed.path}" + (f"?{parsed.query}" if parsed.query else "")
                self.assertIsNone(ADAPTERS[provider].source(invalid))

    def test_all_adapters_parse_public_jobposting(self):
        page = b'''<script type="application/ld+json">{"@type":"JobPosting","title":"Engineer","description":"Build","identifier":"123","url":"/jobs/123","jobLocation":{"address":{"addressLocality":"Berlin"}}}</script>'''
        for provider in ("jobvite", "onlyfy", "softgarden", "teamtailor", "successfactors", "bamboohr", "icims"):
            with self.subTest(provider=provider):
                with patch("jobsh.adapters.jsonld.fetch", return_value=page):
                    record, = ADAPTERS[provider].fetch_records("https://jobs.example/123", 1)
                self.assertEqual((record["external_id"], record["title"]), ("123", "Engineer"))
                self.assertEqual(json.loads(record["locations"]), ["Berlin"])
