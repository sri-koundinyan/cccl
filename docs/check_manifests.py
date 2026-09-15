#!/usr/bin/env python3
"""Check a component's two version manifests before its documentation ships.

Both files travel with the release, as they do in cuda-python:

    nv-versions.json   authoritative, read by the theme to draw the switcher
    versions.json      cuda-python-style compatibility manifest

Two things can go wrong silently, so both are checked here rather than left to
a reviewer noticing:

*   The version being published is absent from ``nv-versions.json``. The
    documentation deploys and renders, but no switcher entry points at it, so
    a reader has no way to reach it.

*   The two manifests disagree. Nothing reads ``versions.json`` today, so the
    disagreement is invisible until something does. cuda-python's live site
    shows this happening: at the revision this design was taken from,
    ``cuda_core/versions.json`` stops at ``0.3.2`` while its
    ``nv-versions.json`` reaches ``1.2.0``.

This is not a publication system. It reads two files and compares two sets.
"""

import argparse
import json
import pathlib
import sys


def versions_of(component_root):
    """Return (nv_versions, compat_versions) as ordered lists."""
    root = pathlib.Path(component_root)
    nv = json.loads((root / "nv-versions.json").read_text(encoding="utf-8"))
    compat = json.loads((root / "versions.json").read_text(encoding="utf-8"))
    return [entry["version"] for entry in nv], list(compat)


def check(component_root, version):
    """Raise SystemExit with a specific message, or return the version list."""
    nv, compat = versions_of(component_root)

    if version not in nv:
        raise SystemExit(
            f"error: nv-versions.json does not list {version!r}.\n"
            f"       It lists: {', '.join(nv) or '(nothing)'}\n"
            "       Add the version during release preparation, before tagging.\n"
            "       Without an entry the docs deploy but nothing links to them."
        )

    if set(nv) != set(compat):
        only_nv = sorted(set(nv) - set(compat))
        only_compat = sorted(set(compat) - set(nv))
        detail = []
        if only_nv:
            detail.append(f"       only in nv-versions.json: {', '.join(only_nv)}")
        if only_compat:
            detail.append(f"       only in versions.json:    {', '.join(only_compat)}")
        raise SystemExit(
            "error: the two manifests disagree.\n"
            + "\n".join(detail)
            + "\n       Both travel with the release; update them together."
        )

    return nv


def retarget(component_root, component, site_root):
    """Point the manifest's URLs at the host actually serving this build.

    The switcher entries are absolute URLs and the browser follows them, so a
    rehearsal published to a fork would otherwise offer a dropdown whose every
    option navigates to production.
    """
    root = pathlib.Path(component_root)
    path = root / "nv-versions.json"
    entries = json.loads(path.read_text(encoding="utf-8"))
    for entry in entries:
        entry["url"] = f"{site_root.rstrip('/')}/{component}/{entry['version']}/"
    path.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
    return entries


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("component_root", help="directory holding both manifests")
    parser.add_argument("version", help="the version being published")
    parser.add_argument("--component", help="cpp or python, for --site-url")
    parser.add_argument("--site-url", help="retarget manifest URLs to this site root")
    args = parser.parse_args(argv)

    if args.site_url:
        if not args.component:
            raise SystemExit("error: --site-url requires --component")
        retarget(args.component_root, args.component, args.site_url)
        print(f"  manifest URLs retargeted to {args.site_url.rstrip('/')}/{args.component}/")

    listed = check(args.component_root, args.version)
    print(f"  manifests agree, and list {args.version}: {', '.join(listed)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
