#!/usr/bin/env python3
"""Check a component's version manifest before its documentation ships.

    nv-versions.json   the version list, fetched by the theme to draw the switcher

One thing can go wrong silently, so it is checked here rather than left to a
reviewer noticing: the version being published is absent from the manifest. The
documentation deploys and renders, but no switcher entry points at it, so a
reader has no way to reach it.

cuda-python also ships a second, differently-shaped ``versions.json`` beside
this one. CCCL does not, because nothing reads it -- and an unread file drifts:
on cuda-python's live site ``cuda_core/versions.json`` stops at ``0.3.2`` while
its ``nv-versions.json`` reaches ``1.2.0``, with no visible consequence.

This is not a publication system. It reads one file and checks one membership.
"""

import argparse
import json
import pathlib
import re
import sys


def versions_of(component_root):
    """Return the manifest's versions, in file order."""
    root = pathlib.Path(component_root)
    nv = json.loads((root / "nv-versions.json").read_text(encoding="utf-8"))
    return [entry["version"] for entry in nv]


def check(component_root, version):
    """Raise SystemExit with a specific message, or return the version list."""
    nv = versions_of(component_root)

    if version not in nv:
        raise SystemExit(
            f"error: nv-versions.json does not list {version!r}.\n"
            f"       It lists: {', '.join(nv) or '(nothing)'}\n"
            "       Add the version during release preparation, before tagging.\n"
            "       Without an entry the docs deploy but nothing links to them."
        )

    return nv


def retarget(component_root, component, site_root):
    """Point this component root's absolute URLs at the host serving the build.

    The switcher entries are absolute URLs and the browser follows them, so a
    rehearsal published to a fork would otherwise offer a dropdown whose every
    option navigates to production. The landing redirect's canonical link is
    rewritten for the same reason -- it is inert, but a lone production URL in
    a rehearsal artifact is exactly the confusion this flag exists to remove.

    Only the built artifact is touched. The checked-in manifests still name
    production, because that is where a real release goes.
    """
    root = pathlib.Path(component_root)
    base = f"{site_root.rstrip('/')}/{component}"

    path = root / "nv-versions.json"
    entries = json.loads(path.read_text(encoding="utf-8"))
    for entry in entries:
        entry["url"] = f"{base}/{entry['version']}/"
    path.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")

    landing = root / "index.html"
    if landing.exists():
        landing.write_text(
            re.sub(
                r'(<link rel="canonical" href=")[^"]*(">)',
                rf"\g<1>{base}/unstable/\g<2>",
                landing.read_text(encoding="utf-8"),
            ),
            encoding="utf-8",
        )

    return entries


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("component_root", help="directory holding nv-versions.json")
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
    print(f"  nv-versions.json lists {args.version}: {', '.join(listed)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
