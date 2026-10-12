"""Build self-contained stage wheels, including only reachable, storage-free code.

Run this before building a component. Each generated source tree is self-contained;
no editable install, parent directory import, or shared runtime service is used.
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULES = ("collect", "ground", "curate", "write", "verify", "illustrate", "assemble")
DEPENDENCIES = [
    "pydantic==2.13.5",
    "httpx==0.28.1",
    "beautifulsoup4==4.14.3",
    "soupsieve==2.10",
    "markdown-it-py==4.0.0",
    "Pillow==12.3.0",
    "PyYAML==6.0.2",
    "defusedxml==0.7.1",
    "structlog==25.4.0",
]


def legacy_dependencies(text: str) -> set[str]:
    found = set()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app."):
            found.add(node.module)
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names if alias.name.startswith("app."))
    return found


def build(module: str) -> None:
    namespace = "nw_" + module
    component = ROOT / "components" / module
    package = component / "src" / namespace
    package.mkdir(parents=True, exist_ok=True)
    sources = {}
    for name in ("__init__.py", "protocol.py", "common.py", "runtime.py", "prompts.py"):
        sources[name] = (ROOT / "nw_generation" / name).read_text(encoding="utf-8")
    sources["handlers/__init__.py"] = ""
    sources["handlers/" + module + ".py"] = (
        ROOT / "nw_generation/handlers" / (module + ".py")
    ).read_text(encoding="utf-8")
    required = set()
    for text in sources.values():
        required.update(legacy_dependencies(text))
    visited = set()
    while required:
        name = required.pop()
        if name in visited:
            continue
        if name.startswith(
            (
                "app.infrastructure",
                "app.orchestration",
                "app.api",
                "app.jobs",
                "app.core.config",
                "app.ai.runner",
            )
        ):
            raise ValueError("Forbidden runtime dependency: " + name)
        source = ROOT / (name.replace(".", "/") + ".py")
        text = source.read_text(encoding="utf-8")
        tree = ast.parse(text)
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
            elif isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
        if any(name.startswith(("sqlalchemy", "psycopg")) for name in imports):
            raise ValueError("Storage dependency in component: " + str(source))
        visited.add(name)
        required.update(legacy_dependencies(text) - visited)
        sources["_vendor/" + name.removeprefix("app.").replace(".", "/") + ".py"] = text
    wanted = {package / name for name in sources}
    for existing in package.rglob("*.py"):
        if existing.name not in {"__init__.py", "cli.py", "__main__.py"} and existing not in wanted:
            if not existing.resolve().is_relative_to((ROOT / "components").resolve()):
                raise ValueError("Generated path escaped components")
            existing.unlink()
    for relative, text in sources.items():
        target = package / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        text = text.replace("from app.", "from " + namespace + "._vendor.")
        text = text.replace("import app.", "import " + namespace + "._vendor.")
        target.write_text(text, encoding="utf-8", newline="\n")
        for parent in target.parents:
            if parent == package.parent:
                break
            initializer = parent / "__init__.py"
            if not initializer.exists():
                initializer.write_text("", encoding="utf-8")
    (package / "cli.py").write_text(
        f"from .runtime import main as stage_main\n\n\ndef main() -> int:\n"
        f'    return stage_main("{module}")\n',
        encoding="utf-8",
    )
    (package / "__main__.py").write_text("from .cli import main\n\nraise SystemExit(main())\n")
    quoted = ", ".join('"' + dependency + '"' for dependency in DEPENDENCIES)
    project = (
        '[build-system]\nrequires = ["hatchling==1.27.0"]\nbuild-backend = "hatchling.build"\n\n'
        f'[project]\nname = "news-weave-{module}"\nversion = "1.0.0"\n'
        'requires-python = ">=3.13,<3.15"\n'
        f'dependencies = [{quoted}]\n\n[project.scripts]\nnw-{module} = "{namespace}.cli:main"\n\n'
        f'[tool.hatch.build.targets.wheel]\npackages = ["src/{namespace}"]\n'
    )
    (component / "pyproject.toml").write_text(project, encoding="utf-8")
    (component / "README.md").write_text(
        f"# nw-{module}\n\nStandalone file-in/file-out stage. Build with pip wheel .\n"
        f"Run: nw-{module} run --request request.json --output <local-directory>.\n"
        "No NewsWeave database, other stage, or WordPress installation is required.\n",
        encoding="utf-8",
    )
    print(module + ": " + str(len(visited)) + " storage-free policy/contract files")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("module", choices=(*MODULES, "all"), default="all", nargs="?")
    args = parser.parse_args()
    for module in MODULES if args.module == "all" else (args.module,):
        build(module)


if __name__ == "__main__":
    main()
