#!/usr/bin/env python3
"""Render the documentation version-switcher manifests.

The list of versions is *discovered* from the directories that actually exist on
the published site, rather than maintained by hand. Publishing a version is
therefore all it takes to have it appear in the switcher: there is no second
step to forget, and the switcher cannot drift out of step with what is really
there. A directory only counts once it contains an ``index.html``, so a
half-written or failed upload is not advertised.

What still needs a human decision is ``latest_stable``, in
``published_versions.json``. Publishing a release is not the same as declaring
it the one readers should land on by default -- during a release candidate
period, or when something turns out to be wrong with a build, you want the
former without the latter.

Two files are written to the site root:

``nv-versions.json``
    Consumed by ``nvidia-sphinx-theme``'s version switcher. ``docs/conf.py``
    points ``html_theme_options.switcher.json_url`` at this file.

``versions.json``
    Legacy manifest. Nothing in this repository reads it, but it is already a
    live URL, so it is rendered from the same source rather than dropped.

Three values the calling shell script needs are printed to stdout, one per line:
the default version (the redirect target for the site root and for legacy
unversioned URLs), the site base path (used to route the 404 handler), and
``latest_stable`` (empty when none is set or when it names a version that is not
actually published).
"""

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

# A directory is a documentation version if it is the development docs or a
# MAJOR.MINOR release. "latest" is excluded: it is an alias, and it gets its own
# switcher entry rather than being listed as a version in its own right.
VERSION_DIR = re.compile(r"^(?:unstable|[0-9]+\.[0-9]+)$")


def load_manifest(path):
    """Load the checked-in settings that cannot be derived from the site."""
    with open(path, encoding="utf-8") as f:
        manifest = json.load(f)

    if "versions" in manifest:
        raise SystemExit(
            f"{path}: 'versions' is no longer read. The version list is "
            f"discovered from the published site; remove the key."
        )

    if "components" not in manifest:
        raise SystemExit(
            f"{path}: no 'components'. The C++ and Python libraries version "
            f"independently and each needs its own entry."
        )

    ids = [c["id"] for c in manifest["components"]]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise SystemExit(f"{path}: duplicate component ids: {sorted(duplicates)}")

    paths = [c.get("path", "") for c in manifest["components"]]
    if len(set(paths)) != len(paths):
        raise SystemExit(f"{path}: two components share a path: {sorted(paths)}")

    return manifest


def get_component(manifest, component_id, path):
    """The settings for one component, by id."""
    for component in manifest["components"]:
        if component["id"] == component_id:
            return component
    known = ", ".join(c["id"] for c in manifest["components"])
    raise SystemExit(f"{path}: no component '{component_id}'. Known: {known}")


def discover_versions(roots):
    """Version directories that exist, across one or more site roots.

    Roots are searched in order and unioned, so a deploy can combine the version
    it has just built with the versions already published.
    """
    found = set()
    for root in roots:
        if root is None:
            continue
        path = Path(root)
        if not path.is_dir():
            continue
        for child in path.iterdir():
            if not child.is_dir() or not VERSION_DIR.match(child.name):
                continue
            # Advertising a directory with no landing page would put a link to
            # a partial or failed upload in front of readers.
            if (child / "index.html").exists():
                found.add(child.name)
    return found


def order_versions(versions):
    """Development docs first, then releases newest to oldest."""

    def release_key(name):
        return tuple(int(part) for part in name.split("."))

    releases = sorted((v for v in versions if v != "unstable"), key=release_key)
    releases.reverse()
    return (["unstable"] if "unstable" in versions else []) + releases


def label_for(version):
    return "unstable (main)" if version == "unstable" else version


def resolve_latest_stable(component, versions, manifest_path):
    """``latest_stable`` if it is actually published, otherwise nothing.

    Pointing the site root at a version that is not there is the failure this
    guards against: the root would redirect to a directory that 404s.
    """
    latest_stable = component.get("latest_stable")
    if latest_stable is None:
        return None

    if latest_stable not in versions:
        print(
            f"warning: {manifest_path} sets {component['id']} latest_stable to "
            f"'{latest_stable}', "
            f"which is not published. Ignoring it; the site root will fall back "
            f"to the development docs. Publish that version to fix this.",
            file=sys.stderr,
        )
        return None

    return latest_stable


