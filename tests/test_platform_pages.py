import json
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from jobsh.adapters import ADAPTERS


class PlatformPagesTest(unittest.TestCase):
    def test_sources_are_limited_to_job_pages(self):
        cases = {
            "jobvite": "https://jobs.jobvite.com/acme/job/abc",
            "softgarden": "https://acme.softgarden.io/job/abc",
            "teamtailor": "https://acme.teamtailor.com/jobs/abc",
        }
        for provider, url in cases.items():
            with self.subTest(provider=provider):
                expected = ("acme", "https://jobs.jobvite.com/acme") if provider == "jobvite" else (url, url)
                self.assertEqual(ADAPTERS[provider].source(url), expected)
                parsed = urlsplit(url)
                invalid = f"https://example.invalid{parsed.path}" + (f"?{parsed.query}" if parsed.query else "")
                self.assertIsNone(ADAPTERS[provider].source(invalid))
                self.assertIsNone(ADAPTERS[provider].source(url.replace("https://", "https://attacker@")))

    def test_all_adapters_parse_public_jobposting(self):
        page = b'''<script type="application/ld+json">{"@type":"JobPosting","title":"Engineer","description":"Build","identifier":"123","url":"/jobs/123","jobLocation":{"address":{"addressLocality":"Berlin"}}}</script>'''
        for provider in ("softgarden", "teamtailor"):
            with self.subTest(provider=provider):
                with patch("jobsh.adapters.jsonld.fetch", return_value=page):
                    record, = ADAPTERS[provider].fetch_records("https://jobs.example/123", 1)
                self.assertEqual((record["external_id"], record["title"]), ("123", "Engineer"))
                self.assertEqual(json.loads(record["locations"]), ["Berlin"])
