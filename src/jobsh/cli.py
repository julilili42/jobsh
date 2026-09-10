import argparse
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

from .db import connect
from .discovery import discover
from .jobs import register_feed, sync
from .search import get_job, search


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jobsh")
    parser.add_argument("--db", type=Path, default=Path("jobsh.db"))
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser(
        "discovery", help="find and register public Personio feeds"
    )
    command.add_argument("--limit", type=int, default=0, help="maximum hosts to verify")
    command.add_argument("--workers", type=int, default=8)
    command.add_argument("--timeout", type=float, default=15)

    command = commands.add_parser("sync", help="import all registered feeds")
    command.add_argument("--timeout", type=float, default=15)

    command = commands.add_parser("search", help="search open, confirmed IT jobs")
    command.add_argument("query", nargs="?", default="")
    command.add_argument("--title", default="")
    command.add_argument("--location", default="")
    mode = command.add_mutually_exclusive_group()
    mode.add_argument("--work-mode", choices=("remote", "hybrid", "onsite", "unknown"))
    mode.add_argument("--remote", dest="work_mode", action="store_const", const="remote")
    command.add_argument("--limit", type=int, default=20)
    command.add_argument("--offset", type=int, default=0)
    command.add_argument("--json", action="store_true")

    command = commands.add_parser(
        "show", help="show a job, including unclassified or closed jobs"
    )
    command.add_argument("id", type=int)
    command.add_argument("--json", action="store_true")
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    try:
        if args.command == "discovery":
            feeds = discover(args.limit, args.workers, args.timeout)
            with closing(connect(args.db)) as database, database:
                for account, feed_url, observed_at in feeds:
                    register_feed(database, account, feed_url, "common-crawl", observed_at)
            print(f"registered {len(feeds)} feeds", file=sys.stderr)
        elif args.command == "sync":
            with closing(connect(args.db)) as database, database:
                succeeded, failed = sync(database, args.timeout)
            print(f"synced {succeeded} sources; {failed} failed", file=sys.stderr)
            if failed:
                raise OSError(f"{failed} source imports failed")
        elif args.command in ("search", "show"):
            with closing(connect(args.db)) as database:
                result = get_job(database, args.id) if args.command == "show" else search(
                    database, args.query, title=args.title, location=args.location,
                    work_mode=args.work_mode, limit=args.limit, offset=args.offset,
                )
            if args.json:
                print(json.dumps(result, ensure_ascii=False))
            elif args.command == "show":
                for key, value in result.items():
                    print(f"{key}: {value if value is not None else 'unknown'}")
            else:
                for job in result:
                    print(f"{job['id']}\t{job['title']}\t{job['location_text'] or 'unknown'}\t{job['work_mode']}")
                    print(f"  {job['original_url']} | {job['provider_account']} | last seen: {job['last_seen_at']}")
    except (OSError, ValueError, KeyError, sqlite3.Error) as error:
        parser.exit(1, f"jobsh: {error}\n")
