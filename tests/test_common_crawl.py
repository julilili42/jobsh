import unittest
from unittest.mock import patch

from jobsh.common_crawl import latest_snapshot, records


class CommonCrawlTest(unittest.TestCase):
    @patch("jobsh.common_crawl.fetch")
    def test_latest_snapshot_uses_newest_collection(self, fetch) -> None:
        fetch.return_value = b"""[
            {"id":"old","cdx-api":"old-url","to":"2026-01-01"},
            {"id":"new","cdx-api":"new-url","to":"2026-02-01"}
        ]"""
        self.assertEqual(latest_snapshot(1), "new-url")

    @patch("jobsh.common_crawl.time.sleep")
    @patch("jobsh.common_crawl.fetch")
    def test_records_reads_all_snapshot_pages(self, fetch, sleep) -> None:
        fetch.side_effect = [
            b'[{"id":"snapshot","cdx-api":"index","to":"2026-01-01"}]',
            b'{"pages":2}',
            b'{"url":"https://one.example"}\n',
            b'{"url":"https://two.example"}\n',
        ]

        self.assertEqual(
            records("example.com", 1),
            [
                {"url": "https://one.example"},
                {"url": "https://two.example"},
            ],
        )
        sleep.assert_called_once_with(1)
