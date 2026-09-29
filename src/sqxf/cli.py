"""Command line entry point: ``sqxf``."""
from __future__ import annotations

import argparse

from sqxf import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sqxf", description="Forex strategy factory (M15 base data, H1 signals).")
    parser.add_argument("--version", action="version", version=f"sqxf {__version__}")
    parser.add_subparsers(dest="command", metavar="command")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
