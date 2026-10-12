import subprocess
import sys
from uuid import uuid4

from typer.testing import CliRunner

from app.cli import app
from app.core.config import Settings


def test_shadow_command_is_registered_by_import_and_module_entrypoint():
    result = CliRunner().invoke(app, ["comparison", "shadow", "--help"])
    assert result.exit_code == 0 and "--candidate" in result.stdout
    module = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "app.cli", "comparison", "shadow", "--help"],
        capture_output=True, text=True, check=False,
    )
    assert module.returncode == 0 and "--exclusion-baseline" in module.stdout


def test_unconfigured_models_defer_without_creating_a_report_or_sending(monkeypatch, tmp_path):
    monkeypatch.setattr("app.cli.get_settings", lambda: Settings(_env_file=None))
    output = tmp_path / "audit.json"
    result = CliRunner().invoke(app, ["comparison", "shadow", "--item", str(uuid4()),
                                      "--candidate", str(uuid4()), "--output", str(output)])
    assert result.exit_code == 2
    assert "COMPARISON_MODELS_NOT_CONFIGURED" in result.output
    assert not output.exists()
