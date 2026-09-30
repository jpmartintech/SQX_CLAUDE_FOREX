"""Pre-registration safety: strict YAML keys and no test writes to the versioned trial ledger."""
from pathlib import Path

import pytest

import sqxf.trials as trials
from sqxf.provenance import PROJECT_ROOT, ConfigKeyError, load_yaml_strict


@pytest.mark.parametrize("bad", ["null:\n  a: 1\n", "yes: 1\n", "on: 2\n", "1: x\n", "a:\n  off: 3\n", "a:\n  - {null: 1}\n"])
def test_strict_loader_fails_when_a_key_is_lost(tmp_path, bad):
    p = tmp_path / "c.yaml"
    p.write_text(bad)
    with pytest.raises(ConfigKeyError):
        load_yaml_strict(p)


def test_strict_loader_accepts_quoted_keys(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text('"null":\n  n: 1\nsub:\n  - {"yes": 2}\n')
    assert load_yaml_strict(p) == {"null": {"n": 1}, "sub": [{"yes": 2}]}


@pytest.mark.parametrize("path", sorted((PROJECT_ROOT / "configs").glob("*.yaml")), ids=lambda p: p.name)
def test_every_committed_config_keeps_all_keys(path: Path):
    load_yaml_strict(path)


def test_tests_do_not_write_the_versioned_ledger():
    project_ledger = PROJECT_ROOT / "trials" / "ledger.jsonl"
    before = project_ledger.read_bytes() if project_ledger.exists() else b""
    trials.record_evaluations("unit test", "EURUSD", 7, selection=False)
    assert trials.LEDGER != project_ledger and trials.total_evaluations() == 7
    assert (project_ledger.read_bytes() if project_ledger.exists() else b"") == before
    trials.LEDGER = project_ledger  # guard: a direct write to the real ledger under pytest must fail
    try:
        with pytest.raises(RuntimeError):
            trials.record_evaluations("unit test", "EURUSD", 1, selection=False)
    finally:
        trials.LEDGER = PROJECT_ROOT / "tmp_never_used.jsonl"