def build_switcher_entries(versions, latest_stable, base_url):
    """Build the nv-versions.json payload.

    ``latest_stable`` is marked ``preferred`` rather than the synthetic
    ``latest`` entry. The theme compares ``preferred`` against each page's
    ``version_match`` to decide whether to show the "you are viewing an old
    version" banner, and pages under ``/latest/`` are the stable build's own
    pages, so they carry the stable version string rather than "latest".
    """
    entries = []

    if latest_stable is not None:
        entries.append(
            {
                "name": f"latest ({latest_stable})",
                "version": "latest",
                "url": f"{base_url}latest/",
            }
        )

    for version in versions:
        entry = {
            "name": label_for(version),
            "version": version,
            "url": f"{base_url}{version}/",
        }
        if version == latest_stable:
            entry["preferred"] = True
        entries.append(entry)

    return entries


def build_legacy_versions(versions, latest_stable):
    """The flat ``versions.json`` mapping kept for backwards compatibility."""
    mapping = {}
    if latest_stable is not None:
        mapping["latest"] = "latest"
    for version in versions:
        mapping[version] = version
    return mapping


def default_version(versions, latest_stable):
    """The version the site root and legacy unversioned URLs redirect to.

    Deliberately the concrete version directory rather than the ``latest``
    alias, so that the root keeps resolving even when the alias has not been
    rebuilt yet.
    """
    if latest_stable is not None:
        return latest_stable
    return "unstable" if "unstable" in versions else versions[0]


def site_base_path(base_url, component_path):
    """The path portion of the *site* root, e.g. ``/cccl`` (no trailing slash).

    ``base_url`` addresses the component, so a nested component's path is
    stripped back off: the 404 handler is shared by the whole site and has to
    reason about it as a whole.
    """
    path = urlparse(base_url).path.rstrip("/")
    if component_path:
        suffix = "/" + component_path.strip("/")
        path = path.removesuffix(suffix)
    return path


def check_size_budget(manifest, versions):
    """Warn when the site is likely to outgrow the 1 GB GitHub Pages limit."""
    budget = manifest.get("size_budget_versions")
    if budget is not None and len(versions) > budget:
        print(
            f"warning: {len(versions)} versions are published but the budget is "
            f"{budget}. GitHub Pages refuses to publish a site over 1 GB, and a "
            f"CCCL version costs 110-290 MB. Retire an old release or raise "
            f"size_budget_versions.",
            file=sys.stderr,
        )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, help="published_versions.json")
    parser.add_argument("--base-url", required=True, help="docs site base URL")
    parser.add_argument("--out-dir", required=True, help="component root to write into")
    parser.add_argument(
        "--component",
        required=True,
        help="which component in the manifest this subtree is (e.g. cpp, python)",
    )
    parser.add_argument(
        "--discover-from",
        action="append",
        default=[],
        metavar="DIR",
        help="site root to discover version directories in; repeatable",
    )
    args = parser.parse_args(argv)

    base_url = args.base_url.rstrip("/") + "/"
    manifest = load_manifest(args.manifest)

    discovered = discover_versions(args.discover_from)
    if not discovered:
        raise SystemExit(
            "error: no version directories found in "
            f"{args.discover_from or '(nothing searched)'}. Expected at least "
            f"one directory named 'unstable' or MAJOR.MINOR containing an "
            f"index.html."
        )

    component = get_component(manifest, args.component, args.manifest)
    versions = order_versions(discovered)
    latest_stable = resolve_latest_stable(component, discovered, args.manifest)
    check_size_budget(manifest, versions)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    switcher = build_switcher_entries(versions, latest_stable, base_url)
    (out_dir / "nv-versions.json").write_text(
        json.dumps(switcher, indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / "versions.json").write_text(
        json.dumps(build_legacy_versions(versions, latest_stable), indent=2) + "\n",
        encoding="utf-8",
    )

    # Consumed by assemble_site.bash, one value per line.
    print(default_version(versions, latest_stable))
    print(site_base_path(base_url, component.get("path", "")))
    print(latest_stable or "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
