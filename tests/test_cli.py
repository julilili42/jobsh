import unittest
import io
import sqlite3
import tempfile
from contextlib import closing, redirect_stderr
from pathlib import Path
from unittest.mock import patch

from jobsh.cli import _build_parser, main
from jobsh.db import connect
from jobsh.jobs import register_feed

FEED = (Path(__file__).parents[1] / "testdata/personio.xml").read_bytes()


class CliTest(unittest.TestCase):
    @patch("jobsh.personio_feed.fetch", side_effect=[OSError("offline"), FEED])
    def test_partial_sync_exits_with_error_and_commits_success(self, fetch):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "jobs.db"
            database = connect(path)
            with database:
                for account in ("broken", "working"):
                    register_feed(database, account, f"https://{account}.jobs.personio.de/xml", "manual")
            database.close()
            stderr = io.StringIO()
            with patch("sys.argv", ["jobsh", "--db", str(path), "sync"]), redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as error:
                    main()
            self.assertEqual(error.exception.code, 1)
            self.assertIn("1 source imports failed", stderr.getvalue())
            with closing(sqlite3.connect(path)) as database:
                self.assertEqual(database.execute(
                    "SELECT sources.provider_account FROM jobs JOIN sources ON jobs.source_id = sources.id"
                ).fetchall(), [("working",)])
                self.assertEqual(database.execute(
                    "SELECT status FROM sync_runs ORDER BY id"
                ).fetchall(), [("failed",), ("succeeded",)])

    @patch("jobsh.discovery.fetch")
    @patch("jobsh.discovery.records")
    def test_discovery_registers_only_valid_feeds_and_respects_limit(self, records, fetch):
        accounts = ("alpha", "alpha", "broken", "empty", "zeta")
        records.return_value = [{"url": f"https://{account}.jobs.personio.de/job/1"} for account in accounts]
        responses = {f"https://{account}.jobs.personio.de/xml?language=de": data for account, data in (
            ("alpha", FEED), ("broken", b"<broken"), ("empty", b"<workzag-jobs/>"), ("zeta", FEED),
        )}
        fetch.side_effect = lambda url, timeout: responses[url]
        with tempfile.TemporaryDirectory() as directory:
            for limit, expected, calls in ((0, ["alpha", "empty", "zeta"], 4), (3, ["alpha", "empty"], 3)):
                with self.subTest(limit=limit):
                    fetch.reset_mock()
                    path = Path(directory) / f"{limit}.db"
                    args = ["jobsh", "--db", str(path), "discovery", "--limit", str(limit), "--workers", "2"]
                    with patch("sys.argv", args), redirect_stderr(io.StringIO()):
                        main()
                    with closing(sqlite3.connect(path)) as database:
                        self.assertEqual(database.execute(
                            "SELECT provider_account FROM sources ORDER BY provider_account"
                        ).fetchall(), [(account,) for account in expected])
                    self.assertEqual(fetch.call_count, calls)

    def test_parser_reads_discovery_and_sync_options(self) -> None:
        discovery = _build_parser().parse_args(
            ["--db", "custom.db", "discovery", "--limit", "5", "--workers", "2", "--timeout", "3"]
        )
        self.assertEqual(discovery.command, "discovery")
        self.assertEqual(discovery.db, Path("custom.db"))
        self.assertEqual((discovery.limit, discovery.workers, discovery.timeout), (5, 2, 3))

        sync = _build_parser().parse_args(["sync", "--timeout", "4"])
        self.assertEqual(sync.command, "sync")
        self.assertEqual(sync.db, Path("jobsh.db"))
        self.assertEqual(sync.timeout, 4)


if __name__ == "__main__":
    unittest.main()
