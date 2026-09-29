"""Command line entry point: ``sqxf``."""
from __future__ import annotations

import argparse
from pathlib import Path

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


def cmd_funnel(args: argparse.Namespace) -> int:
    """Run the pre-registered discovery funnel described by a committed YAML config."""
    import json
    import subprocess

    import yaml

    from sqxf.backtest.evaluator import load_market
    from sqxf.funnel.pipeline import run_funnel
    from sqxf.provenance import PROJECT_ROOT

    cfg_path = Path(args.config).resolve()
    rel = cfg_path.relative_to(PROJECT_ROOT)
    dirty = subprocess.run(["git", "status", "--porcelain", "--", str(rel)], cwd=PROJECT_ROOT, capture_output=True,
                           text=True).stdout.strip()
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", str(rel)], cwd=PROJECT_ROOT, capture_output=True).returncode
    if dirty or tracked != 0:
        print(f"refusing to run: {rel} must be committed before any run (pre-registration)")
        return 2
    cfg = yaml.safe_load(cfg_path.read_text())
    market = load_market(cfg["pair"])
    out = PROJECT_ROOT / "runs" / cfg["run_name"]
    report = run_funnel(market, cfg, out_dir=out)
    print(json.dumps({"counts": report["counts"], "dsr_inputs": report["dsr_inputs"],
                      "too_good_flags": report["too_good_flags"], "report": str(out / "report.json")}, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sqxf", description="Forex strategy factory (M15 base data, H1 signals).")
    parser.add_argument("--version", action="version", version=f"sqxf {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="command")
    p = sub.add_parser("build-data", help="validate raw M15, cache canonical pre-holdout data, summarise H1")
    p.add_argument("pairs", nargs="*", help="pairs (default: configs/data.yaml)")
    p.add_argument("--rebuild", action="store_true", help="ignore the parquet cache")
    p.set_defaults(func=cmd_build_data)
    p = sub.add_parser("funnel", help="run the pre-registered discovery funnel (config must be committed)")
    p.add_argument("--config", default="configs/funnel.yaml")
    p.set_defaults(func=cmd_funnel)
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
