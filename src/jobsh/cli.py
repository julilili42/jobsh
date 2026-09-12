import argparse
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

from .adapters import ADAPTERS
from .db import connect, register_source
from .discovery import discover
from .search import get_job, search
from .sync import sync


def _discovery(args: argparse.Namespace) -> None:
    provider = args.provider
    domain = ADAPTERS[provider].domain
    with closing(connect(args.db)) as database:
        known_accounts = {
            row[0]
            for row in database.execute("SELECT provider_account FROM sources WHERE provider = ?", (provider,))
        }
        saved = database.execute(
            "SELECT state FROM discovery_state WHERE domain = ?", (domain,)
        ).fetchone()
        state = json.loads(saved[0]) if saved else {}
        feeds = discover(provider, args.limit, args.workers, args.timeout, known_accounts, state)
        with database:
            for account, url, observed_at in feeds:
                register_source(database, provider, account, url, "common-crawl", observed_at)
            database.execute(
                "INSERT OR REPLACE INTO discovery_state VALUES (?, ?)",
                (domain, json.dumps(state)),
            )
    print(f"registered {len(feeds)} feeds", file=sys.stderr)


def _sync(args: argparse.Namespace) -> None:
    with closing(connect(args.db)) as database:
        succeeded, failed = sync(database, args.timeout, args.workers)
    print(f"synced {succeeded} sources; {failed} failed", file=sys.stderr)
    if failed:
        raise OSError(f"{failed} source imports failed")


def _search(args: argparse.Namespace) -> None:
    with closing(connect(args.db)) as database:
        page = search(database, args.query, title=args.title, location=args.location,
                      work_mode=args.work_mode, limit=args.limit, cursor=args.cursor)
    if args.json:
        print(json.dumps(page, ensure_ascii=False))
        return
    for job in page["jobs"]:
        print(f"{job['id']}\t{job['title']}\t{job['location_text'] or 'unknown'}\t{job['work_mode']}")
        print(f"  {job['original_url']} | {job['provider_account']} | last seen: {job['last_seen_at']}")
    if page["next_cursor"] is not None:
        print(f"next page: --cursor {page['next_cursor']}", file=sys.stderr)


def _show(args: argparse.Namespace) -> None:
    with closing(connect(args.db)) as database:
        job = get_job(database, args.id)
    if args.json:
        print(json.dumps(job, ensure_ascii=False))
        return
    for key, value in job.items():
        print(f"{key}: {value if value is not None else 'unknown'}")


def _serve(args: argparse.Namespace) -> None:
    from .server import serve

    serve(args.db)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jobsh")
    parser.add_argument("--db", type=Path, default=Path("jobsh.db"))
    commands = parser.add_subparsers(dest="command", required=True)
    for name, run, help_text in (
        ("discovery", _discovery, "find and register public job feeds"),
        ("sync", _sync, "import all registered feeds"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.set_defaults(run=run)
        command.add_argument("--workers", type=int, default=32)
        command.add_argument("--timeout", type=float, default=15)
        if name == "discovery":
            command.add_argument("--provider", choices=ADAPTERS, default="personio")
            command.add_argument("--limit", type=int, default=0, help="maximum hosts to verify")

    command = commands.add_parser("search", help="search all open jobs")
    command.set_defaults(run=_search)
    command.add_argument("query", nargs="?", default="")
    command.add_argument("--title", default="")
    command.add_argument("--location", default="")
    mode = command.add_mutually_exclusive_group()
    mode.add_argument("--work-mode", choices=("remote", "hybrid", "onsite", "unknown"))
    mode.add_argument("--remote", dest="work_mode", action="store_const", const="remote")
    command.add_argument("--limit", type=int, default=20)
    command.add_argument("--cursor", type=int, default=0, help="continue after this job ID")
    command.add_argument("--json", action="store_true")

    command = commands.add_parser("show", help="show the full job, including closed jobs")
    command.set_defaults(run=_show)
    command.add_argument("id", type=int)
    command.add_argument("--json", action="store_true")
    command = commands.add_parser("serve", help="run the local MCP server over stdio")
    command.set_defaults(run=_serve)
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    try:
        args.run(args)
    except (OSError, ValueError, sqlite3.Error) as error:
        parser.exit(1, f"jobsh: {error}\n")
