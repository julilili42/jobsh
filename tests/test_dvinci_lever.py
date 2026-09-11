import json
import unittest
from unittest.mock import patch

from jobsh.adapters import dvinci, lever


def encoded(value):
    return json.dumps(value).encode()


DVINCI = {
    "id": 1, "position": "Python Engineer",
    "jobPublicationURL": "https://acme.dvinci.de/de/jobs/1/python-engineer",
    "startDate": "2026-09-11", "introduction": "Intro", "tasks": "Python",
    "profile": "Profile", "weOffer": "Hybrid work", "closingText": "Apply",
    "jobOpening": {
        "location": "Berlin", "locations": [{"name": "Berlin"}, {"name": "Hamburg"}],
        "workingTimes": [{"name": "Full-time"}], "categories": [{"name": "Engineering"}],
    },
}
LEVER = {
    "id": "job-1", "text": "Python Engineer",
    "hostedUrl": "https://jobs.eu.lever.co/acme/job-1", "description": "<p>Python</p>",
    "categories": {"location": "Berlin", "allLocations": ["Berlin", "Hamburg"],
                   "commitment": "Full-time", "department": "Engineering"},
    "workplaceType": "hybrid", "createdAt": 1000,
}


class DvinciLeverTest(unittest.TestCase):
    def test_sources(self):
        self.assertEqual(dvinci.source("https://acme.dvinci.de/de/jobs/1/x"),
                         ("acme", "https://acme.dvinci.de/jobPublication/list.json?maxCacheAge=3600"))
        self.assertEqual(dvinci.source("https://acme.dvinci.de/portal/tech/de/jobs/1/x"),
                         ("acme:tech", "https://acme.dvinci.de/portal/tech/jobPublication/list.json?maxCacheAge=3600"))
        self.assertEqual(lever.source("https://jobs.lever.co/acme/job-1"),
                         ("acme", "https://api.lever.co/v0/postings/acme"))
        self.assertEqual(lever.source("https://jobs.eu.lever.co/acme/job-1"),
                         ("eu:acme", "https://api.eu.lever.co/v0/postings/acme"))
        for parser, url in ((dvinci.source, "https://acme.dvinci.de.evil/x"),
                            (lever.source, "https://jobs.lever.co.evil/acme/x")):
            self.assertIsNone(parser(url))

    def test_normalization(self):
        dvinci_record, = dvinci.normalize_feed(encoded([DVINCI]))
        lever_record, = lever.normalize_feed(encoded([LEVER]))
        self.assertEqual(json.loads(dvinci_record["locations"]), ["Berlin", "Hamburg"])
        self.assertEqual(dvinci_record["work_mode"], "hybrid")
        self.assertEqual(dvinci_record["source_category"], "Engineering")
        self.assertEqual(json.loads(lever_record["locations"]), ["Berlin", "Hamburg"])
        self.assertEqual(lever_record["work_mode"], "hybrid")
        self.assertEqual(lever_record["published_at"], "1970-01-01T00:00:01+00:00")
        for normalize, value in ((dvinci.normalize_feed, [DVINCI, DVINCI]),
                                 (lever.normalize_feed, [LEVER, LEVER])):
            with self.assertRaises(ValueError):
                normalize(encoded(value))

    def test_lever_pagination_and_verification(self):
        first = [LEVER | {"id": f"job-{index}"} for index in range(100)]
        with patch("jobsh.adapters.lever.fetch",
                   side_effect=[encoded(first), encoded([LEVER | {"id": "job-100"}])]) as fetch:
            self.assertEqual(len(lever.fetch_records("https://api.lever.co/v0/postings/acme", 3)), 101)
            self.assertIn("skip=100", fetch.call_args_list[1].args[0])
        with patch("jobsh.adapters.lever.fetch", return_value=encoded([LEVER])) as fetch:
            lever.verify_feed("https://api.lever.co/v0/postings/acme", 3)
            self.assertIn("limit=1", fetch.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
