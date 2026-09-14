import json
import unittest
from unittest.mock import patch

from jobsh.adapters import workday

URL = "https://acme.wd3.myworkdayjobs.com/wday/cxs/acme/External/jobs"
POSTING = {"title": "Python Engineer", "externalPath": "/job/Berlin/Python-Engineer_JR-1"}
POSTING |= {"locationsText": "Berlin, Germany", "remoteType": "Hybrid"}


class WorkdayTest(unittest.TestCase):
    def test_later_pages_may_omit_total(self):
        postings = [POSTING | {"externalPath": f"/job/Berlin/{index}"} for index in range(21)]
        with patch("jobsh.adapters.workday.fetch", side_effect=[
            json.dumps({"total": 21, "jobPostings": postings[:20]}).encode(),
            json.dumps({"total": 0, "jobPostings": postings[20:]}).encode(),
        ]):
            self.assertEqual(workday._postings(URL, 3), postings)

    def test_source_and_complete_feed(self):
        self.assertEqual(workday.source(
            "https://acme.wd3.myworkdayjobs.com/en-US/External/job/Berlin/Python-Engineer_JR-1"
        ), ("acme.wd3.myworkdayjobs.com:External", URL))
        self.assertIsNone(workday.source("https://acme.wd3.myworkdayjobs.com/en-US/External"))
        self.assertIsNone(workday.source("https://acme.wd3.myworkdayjobs.com.evil/External/job/x"))

        with patch("jobsh.adapters.workday.fetch", side_effect=[
            json.dumps({"total": 1, "jobPostings": [POSTING]}).encode(),
        ]) as fetch:
            record, = workday.fetch_records(URL, 3)
        self.assertEqual((record["title"], record["location_text"], record["work_mode"]),
                         ("Python Engineer", "Berlin, Germany", "hybrid"))
        self.assertEqual(fetch.call_args_list[0].kwargs["json"]["offset"], 0)

        for page in ({}, {"total": 1, "jobPostings": []},
                     {"total": 2, "jobPostings": [POSTING, POSTING]}):
            with patch("jobsh.adapters.workday.fetch", return_value=json.dumps(page).encode()), \
                    self.assertRaises(ValueError):
                workday.fetch_records(URL, 3)


if __name__ == "__main__":
    unittest.main()
