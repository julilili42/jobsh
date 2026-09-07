import argparse

from .personio import discover


def main() -> None:
    parser = argparse.ArgumentParser(prog="jobsh")
    commands = parser.add_subparsers(dest="command")
    personio = commands.add_parser(
        "discover-personio", help="find and verify public Personio feeds"
    )
    personio.add_argument("--limit", type=int, default=0, help="maximum hosts to verify")
    personio.add_argument("--workers", type=int, default=8)
    personio.add_argument("--timeout", type=float, default=15)
    args = parser.parse_args()

    if args.command == "discover-personio":
        try:
            discover(args.limit, args.workers, args.timeout)
        except (OSError, ValueError) as error:
            parser.exit(1, f"jobsh: {error}\n")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
