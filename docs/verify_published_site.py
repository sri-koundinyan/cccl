#!/usr/bin/env python3
"""Check that a published documentation site contains what the manifest promises.

Used in two places:

* After a deploy, as a cheap assertion that the site is coherent.
* Before compacting the gh-pages history, where it is a safety interlock. That
  operation force-pushes an orphan commit, so a truncated or half-written tree
  would become the only thing left. Refusing to proceed on an incomplete site is
  the difference between a maintenance job and an outage.

Usage:
    verify_published_site.py --site-root PATH [--manifest PATH]
"""

import argparse
import json
import sys
from pathlib import Path

ROOT_FILES = (
    "index.html",
    "404.html",
    "nv-versions.json",
    "versions.json",
    ".nojekyll",
)


def check(site_root, manifest_path):
    """Return a list of problems; empty means the site is coherent."""
    problems = []
    site_root = Path(site_root)

    if not site_root.is_dir():
        return [f"site root does not exist: {site_root}"]

    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    for name in ROOT_FILES:
        if not (site_root / name).exists():
            problems.append(f"missing root file: {name}")

    expected = [entry["dir"] for entry in manifest["versions"]]
    for directory in expected:
        version_root = site_root / directory
        if not version_root.is_dir():
            problems.append(f"manifest lists '{directory}' but the directory is absent")
        elif not (version_root / "index.html").exists():
            problems.append(f"{directory}/ has no index.html")

    latest_stable = manifest.get("latest_stable")
    if latest_stable is not None:
        alias = site_root / "latest"
        if not alias.is_dir():
            problems.append("latest_stable is set but latest/ is absent")
        elif not (alias / "index.html").exists():
            problems.append("latest/ has no index.html")
        elif latest_stable not in (alias / "index.html").read_text(encoding="utf-8"):
            problems.append(f"latest/ does not point at '{latest_stable}'")

    # A published site that still contains build-time placeholders means the
    # templates were copied rather than rendered.
    for name in ("index.html", "404.html"):
        path = site_root / name
        if path.exists():
            text = path.read_text(encoding="utf-8")
            if "@DEFAULT_VERSION@" in text or "@SITE_BASE@" in text:
                problems.append(f"{name} still contains unrendered placeholders")

    # Anything that looks like a version directory but is not in the manifest is
    # invisible to readers: it is published but absent from the switcher.
    known = set(expected) | {"latest"}
    for child in sorted(site_root.iterdir()):
        if not child.is_dir() or child.name.startswith((".", "_")):
            continue
        if child.name not in known:
            problems.append(
                f"'{child.name}/' is published but not listed in the manifest"
            )

    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-root", required=True)
    parser.add_argument(
        "--manifest",
        default=str(Path(__file__).parent / "published_versions.json"),
    )
    args = parser.parse_args(argv)

    problems = check(args.site_root, args.manifest)
    if problems:
        print(f"Published site is not coherent ({len(problems)} problem(s)):")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print(f"Published site at {args.site_root} is coherent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
