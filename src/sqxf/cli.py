"""Command line entry point: ``sqxf``."""
from __future__ import annotations

import argparse

from sqxf import __version__


def cmd_build_data(args: argparse.Namespace) -> int:
    """Validate and cache canonical pre-holdout M15 for each pair, and report the derived H1."""
    from sqxf.data.h1 import build_h1
    from sqxf.data.m15 import DataConfig, load_m15
    from sqxf.provenance import load_config

    cfg = DataConfig.load()
    pairs = args.pairs or load_config("data")["pairs"]
    print(f"{'pair':8} {'m15':>8} {'h1':>7} {'complete':>9} {'no_trade':>9}  first -> last (EET)  sha256")
    for pair in pairs:
        m15 = load_m15(pair, cfg, use_cache=not args.rebuild)
        h1 = build_h1(m15)
        print(f"{pair:8} {len(m15):8d} {len(h1):7d} {h1['complete'].mean():9.4%} {h1['no_trade'].mean():9.4%}  "
              f"{m15['ts_local'].iat[0]} -> {m15['ts_local'].iat[-1]}  {m15.attrs['source_sha256'][:12]}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sqxf", description="Forex strategy factory (M15 base data, H1 signals).")
    parser.add_argument("--version", action="version", version=f"sqxf {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="command")
    p = sub.add_parser("build-data", help="validate raw M15, cache canonical pre-holdout data, summarise H1")
    p.add_argument("pairs", nargs="*", help="pairs (default: configs/data.yaml)")
    p.add_argument("--rebuild", action="store_true", help="ignore the parquet cache")
    p.set_defaults(func=cmd_build_data)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
