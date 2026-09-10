import argparse
import json
import sqlite3
import sys
from contextlib import closing
from functools import partial
from pathlib import Path
from urllib.parse import urlsplit

from .db import connect
from .discovery import discover
from .search import get_job, search
from .sources import register_source, sync


def _discovery(provider: str, domain: str, args: argparse.Namespace) -> None:
    with closing(connect(args.db)) as database:
        known_hosts = {
            urlsplit(row[0]).hostname or ""
            for row in database.execute("SELECT url FROM sources WHERE provider = ?", (provider,))
        }
        feeds = discover(domain, args.limit, args.workers, args.timeout, known_hosts)
        with database:
            for account, url, observed_at in feeds:
                register_source(database, provider, account, url, "common-crawl", observed_at)
    print(f"registered {len(feeds)} feeds", file=sys.stderr)


def _sync(args: argparse.Namespace) -> None:
    with closing(connect(args.db)) as database, database:
        succeeded, failed = sync(database, args.timeout, args.workers)
    print(f"synced {succeeded} sources; {failed} failed", file=sys.stderr)
    if failed:
        raise OSError(f"{failed} source imports failed")


def _search(args: argparse.Namespace) -> None:
    with closing(connect(args.db)) as database:
        jobs = search(database, args.query, title=args.title, location=args.location,
                      work_mode=args.work_mode, limit=args.limit, offset=args.offset)
    if args.json:
        print(json.dumps(jobs, ensure_ascii=False))
        return
    for job in jobs:
        print(f"{job['id']}\t{job['title']}\t{job['location_text'] or 'unknown'}\t{job['work_mode']}")
        print(f"  {job['original_url']} | {job['provider_account']} | last seen: {job['last_seen_at']}")


def _show(args: argparse.Namespace) -> None:
    with closing(connect(args.db)) as database:
        job = get_job(database, args.id)
    if args.json:
        print(json.dumps(job, ensure_ascii=False))
        return
    for key, value in job.items():
        print(f"{key}: {value if value is not None else 'unknown'}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jobsh")
    parser.add_argument("--db", type=Path, default=Path("jobsh.db"))
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser(
        "discovery", help="find and register public Personio feeds"
    )
    command.set_defaults(run=partial(_discovery, "personio", "jobs.personio.de"))
    command.add_argument("--limit", type=int, default=0, help="maximum hosts to verify")
    command.add_argument("--workers", type=int, default=32)
    command.add_argument("--timeout", type=float, default=15)

    command = commands.add_parser("sync", help="import all registered feeds")
    command.set_defaults(run=_sync)
    command.add_argument("--workers", type=int, default=32)
    command.add_argument("--timeout", type=float, default=15)

    command = commands.add_parser("search", help="search open, confirmed IT jobs")
    command.set_defaults(run=_search)
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
    command.set_defaults(run=_show)
    command.add_argument("id", type=int)
    command.add_argument("--json", action="store_true")
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    try:
        args.run(args)
    except (OSError, ValueError, sqlite3.Error) as error:
        parser.exit(1, f"jobsh: {error}\n")
