import ast
from pathlib import Path

MODULES = {
    "acquisition",
    "extraction",
    "deduplication",
    "selection",
    "comparison",
    "writing",
    "verification",
    "review",
    "publication",
}


def test_modules_do_not_import_other_module_internals() -> None:
    root = Path("app/modules")
    violations: list[str] = []
    if not root.exists():
        return
    for source in root.rglob("*.py"):
        owner = source.relative_to(root).parts[0]
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                parts = name.split(".")
                if len(parts) >= 3 and parts[:2] == ["app", "modules"]:
                    target = parts[2]
                    if target in MODULES and target != owner:
                        violations.append(f"{source}: imports {name}")
    assert not violations, "\n".join(violations)
