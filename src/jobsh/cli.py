import argparse
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

from .db import connect
from .jobs import register_feed, sync
from .discovery import discover


def _run_discovery(
    database_path: Path, limit: int, workers: int, timeout: float
) -> None:
    feeds = discover(limit, workers, timeout)
    with closing(connect(database_path)) as database, database:
        for account, feed_url, observed_at in feeds:
            register_feed(
                database,
                account,
                feed_url,
                "common-crawl",
                observed_at,
            )
    print(f"registered {len(feeds)} feeds", file=sys.stderr)


def _run_sync(database_path: Path, timeout: float) -> None:
    with closing(connect(database_path)) as database, database:
        succeeded, failed = sync(database, timeout)
    print(f"synced {succeeded} sources; {failed} failed", file=sys.stderr)
    if failed:
        raise OSError(f"{failed} source imports failed")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jobsh")
    parser.add_argument("--db", type=Path, default=Path("jobsh.db"))
    commands = parser.add_subparsers(dest="command", required=True)
    discovery = commands.add_parser(
        "discovery", help="find and register public Personio feeds"
    )
    discovery.add_argument("--limit", type=int, default=0, help="maximum hosts to verify")
    discovery.add_argument("--workers", type=int, default=8)
    discovery.add_argument("--timeout", type=float, default=15)
    synchronize = commands.add_parser("sync", help="import all registered feeds")
    synchronize.add_argument("--timeout", type=float, default=15)
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    try:
        if args.command == "discovery":
            _run_discovery(args.db, args.limit, args.workers, args.timeout)
        elif args.command == "sync":
            _run_sync(args.db, args.timeout)
    except (OSError, ValueError, KeyError, sqlite3.Error) as error:
        parser.exit(1, f"jobsh: {error}\n")
