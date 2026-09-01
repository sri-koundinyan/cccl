#!/usr/bin/env python3
"""Report documentation URLs that a change would remove.

Compares the page list produced by ``scrape_docs.bash`` for the current build
against the page list of the currently published documentation. Any path present
in the published docs but missing from this build is a URL that would stop
resolving: a bookmark, a search result, or a link in a Slack thread that breaks.

This is advisory rather than blocking. Restructuring documentation removes paths
on purpose, and the site's 404 handler fuzzy-matches misses against the page
list, so a removal degrades rather than dead-ends. What matters is that the
number is visible in review instead of being discovered by users afterwards.

Usage:
    check_removed_pages.py --current PATH --baseline PATH_OR_URL [--summary PATH]

Exits non-zero only on a usage or parsing error, never because pages were
removed. Pass --strict to fail when any page disappears.
"""

import argparse
import sys
import urllib.error
import urllib.request
from pathlib import Path

# Pages that exist to support the site rather than to be linked at.
IGNORED = frozenset({"/404_helper.html", "/genindex.html", "/search.html"})


def parse_pagelist(text):
    """Parse scrape_docs.bash output: comma-separated paths on a single line."""
    paths = set()
    for raw in text.split(","):
        path = raw.strip()
        if not path:
            continue
        # find(1) emits "./index.html" as "/index.html"; normalize "/./" noise.
        if path.startswith("/./"):
            path = path[2:]
        if path not in IGNORED:
            paths.add(path)
    return paths


def read_source(location):
    """Read a page list from a local path or an http(s) URL."""
    if location.startswith(("http://", "https://")):
        with urllib.request.urlopen(location, timeout=30) as response:
            return response.read().decode("utf-8")
    return Path(location).read_text(encoding="utf-8")


def render_report(removed, added, baseline, limit=50):
    lines = []
    if removed:
        lines.append(f"### {len(removed)} documentation URL(s) would stop resolving")
        lines.append("")
        lines.append(f"Compared against `{baseline}`.")
        lines.append("")
        for path in sorted(removed)[:limit]:
            lines.append(f"- `{path}`")
        if len(removed) > limit:
            lines.append(f"- ...and {len(removed) - limit} more")
        lines.append("")
        lines.append(
            "These are reachable today. Readers who follow an existing link will "
            "land on the 404 handler, which offers the closest matching pages. If "
            "a removal is intentional, no action is needed beyond knowing the count."
        )
    else:
        lines.append("### No documentation URLs are removed by this change")
        lines.append("")
        lines.append(f"Compared against `{baseline}`.")

    if added:
        lines.append("")
        lines.append(f"{len(added)} new page(s) added.")

    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", required=True, help="this build's pagelist.txt")
    parser.add_argument(
        "--baseline", required=True, help="published pagelist.txt (path or URL)"
    )
    parser.add_argument("--summary", help="write the report here as well as stdout")
    parser.add_argument(
        "--strict", action="store_true", help="exit non-zero if pages were removed"
    )
    args = parser.parse_args(argv)

    current = parse_pagelist(Path(args.current).read_text(encoding="utf-8"))
    if not current:
        print(f"error: {args.current} listed no pages", file=sys.stderr)
        return 2

    try:
        baseline = parse_pagelist(read_source(args.baseline))
    except (OSError, urllib.error.URLError) as exc:
        # No published docs yet, or the site is unreachable. That is not a
        # reason to fail a pull request.
        print(f"Skipping removed-page check: could not read baseline ({exc})")
        return 0

    if not baseline:
        print("Skipping removed-page check: baseline listed no pages")
        return 0

    report = render_report(baseline - current, current - baseline, args.baseline)
    print(report)
    if args.summary:
        Path(args.summary).write_text(report, encoding="utf-8")

    if args.strict and (baseline - current):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
