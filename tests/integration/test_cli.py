import os
import sys
from pathlib import Path

import pytest

from mas_recovery import cli


@pytest.mark.parametrize("existing,expected", [(None, "local-value"), ("exported", "exported")])
def test_cli_loads_local_env_without_overriding_shell(monkeypatch, tmp_path, existing, expected):
    config = Path(__file__).resolve().parents[2] / "configs" / "clean.toml"
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MAS_RECOVERY_TEST_ENV", raising=False)
    monkeypatch.delenv("PYTHON_DOTENV_DISABLED", raising=False)
    if existing is not None:
        monkeypatch.setenv("MAS_RECOVERY_TEST_ENV", existing)
    (tmp_path / ".env").write_text("MAS_RECOVERY_TEST_ENV=local-value\n")
    monkeypatch.setattr(sys, "argv", ["mas-recovery", "run", "--config", str(config)])

    def run(config, task, backend, output, **kwargs):
        assert os.environ["MAS_RECOVERY_TEST_ENV"] == expected
        return tmp_path

    monkeypatch.setattr(cli, "run_experiment", run)
    cli.main()
