import json
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from jobsh.adapters import ADAPTERS, Adapter
from jobsh.db import checkpoint_discovery, connect
from jobsh.discovery import COLLECTIONS_URL, _read_json, discover, records
from jobsh.http import HTTPStatusError


class CommonCrawlTest(unittest.TestCase):
    @patch("jobsh.discovery.records")
    def test_discovery_prioritizes_saved_candidates_and_bounds_unlimited_runs(self, records_mock):
        database = connect(":memory:")
        self.addCleanup(database.close)
        adapter = Adapter(("boards.example",), lambda url: (url.rsplit("/", 1)[-1], url), Mock(return_value=[]))
        with database:
            checkpoint_discovery(database, "example", [("saved", "https://api.example/saved")], {})
        with patch.dict("jobsh.discovery.ADAPTERS", {"example": adapter}):
            self.assertEqual(
                [row[0] for row in discover("example", 1, 1, 3, database=database)], ["saved"]
            )
        records_mock.assert_not_called()

        records_mock.return_value = [
            {"url": f"https://api.example/{account}"} for account in ("one", "two", "three")
        ]
        with patch.dict("jobsh.discovery.ADAPTERS", {"example": adapter}), \
                patch("jobsh.discovery.DISCOVERY_BATCH", 2):
            self.assertEqual([row[0] for row in discover("example", 0, 1, 3)], ["one", "two"])

    @patch("jobsh.discovery.records")
    def test_discovery_reserves_capacity_for_fresh_candidates(self, records_mock):
        database = connect(":memory:")
        self.addCleanup(database.close)
        adapter = Adapter(("boards.example",), lambda url: (url.rsplit("/", 1)[-1], url), Mock(return_value=[]))
        with database:
            checkpoint_discovery(database, "example", [
                ("stale-one", "https://api.example/stale-one"),
                ("stale-two", "https://api.example/stale-two"),
            ], {})
            database.execute("UPDATE discovery_candidates SET retry_at = '2000-01-01T00:00:00+00:00'")
        records_mock.return_value = [{"url": "https://api.example/fresh"}]
        with patch.dict("jobsh.discovery.ADAPTERS", {"example": adapter}):
            result = discover("example", 2, 1, 3, database=database)
        self.assertEqual([row[0] for row in result], ["fresh", "stale-one"])
        records_mock.assert_called_once()

    @patch("jobsh.discovery.records")
    def test_discovery_limits_retries_to_half_the_batch(self, records_mock):
        database = connect(":memory:")
        self.addCleanup(database.close)
        adapter = Adapter(("boards.example",), lambda url: (url.rsplit("/", 1)[-1], url), Mock(return_value=[]))
        with database:
            checkpoint_discovery(database, "example", [
                (f"retry-{index}", f"https://api.example/retry-{index}") for index in range(4)
            ], {})
            database.execute("UPDATE discovery_candidates SET retry_at = '2000-01-01T00:00:00+00:00'")
        records_mock.return_value = [{"url": f"https://api.example/fresh-{index}"} for index in range(2)]
        with patch.dict("jobsh.discovery.ADAPTERS", {"example": adapter}):
            result = discover("example", 4, 1, 3, database=database)
        self.assertEqual([row[0] for row in result], ["fresh-0", "fresh-1", "retry-0", "retry-1"])

    def test_discovery_checkpoints_long_scans(self):
        database = connect(":memory:")
        self.addCleanup(database.close)
        state = {}

        def crawl(domain, timeout, cursor, collections):
            for offset in range(1000):
                cursor["offset"] = offset + 1
                yield {"url": "https://irrelevant.example"}
            raise OSError("interrupted")

        adapter = Adapter(("boards.example",), lambda url: None, Mock(return_value=[]))
        with patch("jobsh.discovery.records", side_effect=crawl), \
                patch.dict("jobsh.discovery.ADAPTERS", {"example": adapter}), \
                self.assertRaisesRegex(OSError, "interrupted"):
            discover("example", 0, 1, 3, states={"boards.example": state}, database=database)
        saved = database.execute(
            "SELECT state FROM discovery_state WHERE domain = 'boards.example'"
        ).fetchone()[0]
        self.assertEqual(json.loads(saved)["offset"], 1000)

    @patch("jobsh.discovery.records")
    def test_adapter_supports_accounts_in_url_paths(self, records_mock):
        records_mock.return_value = [
            {"url": "https://boards.example/known/1"},
            {"url": "https://boards.example/new/2"},
            {"url": "https://boards.example/new/3"},
        ]
        fetch = Mock(return_value=[])
        def source(url):
            account = urlsplit(url).path.split("/")[1]
            return account, f"https://api.example/{account}/jobs"
        adapter = Adapter(("boards.example",), source, fetch)
        with patch.dict("jobsh.discovery.ADAPTERS", {"example": adapter}):
            result = discover("example", 10, 2, 3, {"known"})
        self.assertEqual([row[:2] for row in result], [("new", "https://api.example/new/jobs")])
        fetch.assert_called_once_with("https://api.example/new/jobs", 3)
        records_mock.assert_called_once_with("boards.example", 3, {}, 1)

    @patch("jobsh.discovery.records")
    def test_adapter_discovers_across_domains_without_duplicate_accounts(self, records_mock):
        records_mock.side_effect = (
            [{"url": "https://one.example/acme/1"}, {"url": "https://one.example/later/1"}],
            [{"url": "https://two.example/other/1"}],
        )

        def source(url):
            account = urlsplit(url).path.split("/")[1]
            return account, f"https://api.example/{account}"

        adapter = Adapter(("one.example", "two.example"), source, Mock(return_value=[]))
        states = {}
        with patch.dict("jobsh.discovery.ADAPTERS", {"example": adapter}):
            result = discover("example", 2, 1, 3, states=states, collections=2)
        self.assertEqual([item[0] for item in result], ["acme", "other"])
        self.assertEqual(records_mock.call_args_list[0].args, ("one.example", 3, states["one.example"], 2))
        self.assertEqual(records_mock.call_args_list[1].args, ("two.example", 3, states["two.example"], 2))

    @patch("jobsh.discovery._read_json")
    def test_resume_inside_page_and_restart_for_new_collection(self, read):
        state = {}
        rows = [{"url": "https://one.example"}, {"url": "https://two.example"}]
        read.side_effect = lambda url, timeout, **kwargs: (
            [{"cdx-api": "index", "to": "2026"}] if url == COLLECTIONS_URL
            else rows if kwargs.get("lines") else {"pages": 1}
        )
        stream = records("example", 1, state)
        self.assertEqual(next(stream), rows[0])
        stream.close()
        self.assertEqual(list(records("example", 1, state)), rows[1:])
        self.assertEqual(list(records("example", 1, state)), [])
        state["endpoint"] = "old-index"
        self.assertEqual(list(records("example", 1, state)), rows)

    @patch("jobsh.discovery.fetch")
    def test_latest_snapshot_uses_newest_collection(self, fetch) -> None:
        fetch.return_value = b"""[
            {"id":"old","cdx-api":"old-url","to":"2026-01-01"},
            {"id":"new","cdx-api":"new-url","to":"2026-02-01"}
        ]"""
        self.assertEqual(max(_read_json(COLLECTIONS_URL, 1), key=lambda item: item["to"])["cdx-api"], "new-url")

    @patch("jobsh.discovery.fetch")
    def test_records_reads_requested_collections_once(self, fetch) -> None:
        fetch.side_effect = [
            b'[{"cdx-api":"new","to":"2026"},{"cdx-api":"old","to":"2025"}]',
            b'{"pages":1}', b'{"pages":1}',
            b'{"url":"https://same.example/new"}\n',
            b'{"url":"https://same.example/old"}\n',
            b'[{"cdx-api":"new","to":"2026"},{"cdx-api":"old","to":"2025"}]',
            b'{"pages":1}', b'{"pages":1}',
        ]
        state = {}
        self.assertEqual(
            [row["url"] for row in records("example.com", 1, state, 2)],
            ["https://same.example/new", "https://same.example/old"],
        )
        self.assertEqual(list(records("example.com", 1, state, 2)), [])

    @patch("jobsh.discovery.time.sleep")
    @patch("jobsh.discovery.fetch")
    def test_records_reads_all_snapshot_pages(self, fetch, sleep) -> None:
        fetch.side_effect = [
            b'[{"id":"snapshot","cdx-api":"index","to":"2026-01-01"}]',
            b'{"pages":2}',
            b'{"url":"https://one.example"}\n',
            b'{"url":"https://two.example"}\n',
        ]

        self.assertEqual(
            list(records("example.com", 1)),
            [
                {"url": "https://one.example"},
                {"url": "https://two.example"},
            ],
        )
        sleep.assert_called_once_with(1)
        for call in fetch.call_args_list[1:]:
            self.assertEqual(parse_qs(urlsplit(call.args[0]).query)["pageSize"], ["1"])

    @patch("jobsh.discovery.time.sleep")
    @patch("jobsh.discovery.fetch")
    def test_records_skip_empty_filtered_pages(self, fetch, sleep) -> None:
        fetch.side_effect = [
            b'[{"cdx-api":"index","to":"2026-01-01"}]', b'{"pages":3}',
            b'{"url":"https://one.example"}\n', HTTPStatusError(404, "not found"),
            b'{"url":"https://two.example"}\n',
        ]
        self.assertEqual(list(records("example.com", 1)), [
            {"url": "https://one.example"}, {"url": "https://two.example"},
        ])

    @patch("jobsh.discovery.time.sleep")
    @patch("jobsh.discovery.fetch")
    def test_bad_json_is_retried_without_yielding_partial_pages(self, fetch, sleep):
        fetch.side_effect = [
            b'{"bad"', b'[{"cdx-api":"index","to":"2026-01-01"}]',
            b'{"pages"', b'{"pages":1}',
            b'{"url":"https://one.example"}\n{"url"broken}\n',
            b'{"url":"https://one.example"}\n{"url":"https://two.example"}\n',
        ]
        self.assertEqual(list(records("example.com", 1)),
                         [{"url": "https://one.example"}, {"url": "https://two.example"}])
        self.assertEqual(sleep.call_count, 3)
        fetch.side_effect = None
        fetch.return_value = b'{"url"broken}'
        fetch.reset_mock()
        with self.assertRaisesRegex(ValueError, "invalid Common Crawl JSON from https://index.commoncrawl.org/collinfo.json"):
            _read_json(COLLECTIONS_URL, 1)
        self.assertEqual(fetch.call_count, 3)

    @patch("jobsh.discovery.time.sleep")
    @patch("jobsh.discovery.fetch")
    def test_transient_errors_retry_then_use_older_collection(self, fetch, sleep):
        fetch.side_effect = [
            b'[{"cdx-api":"new","to":"2026"},{"cdx-api":"old","to":"2025"}]',
            HTTPStatusError(504, "timeout"), OSError("connection closed"),
            HTTPStatusError(400, "bad request"), b'{"pages":1}',
            b'{"url":"https://one.example"}\n',
        ]
        state = {}
        self.assertEqual(list(records("example.com", 1, state)), [{"url": "https://one.example"}])
        self.assertEqual(state["endpoint"], "old")
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2])

    @patch("jobsh.discovery.time.sleep")
    @patch("jobsh.discovery.fetch")
    def test_records_fall_back_when_a_collection_page_stays_broken(self, fetch, sleep):
        fetch.side_effect = [
            b'[{"cdx-api":"new","to":"2026"},{"cdx-api":"old","to":"2025"}]',
            b'{"pages":1}', b'{"pages":1}',
            *[HTTPStatusError(502, "bad gateway")] * 3,
            b'{"url":"https://one.example"}\n',
        ]
        self.assertEqual(list(records("example.com", 1)), [{"url": "https://one.example"}])

    @patch("jobsh.discovery._verify_source", side_effect=OSError("skip"))
    @patch("jobsh.discovery.time.sleep")
    @patch("jobsh.discovery.fetch")
    def test_discovery_stops_after_enough_distinct_hosts(self, fetch, sleep, verify):
        fetch.side_effect = [
            b'[{"cdx-api":"index","to":"2026-01-01"}]',
            b'{"pages":100}',
            (b'{"url":"https://jobs.personio.de/"}\n'
             b'{"url":"https://nested.alpha.jobs.personio.de/"}\n'
             b'{"url":"https://zeta.jobs.personio.de/job/1"}\n'
             b'{"url":"https://zeta.jobs.personio.de/job/2"}\n'),
            (b'{"url":"https://beta.jobs.personio.de/job/1"}\n'
             b'{"url":"https://alpha.jobs.personio.de/job/1"}\n'),
        ]
        adapter = ADAPTERS["personio"]
        with patch.dict("jobsh.discovery.ADAPTERS", {
            "personio": Adapter((adapter.domains[0],), adapter.source, adapter.fetch_records),
        }):
            self.assertEqual(discover("personio", limit=2, workers=1, timeout=1), [])
        self.assertEqual(fetch.call_count, 4)  # Metadata + two pages, not all 100 pages.
        sleep.assert_called_once_with(1)
        self.assertEqual([call.args[0][0] for call in verify.call_args_list],
                         ["beta", "zeta"])

    @patch("jobsh.discovery.time.sleep")
    @patch("jobsh.discovery.fetch")
    def test_records_only_fetches_when_consumed(self, fetch, sleep):
        fetch.side_effect = [
            b'[{"cdx-api":"index","to":"2026-01-01"}]', b'{"pages":100}',
            b'{"url":"https://one.example"}\n',
        ]
        rows = records("example.com", 1)
        fetch.assert_not_called()
        self.assertEqual(next(rows), {"url": "https://one.example"})
        rows.close()
        self.assertEqual(fetch.call_count, 3)
        sleep.assert_not_called()
