import json
import unittest
from pathlib import Path

from jobsh.personio import parse_feed, personio_hosts

FIXTURES = Path(__file__).parents[1] / "testdata"


class PersonioTest(unittest.TestCase):
    def test_common_crawl_hosts_are_unique(self) -> None:
        records = [
            json.loads(line)
            for line in (FIXTURES / "common-crawl.jsonl").read_text().splitlines()
        ]
        self.assertEqual(
            personio_hosts(records),
            ["alpha.jobs.personio.de", "beta.jobs.personio.de"],
        )

    def test_feed_requires_personio_xml_with_complete_positions(self) -> None:
        self.assertEqual(parse_feed((FIXTURES / "personio.xml").read_bytes()), 1)
        self.assertEqual(
            parse_feed(
                b'<workzag-jobs xmlns="urn:personio"><position>'
                b"<id> 1 </id><name> Developer </name>"
                b"</position></workzag-jobs>"
            ),
            1,
        )
        with self.assertRaises(ValueError):
            parse_feed(b"<html></html>")
        with self.assertRaises(ValueError):
            parse_feed(b"<workzag-jobs><position><id>1</id></position></workzag-jobs>")
        with self.assertRaises(ValueError):
            parse_feed(
                b"<workzag-jobs><position><id> </id><name>Developer</name>"
                b"</position></workzag-jobs>"
            )
        with self.assertRaisesRegex(ValueError, "duplicate position id"):
            parse_feed(
                b"<workzag-jobs><position><id>1</id><name>A</name></position>"
                b"<position><id>1</id><name>B</name></position></workzag-jobs>"
            )
        with self.assertRaisesRegex(ValueError, "DOCTYPE is not allowed"):
            parse_feed(b"<!DOCTYPE jobs><workzag-jobs />")


if __name__ == "__main__":
    unittest.main()
