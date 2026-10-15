"""Check the working tree boundary before implementing the current design."""

import json
from pathlib import Path


def check(root: Path) -> list[str]:
    manifest = root / "maintenance/retired-paths.json"
    retired = json.loads(manifest.read_text(encoding="utf-8"))
    errors = ["Retired file remains: " + name for name in retired if (root / name).is_file()]
    active_design = "docs/seven-stage-system-design-20261015.md"
    if not (root / active_design).is_file():
        errors.append("Current system design is missing")
    allowed = {active_design}
    for path in (root / "docs").rglob("*"):
        if path.is_file() and path.relative_to(root).as_posix() not in allowed:
            errors.append("Non-current document in docs: " + path.relative_to(root).as_posix())
    return errors


if __name__ == "__main__":
    problems = check(Path(__file__).resolve().parents[1])
    if problems:
        print("\n".join(problems))
        raise SystemExit(1)
    print("Implementation environment is clean; current specification only")
