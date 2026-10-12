"""Build each wheel and execute it with parent/sibling imports blocked."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

MODULES = ("collect", "ground", "curate", "write", "verify", "illustrate", "assemble")
ROOT = Path(__file__).resolve().parents[1]
PROBE = r"""
import importlib.abc, importlib, json, pathlib, sys
wheel, module, directory = sys.argv[1:]
sys.path.insert(0, wheel)
namespace = "nw_" + module
class Boundary(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "app" or fullname.startswith(("app.", "sqlalchemy", "psycopg")):
            raise ImportError("forbidden parent/storage import: " + fullname)
        if fullname.startswith("nw_") and fullname.split(".")[0] != namespace:
            raise ImportError("forbidden sibling import: " + fullname)
sys.meta_path.insert(0, Boundary())
runtime = importlib.import_module(namespace + ".runtime")
importlib.import_module(namespace + ".handlers." + module)
protocol = importlib.import_module(namespace + ".protocol")
request = pathlib.Path(directory) / "request.json"
request.write_bytes(protocol.canonical({"schema_version": "1.0", "module": module, "inputs": {}}))
result = runtime.execute(module, request, pathlib.Path(directory) / "output")
assert result["outcome"] == "error" and not result["outputs"], result
assert result["issues"][0]["code"].startswith("INPUT_REQUIRED_"), result
assert not any(name == "app" or name.startswith("app.") for name in sys.modules)
# Illustration can complete independently with a supplied draft and skip policy.
if module == "illustrate":
    file = pathlib.Path(directory) / "draft.nwstage"
    value = protocol.write_stage(file, "ArticleDraftV1", {"draft": {"title": "Example"}})
    request.write_bytes(protocol.canonical({"schema_version": "1.0", "module": module,
        "inputs": {"draft": {"file": file.name, "sha256": value}},
        "parameters": {"enabled": False}}))
    result = runtime.execute(module, request, pathlib.Path(directory) / "output")
    assert result["outcome"] == "success", result
print(module + ": isolated wheel import/execution OK")
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel-dir", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="nw-wheel-check-") as temporary:
        base = Path(temporary)
        wheels = args.wheel_dir or base / "wheels"
        wheels.mkdir(parents=True, exist_ok=True)
        for module in MODULES:
            subprocess.run(  # noqa: S603 - interpreter and module names are fixed
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "wheel",
                    "--no-deps",
                    "--no-build-isolation",
                    "--wheel-dir",
                    str(wheels),
                    str(ROOT / "components" / module),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
            )
            wheel = next(wheels.glob("news_weave_" + module + "-*.whl"))
            directory = base / module
            directory.mkdir()
            subprocess.run(  # noqa: S603 - interpreter and module names are fixed
                [sys.executable, "-I", "-c", PROBE, str(wheel.resolve()), module, str(directory)],
                cwd=directory,
                check=True,
            )


if __name__ == "__main__":
    main()
