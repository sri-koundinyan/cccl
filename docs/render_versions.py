#!/usr/bin/env python3
"""Render the documentation version-switcher manifests.

Reads ``published_versions.json`` -- the checked-in source of truth for which
documentation versions exist -- and writes the two manifests served from the
site root:

``nv-versions.json``
    Consumed by ``nvidia-sphinx-theme``'s version switcher. ``docs/conf.py``
    points ``html_theme_options.switcher.json_url`` at this file.

``versions.json``
    Legacy manifest. Nothing in this repository reads it, but it is already a
    live URL, so it is rendered from the same source rather than dropped.

Every documentation build writes the same complete manifests, which is what
makes versioned publishing safe: deploying 3.4 does not clobber the switcher
entry for 3.3, and deploying ``unstable`` does not clobber either of them.

Three values that the calling shell script needs are printed to stdout, one per
line: the default version (the redirect target for the site root and for legacy
unversioned URLs), the site base path (used to route the 404 handler), and
``latest_stable`` (empty when no stable version has been published yet).
"""

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlparse


def load_manifest(path):
    """Load and validate the checked-in version manifest."""
    with open(path, encoding="utf-8") as f:
        manifest = json.load(f)

    versions = manifest.get("versions")
    if not versions:
        raise SystemExit(f"{path}: 'versions' must be a non-empty list")

    dirs = [entry["dir"] for entry in versions]
    duplicates = {d for d in dirs if dirs.count(d) > 1}
    if duplicates:
        raise SystemExit(f"{path}: duplicate version directories: {sorted(duplicates)}")

    latest_stable = manifest.get("latest_stable")
    if latest_stable is not None and latest_stable not in dirs:
        raise SystemExit(
            f"{path}: latest_stable '{latest_stable}' is not present in 'versions'"
        )

    # GitHub Pages will not publish a site larger than 1 GB, and each version
    # costs 130-180 MB. Warn rather than fail: the fix is deciding which release
    # to retire, which is not a decision a build should make on its own.
    budget = manifest.get("size_budget_versions")
    if budget is not None and len(dirs) > budget:
        print(
            f"warning: {len(dirs)} versions listed but the size budget is "
            f"{budget}; the published site may exceed the 1 GB GitHub Pages "
            f"limit. Retire an old release or raise size_budget_versions.",
            file=sys.stderr,
        )

    return manifest


def build_switcher_entries(manifest, base_url):
    """Build the nv-versions.json payload.

    ``latest_stable`` is marked ``preferred`` rather than the synthetic
    ``latest`` entry. The theme compares ``preferred`` against each page's
    ``version_match`` to decide whether to show the "you are viewing an old
    version" banner, and pages under ``/latest/`` are a copy of the stable
    build, so they carry the stable version string rather than "latest".
    """
    latest_stable = manifest.get("latest_stable")
    entries = []

    if latest_stable is not None:
        entries.append(
            {
                "name": f"latest ({latest_stable})",
                "version": "latest",
                "url": f"{base_url}latest/",
            }
        )

    for entry in manifest["versions"]:
        directory = entry["dir"]
        switcher_entry = {
            "name": entry.get("label", directory),
            "version": directory,
            "url": f"{base_url}{directory}/",
        }
        if directory == latest_stable:
            switcher_entry["preferred"] = True
        entries.append(switcher_entry)

    return entries


def build_legacy_versions(manifest):
    """Build the flat ``versions.json`` mapping kept for backwards compatibility."""
    versions = {}
    if manifest.get("latest_stable") is not None:
        versions["latest"] = "latest"
    for entry in manifest["versions"]:
        versions[entry["dir"]] = entry["dir"]
    return versions


def default_version(manifest):
    """The version the site root and legacy unversioned URLs redirect to.

    Deliberately the concrete version directory rather than the ``latest``
    alias. The alias is only written by a build of latest_stable itself, so
    naming a new latest_stable would otherwise repoint the site root at a
    directory that does not exist yet, and the root would 404 until that
    version happened to be rebuilt.

    Pointing at the concrete directory costs nothing, because these redirects
    are re-rendered from this manifest on every deploy and so track
    latest_stable without needing the alias as an intermediary.
    """
    latest_stable = manifest.get("latest_stable")
    if latest_stable is not None:
        return latest_stable

    dirs = [entry["dir"] for entry in manifest["versions"]]
    return "unstable" if "unstable" in dirs else dirs[0]


def site_base_path(base_url):
    """The path portion of the docs base URL, e.g. ``/cccl`` (no trailing slash)."""
    return urlparse(base_url).path.rstrip("/")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, help="published_versions.json")
    parser.add_argument("--base-url", required=True, help="docs site base URL")
    parser.add_argument("--out-dir", required=True, help="site root to write into")
    args = parser.parse_args(argv)

    base_url = args.base_url.rstrip("/") + "/"
    manifest = load_manifest(args.manifest)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    switcher = build_switcher_entries(manifest, base_url)
    (out_dir / "nv-versions.json").write_text(
        json.dumps(switcher, indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / "versions.json").write_text(
        json.dumps(build_legacy_versions(manifest), indent=2) + "\n", encoding="utf-8"
    )

    # Consumed by assemble_site.bash, one value per line.
    print(default_version(manifest))
    print(site_base_path(base_url))
    print(manifest.get("latest_stable") or "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
