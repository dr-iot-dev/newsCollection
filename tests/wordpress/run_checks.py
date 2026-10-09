"""Validate plugin syntax and both route modes without a live WordPress site."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "wordpress/news-weave/news-weave.php"
HARNESS = ROOT / "tests/wordpress/test-news-weave.php"
MIGRATION = ROOT / "wordpress/news-weave/includes/route-migration.php"


def main() -> None:
    plugin = PLUGIN.read_text(encoding="utf-8")
    harness = HARNESS.read_text(encoding="utf-8")
    # Inline the exact plugin source so Docker does not need a UNC bind mount.
    combined = plugin.replace(
        "require_once __DIR__ . '/includes/route-migration.php';",
        MIGRATION.read_text(encoding="utf-8").removeprefix("<?php"),
    )
    source = harness.replace(
        "require '/project/wordpress/news-weave/news-weave.php';",
        combined.removeprefix("<?php"),
    )
    command = [
        "docker", "run", "--rm", "--pull=never", "-i", "--network", "none",
        "php:8.3-cli-alpine", "php",
    ]
    for php in (PLUGIN, MIGRATION):
        subprocess.run([*command, "-l"], input=php.read_bytes(), check=True)  # noqa: S603
    for mode in ("default", "legacy", "migrated"):
        subprocess.run([*command, "--", mode], input=source.encode(), check=True)  # noqa: S603
    transaction = (ROOT / "tests/wordpress/test-route-migration.php").read_text(encoding="utf-8")
    transaction = transaction.replace(
        "require '/project/wordpress/news-weave/includes/route-migration.php';",
        MIGRATION.read_text(encoding="utf-8").removeprefix("<?php"),
    )
    subprocess.run(command, input=transaction.encode(), check=True)  # noqa: S603


if __name__ == "__main__":
    main()
