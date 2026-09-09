import unittest
from pathlib import Path

from jobsh.cli import _build_parser


class CliTest(unittest.TestCase):
    def test_parser_reads_discovery_and_sync_options(self) -> None:
        discovery = _build_parser().parse_args(
            [
                "--db",
                "custom.db",
                "discovery",
                "--limit",
                "5",
                "--workers",
                "2",
                "--timeout",
                "3",
            ]
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
