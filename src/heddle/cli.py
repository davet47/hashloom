"""CLI: heddle init · heddle index · heddle serve · heddle status · heddle verify."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .errors import HeddleError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="heddle", description="Content-addressed contracts + cached verification over MCP.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="create .heddle/ and contracts/ in the current directory")
    sub.add_parser("index", help="rebuild the store from contracts/")
    serve_parser = sub.add_parser("serve", help="run the MCP server on stdio")
    serve_parser.add_argument(
        "--python",
        metavar="PATH",
        help="interpreter to run pytest with (default: project .venv, else this interpreter)",
    )
    serve_parser.add_argument(
        "--no-pycache-trust",
        action="store_true",
        help="clear project __pycache__ before each verify run (don't trust stale bytecode)",
    )
    sub.add_parser("status", help="dirty contracts, stale verifications, cache hit-rate, token counters")
    verify_parser = sub.add_parser("verify", help="run cached verification for one or more contracts")
    verify_parser.add_argument("names", nargs="+", metavar="NAME", help="contract names to verify")
    verify_parser.add_argument(
        "--radius",
        action="store_true",
        help="also verify every transitive dependent of each NAME (the blast radius)",
    )
    verify_parser.add_argument(
        "--python",
        metavar="PATH",
        help="interpreter to run pytest with (default: project .venv, else this interpreter)",
    )
    verify_parser.add_argument(
        "--no-pycache-trust",
        action="store_true",
        help="clear project __pycache__ before running (don't trust stale bytecode)",
    )
    args = parser.parse_args(argv)

    try:
        if args.command == "init":
            from .project import init_project

            created = init_project(Path.cwd())
            print("\n".join(f"created {p}" for p in created) if created else "already initialised")
            return 0

        from .project import find_root

        root = Path.cwd() if args.command == "init" else find_root()

        if args.command == "serve":
            from .server import serve

            serve(root, python=args.python, pycache_trust=False if args.no_pycache_trust else None)
            return 0

        from .remote import build_store

        store = build_store(root)  # local, or LayeredStore over a shared cache if configured
        if args.command == "index":
            from .indexer import index

            print(json.dumps(index(root, store), indent=2))
        elif args.command == "status":
            from . import api

            print(json.dumps(api.status(root, store), indent=2))
        elif args.command == "verify":
            from . import api
            from .config import resolve_pycache_trust

            trust = resolve_pycache_trust(root, override=False if args.no_pycache_trust else None)
            result = api.verify(root, store, args.names, python=args.python, pycache_trust=trust, radius=args.radius)
            print(json.dumps(result, indent=2))
            # the CI/pre-commit gate: exit mirrors the response's `ok` bit
            if not result["ok"]:
                return 1
        return 0
    except HeddleError as e:
        print(json.dumps(e.to_dict(), indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
