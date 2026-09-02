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
import re
import sys
from pathlib import Path

# Kept in step with render_versions.VERSION_DIR.
VERSION_DIR = re.compile(r"^(?:unstable|[0-9]+\.[0-9]+)$")

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

    # The switcher is built by discovery, so "listed but missing" cannot happen.
    # What can happen is a directory that looks like a version but has no
    # landing page: it is silently omitted from the switcher, which reads as the
    # version having vanished.
    published = []
    for child in sorted(site_root.iterdir()):
        if not child.is_dir() or not VERSION_DIR.match(child.name):
            continue
        if (child / "index.html").exists():
            published.append(child.name)
        else:
            problems.append(
                f"{child.name}/ exists but has no index.html, so it is invisible "
                f"in the version switcher"
            )

    if not published:
        problems.append("no version directories are published")

    latest_stable = manifest.get("latest_stable")
    if latest_stable is not None and latest_stable not in published:
        problems.append(
            f"latest_stable is '{latest_stable}' but that version is not published"
        )

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

    # The switcher is rendered into the site root; it should agree with what is
    # on disk. A mismatch means the root assets are stale relative to the
    # directories, e.g. a version was published without the root being rebuilt.
    switcher_path = site_root / "nv-versions.json"
    if switcher_path.exists():
        try:
            switcher = json.loads(switcher_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            problems.append(f"nv-versions.json is not valid JSON: {exc}")
        else:
            listed = {e["version"] for e in switcher} - {"latest"}
            for missing in sorted(set(published) - listed):
                problems.append(
                    f"'{missing}/' is published but missing from the switcher; "
                    f"redeploy to refresh the site root"
                )
            for extra in sorted(listed - set(published)):
                problems.append(
                    f"the switcher offers '{extra}' but no such directory exists"
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
