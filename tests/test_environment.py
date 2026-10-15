"""The implementation must start from the current workspace boundary."""

import subprocess
import sys
from pathlib import Path


def test_current_environment_is_clean():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(  # noqa: S603 - fixed interpreter and workspace-owned check script
        [sys.executable, str(root / "maintenance/check_environment.py")],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
