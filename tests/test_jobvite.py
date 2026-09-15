import unittest
from unittest.mock import patch

from jobsh.adapters import jobvite

FEED = b"""<?xml version=\"1.0\"?><result><job><id>abc</id><title>Engineer</title><category>Engineering</category><jobtype>Full-Time</jobtype><location>Remote, Germany</location><date>9/14/2026</date><description>&lt;p&gt;Build&lt;/p&gt;</description></job></result>"""


class JobviteTest(unittest.TestCase):
    def test_full_board_feed(self):
        with patch("jobsh.adapters.jobvite.fetch", side_effect=[b"companyEId: 'q6jaVfwe'", FEED]):
            record, = jobvite.fetch_records("https://jobs.jobvite.com/acme", 1)
        self.assertEqual(record["external_id"], "abc")
        self.assertEqual(record["original_url"], "https://jobs.jobvite.com/acme/job/abc")
        self.assertEqual(record["published_at"], "2026-09-14")
        self.assertEqual(record["work_mode"], "remote")

    def test_rejects_invalid_feed(self):
        with self.assertRaisesRegex(ValueError, "unique id"):
            jobvite.normalize_feed(b"<result><job><id>1</id><title>A</title></job><job><id>1</id><title>B</title></job></result>", "https://jobs.jobvite.com/acme")
