import subprocess
import sys

from sqxf.cli import main


def test_main_without_command_prints_help(capsys):
    assert main([]) == 0
    assert "sqxf" in capsys.readouterr().out


def test_help_via_module():
    out = subprocess.run([sys.executable, "-m", "sqxf.cli", "--help"], capture_output=True, text=True, check=True)
    assert "usage: sqxf" in out.stdout


def test_build_data_command_on_real_data(capsys):
    from conftest import raw_available
    if not raw_available():
        import pytest
        pytest.skip("data/raw not present")
    assert main(["build-data", "EURUSD"]) == 0
    assert "EURUSD" in capsys.readouterr().out
