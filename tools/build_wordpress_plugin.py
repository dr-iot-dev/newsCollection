"""Build a News Weave ZIP, optionally retaining the existing site's routes."""

import argparse
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
LEGACY_BOOTSTRAP = """// This deployment package retains the existing site's article identities.
// An explicit wp-config.php setting can override this packaged default.
if (!defined('NEWS_WEAVE_LEGACY_ROUTES')) {
    define('NEWS_WEAVE_LEGACY_ROUTES', true);
}

"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy", action="store_true", help="Keep nc_news / nc-news routes")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    plugin = (ROOT / "wordpress/news-weave/news-weave.php").read_text(encoding="utf-8")
    if args.legacy:
        marker = "function news_weave_register_news_type() {"
        if plugin.count(marker) != 1:
            raise ValueError("Cannot locate News Weave registration function")
        plugin = plugin.replace(marker, LEGACY_BOOTSTRAP + marker)
    filename = "news-weave-legacy.zip" if args.legacy else "news-weave.zip"
    destination = args.output or ROOT / ".local" / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(destination, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("news-weave/news-weave.php", plugin.encode("utf-8"))
        for extra in sorted((ROOT / "wordpress/news-weave").rglob("*.php")):
            if extra.name != "news-weave.php":
                relative = extra.relative_to(ROOT / "wordpress/news-weave").as_posix()
                archive.writestr("news-weave/" + relative, extra.read_bytes())
    print(destination)


if __name__ == "__main__":
    main()
