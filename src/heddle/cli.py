"""CLI: heddle init · heddle index · heddle serve · heddle status · heddle verify."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .errors import HeddleError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="heddle", description="Content-addressed contracts + cached verification over MCP.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="create .heddle/ and contracts/ in the current directory")
    sub.add_parser("index", help="rebuild the store from contracts/")
    serve_parser = sub.add_parser("serve", help="run the MCP server on stdio")
    serve_parser.add_argument(
        "--python",
        metavar="PATH",
        help="interpreter to run pytest with (default: project .venv, else this interpreter)",
    )
    sub.add_parser("status", help="dirty contracts, stale verifications, cache hit-rate, token counters")
    verify_parser = sub.add_parser("verify", help="run cached verification for one or more contracts")
    verify_parser.add_argument("names", nargs="+", metavar="NAME", help="contract names to verify")
    verify_parser.add_argument(
        "--python",
        metavar="PATH",
        help="interpreter to run pytest with (default: project .venv, else this interpreter)",
    )
    args = parser.parse_args(argv)

    try:
        if args.command == "init":
            from .project import init_project

            created = init_project(Path.cwd())
            print("\n".join(f"created {p}" for p in created) if created else "already initialised")
            return 0

        from .project import db_path, find_root

        root = Path.cwd() if args.command == "init" else find_root()

        if args.command == "serve":
            from .server import serve

            serve(root, python=args.python)
            return 0

        from .store import Store

        store = Store(db_path(root))
        if args.command == "index":
            from .indexer import index

            print(json.dumps(index(root, store), indent=2))
        elif args.command == "status":
            from . import api

            print(json.dumps(api.status(root, store), indent=2))
        elif args.command == "verify":
            from . import api

            result = api.verify(root, store, args.names, python=args.python)
            print(json.dumps(result, indent=2))
            # nonzero if any unit failed or errored — usable as a CI/pre-commit gate
            if any(r["status"] in ("fail", "error") for r in result["results"]):
                return 1
        return 0
    except HeddleError as e:
        print(json.dumps(e.to_dict(), indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
