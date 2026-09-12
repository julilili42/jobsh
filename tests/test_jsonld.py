import json
import unittest
from unittest.mock import patch

from jobsh.adapters import ADAPTERS, jsonld
from jobsh.discovery import discover


JOB = {
    "@type": ["Thing", "https://schema.org/JobPosting"],
    "identifier": {"@type": "PropertyValue", "value": 42},
    "title": "Platform Engineer",
    "description": "<p>Hybrid role</p>",
    "datePosted": "2026-09-01",
    "employmentType": ["FULL_TIME", "PERMANENT"],
    "occupationalCategory": "Software Development",
    "url": "/careers/42",
    "jobLocation": {"address": {
        "addressLocality": "Berlin", "addressRegion": "Berlin",
        "addressCountry": {"name": "DE"},
    }},
}


def page(job=JOB):
    payload = json.dumps({"@context": "https://schema.org", "@graph": [
        {"@type": "Organization", "name": "Acme"}, job,
    ]})
    return f'''<html><script type="application/ld+json">not json</script>
        <script TYPE="application/ld+json; charset=utf-8"><!--{payload}--></script></html>'''.encode()


class JsonLdTest(unittest.TestCase):
    def test_source_and_nested_jobposting(self):
        url = "https://example.org/jobs/view?id=42#apply"
        self.assertEqual(jsonld.source(url), (url.removesuffix("#apply"), url.removesuffix("#apply")))
        for invalid in ("file:///tmp/job", "https:///jobs/42", "https://user@example.org/jobs/42"):
            self.assertIsNone(jsonld.source(invalid))

        record = jsonld.normalize_page(page(), url)[0]
        self.assertEqual(record["external_id"], "42")
        self.assertEqual(record["title"], "Platform Engineer")
        self.assertEqual(record["locations"], '["Berlin, DE"]')
        self.assertEqual(record["work_mode"], "hybrid")
        self.assertEqual(record["original_url"], "https://example.org/careers/42")
        self.assertEqual(record["employment_type"], "FULL_TIME; PERMANENT")

    def test_fetch_and_ambiguous_pages(self):
        url = "https://example.org/jobs/42"
        with patch("jobsh.adapters.jsonld.fetch", return_value=page()) as fetch:
            self.assertEqual(jsonld.fetch_records(url, 3)[0]["title"], "Platform Engineer")
            fetch.assert_called_once_with(url, 3)
        for data in (b"<html></html>", page({"@graph": [JOB, JOB | {"title": "Other"}]})):
            with self.assertRaises(ValueError):
                jsonld.normalize_page(data, url)

    def test_registered_but_not_discoverable(self):
        self.assertIs(ADAPTERS["jsonld"].fetch_records, jsonld.fetch_records)
        with self.assertRaisesRegex(ValueError, "does not support"):
            discover("jsonld", 0, 1, 1)
