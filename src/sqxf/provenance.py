"""Provenance helpers: project paths, config loading, file hashes, code version."""
from __future__ import annotations

import hashlib
import subprocess
from functools import lru_cache
from pathlib import Path

import yaml

from sqxf import __version__

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ConfigKeyError(ValueError):
    """A YAML mapping key did not survive loading as the string written in the file (e.g. ``null:``, ``yes:``, ``1:``)."""


def _check_keys(node: yaml.Node, value, where: str) -> None:
    if isinstance(node, yaml.MappingNode):
        for k_node, v_node in node.value:
            raw = k_node.value
            if raw not in value if isinstance(value, dict) else True:
                raise ConfigKeyError(f"{where}: key {raw!r} was not loaded as the string {raw!r}")
            _check_keys(v_node, value[raw], f"{where}.{raw}")
        if isinstance(value, dict) and any(not isinstance(k, str) for k in value):
            raise ConfigKeyError(f"{where}: non-string keys {[k for k in value if not isinstance(k, str)]}")
    elif isinstance(node, yaml.SequenceNode):
        for i, (n, v) in enumerate(zip(node.value, value, strict=True)):
            _check_keys(n, v, f"{where}[{i}]")


def load_yaml_strict(path: Path) -> dict:
    """``yaml.safe_load`` plus a check that every mapping key is loaded exactly as written (pre-registration safety)."""
    text = Path(path).read_text()
    value = yaml.safe_load(text)
    _check_keys(yaml.compose(text), value, Path(path).name)
    return value


def load_config(name: str) -> dict:
    """Load ``configs/<name>.yaml`` from the project root (strict keys)."""
    return load_yaml_strict(PROJECT_ROOT / "configs" / f"{name}.yaml")


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


def require_committed(path: Path) -> None:
    """Pre-registration guard: ``path`` must be tracked by git and have no uncommitted changes."""
    rel = Path(path).resolve().relative_to(PROJECT_ROOT)
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", str(rel)], cwd=PROJECT_ROOT,
                             capture_output=True).returncode == 0
    dirty = subprocess.run(["git", "status", "--porcelain", "--", str(rel)], cwd=PROJECT_ROOT, capture_output=True,
                           text=True).stdout.strip()
    if not tracked or dirty:
        raise RuntimeError(f"{rel} must be committed before any run (pre-registration)")
