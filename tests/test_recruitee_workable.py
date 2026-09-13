import json
import unittest

from jobsh.adapters import recruitee, workable


class RecruiteeWorkableTest(unittest.TestCase):
    def test_sources_and_normalization(self):
        self.assertEqual(recruitee.source("https://acme.recruitee.com/o/python"),
                         ("acme", "https://acme.recruitee.com/api/offers/"))
        self.assertEqual(workable.source("https://apply.workable.com/acme/j/ABC/"),
                         ("acme", "https://apply.workable.com/api/v1/widget/accounts/acme?details=true"))
        self.assertIsNone(recruitee.source("https://recruitee.com/o/python"))
        self.assertIsNone(recruitee.source("https://docs.recruitee.com/reference/offers"))
        self.assertIsNone(workable.source("https://apply.workable.com/j/ABC"))

        offer = {
            "id": 1, "title": "Python Engineer", "description": "Build", "requirements": "Python",
            "locations": [{"city": "Berlin", "state": "Berlin", "country": "Deutschland"}],
            "hybrid": True, "remote": False, "on_site": False, "employment_type_code": "fulltime",
            "department": "Engineering", "careers_url": "https://acme.recruitee.com/o/python",
            "published_at": "2026-09-12 10:00:00 UTC",
        }
        job = {
            "shortcode": "ABC", "title": "Python Engineer", "description": "Build with Python",
            "locations": [{"city": "Berlin", "region": "Berlin", "country": "Germany", "hidden": False}],
            "telecommuting": False, "employment_type": "Full-time", "department": "Engineering",
            "url": "https://apply.workable.com/j/ABC", "published_on": "2026-09-12",
        }
        first, = recruitee.normalize_feed(json.dumps({"offers": [offer]}).encode())
        second, = workable.normalize_feed(json.dumps({"jobs": [job]}).encode())
        self.assertEqual((first["work_mode"], first["location_text"]), ("hybrid", "Berlin, Berlin, Deutschland"))
        self.assertEqual((second["work_mode"], second["location_text"]), ("onsite", "Berlin, Berlin, Germany"))

        for normalize, payload in ((recruitee.normalize_feed, {}), (workable.normalize_feed, {"jobs": [job, job]})):
            with self.assertRaises(ValueError):
                normalize(json.dumps(payload).encode())


if __name__ == "__main__":
    unittest.main()
