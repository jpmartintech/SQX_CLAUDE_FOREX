"""Provenance helpers: project paths, config loading, file hashes, code version."""
from __future__ import annotations

import hashlib
import subprocess
from functools import lru_cache
from pathlib import Path

import yaml

from sqxf import __version__

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_config(name: str) -> dict:
    """Load ``configs/<name>.yaml`` from the project root."""
    path = PROJECT_ROOT / "configs" / f"{name}.yaml"
    with path.open() as fh:
        return yaml.safe_load(fh)


def file_sha256(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        while block := fh.read(chunk):
            digest.update(block)
    return digest.hexdigest()


@lru_cache(maxsize=1)
def code_version() -> str:
    """Package version plus git commit (with ``-dirty`` when the tree has local changes)."""
    try:
        commit = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], cwd=PROJECT_ROOT, capture_output=True,
                                text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=PROJECT_ROOT,
                               capture_output=True, text=True, check=True).stdout.strip()
        return f"{__version__}+{commit}{'-dirty' if dirty else ''}"
    except (OSError, subprocess.CalledProcessError):
        return f"{__version__}+unknown"
