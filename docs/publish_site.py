#!/usr/bin/env python3
"""Assemble the published documentation site, or refuse to.

Usage:
    publish_site.py <site_root> --plan <plan.json>

``site_root`` is the Pages source directory -- ``docs/`` inside a ``gh-pages``
checkout -- already seeded with the complete live site. This script replaces the
directories the plan names, derives the files that describe the site as a whole,
validates the result, and stops short of committing. The workflow commits and
pushes; keeping those out of here means every check below can run in a test
against an ordinary directory.

The seeding matters more than it looks. Because ``site_root`` starts as a copy
of what is live, it *is* the complete desired state -- which is what makes
publishing the whole tree safe rather than destructive. Additive across versions
comes from the seed; destructive within one comes from replacing exactly the
planned directory.

What this deliberately does not do, because the contract forbids it:

* no ``latest`` alias, and no notion of a "newest stable" to promote. Both
  components prefer ``unstable``, and publishing a release never changes that;
* no retention or deletion. Old releases are never removed automatically;
* no site-shell generation. The chooser, Python entry page, 404 page and
  ``.nojekyll`` are written once at launch and thereafter only verified;
* no fuzzy 404 routing and no generated page lists;
* no arbitrary destination, no rollback switch, no permission to publish over
  missing provenance. Those are absent by construction, not validated away.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from release_version import (
    PROVENANCE_FILE,
    RELEASE_FILE,
    TIP,
    VERSION_DIR,
    IdentityError,
    build_provenance,
    classify_target,
    is_ancestor,
    read_provenance,
    require_unstable_pair_agrees,
    same_content_identity,
)

# Components, in the order they appear on the site.
COMPONENTS = [
    {"id": "cpp", "label": "C++", "path": ""},
    {"id": "python", "label": "Python", "path": "python"},
]

# Files that make up the site shell. Written once by the launch candidate and
# preserved byte-for-byte afterwards; an ordinary publication that changed one
# would be changing what every reader sees without review.
SHELL_FILES = ["index.html", "404.html", ".nojekyll", "python/index.html"]

# Without this file GitHub Pages runs Jekyll over the branch, which drops
# underscore-prefixed directories -- taking _static/ with it. Every HTML route
# still returns 200 while the styles and the version-switcher JavaScript are
# simply gone, so a page-level smoke test cannot see the failure. It is checked
# explicitly for that reason.
SENTINEL = ".nojekyll"

# GitHub Pages refuses to publish a site over 1 GB. Stopping below that turns an
# opaque platform rejection into an actionable message, and it is the MVP's only
# automatic brake: nothing here ever deletes content to make room.
SIZE_CEILING_BYTES = 900 * 1024 * 1024

# Sphinx writes this into every page; the theme compares it against a manifest
# entry's "version" to decide which switcher entry is current.
VERSION_MATCH = re.compile(r"version_match\s*=\s*'([^']*)'")


# --------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------


def sort_key(version):
    """Newest first, with the development tip always leading.

    Compared as numeric tuples, not strings: lexicographically "3.9" sorts after
    "3.10" and "4.0" lands in the wrong place entirely.
    """
    if version == TIP:
        return (0,)
    return (1, tuple(-int(part) for part in version.split(".")))


def discover_versions(component_root):
    """The versions actually published under a component.

    A directory counts only once it contains an ``index.html``. A half-finished
    upload is therefore never advertised in the switcher, and the manifest can
    never list a version a reader cannot reach.
    """
    root = Path(component_root)
    if not root.is_dir():
        return []
    found = [
        entry.name
        for entry in root.iterdir()
        if entry.is_dir()
        and VERSION_DIR.match(entry.name)
        and (entry / "index.html").is_file()
    ]
    return sorted(found, key=sort_key)


# --------------------------------------------------------------------------
# Placement
# --------------------------------------------------------------------------


def place_component(site_root, component, artifact, version_dir, provenance):
    """Replace one component's version directory with a freshly built artifact.

    ``rm -rf`` then copy, rather than merging: a merge would leave behind every
    page the new build no longer produces, and the pages that churn most are the
    machine-named Doxygen ones, so the debris would accumulate exactly where it
    grows fastest.
    """
    target = Path(site_root) / component["path"] / version_dir
    source = Path(artifact)

    if not (source / "index.html").is_file():
        raise IdentityError(
            f"error: {source} does not look like a built artifact "
            "(no index.html)."
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)

    if provenance.get("release"):
        (target / RELEASE_FILE).write_text(
            provenance["release"] + "\n", encoding="utf-8"
        )
    (target / PROVENANCE_FILE).write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return target


# --------------------------------------------------------------------------
# Derived files
# --------------------------------------------------------------------------


def write_manifests(site_root, component, versions):
    """Write this component's switcher manifest from what is actually published.

    Derived from the staged directories rather than declared anywhere. A version
    can only appear because its directory exists, so the switcher and the site
    cannot disagree -- a failure mode visible on a sibling NVIDIA project, whose
    two manifests currently list seven and twenty-one versions because each is
    written by whichever build ran last.

    Unstable is marked preferred for both components. The MVP has no "newest
    stable" concept: publishing a release never changes a component's default.
    """
    root = Path(site_root) / component["path"]
    prefix = f"/cccl/{component['path']}/" if component["path"] else "/cccl/"

    entries = [
        {
            # Origin-relative so the identical files work on the staging host,
            # which serves the same /cccl/ base path.
            "url": f"{prefix}{version}/",
            "version": version,
            "preferred": version == TIP,
        }
        for version in versions
    ]
    (root / "nv-versions.json").write_text(
        json.dumps(entries, indent=2) + "\n", encoding="utf-8"
    )

    # The older manifest format, retained for the C++ component only. Nothing in
    # this repository reads it, but an external consumer may, and regenerating
    # it mechanically is cheaper than an unverified compatibility break.
    if component["id"] == "cpp":
        (root / "versions.json").write_text(
            json.dumps({v: v for v in versions}, indent=2) + "\n", encoding="utf-8"
        )


def write_inventory_alias(site_root, component, versions):
    """Expose the development inventory at a stable per-component URL.

    ``/cccl/objects.inv`` holds C++ targets and ``/cccl/python/objects.inv``
    Python ones. The root inventory deliberately stops carrying Python targets:
    each component owns its own machine-readable files.
    """
    if TIP not in versions:
        return
    root = Path(site_root) / component["path"]
    source = root / TIP / "objects.inv"
    if source.is_file():
        shutil.copyfile(source, root / "objects.inv")


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


def check_stamps(site_root, component, versions, problems):
    """Every published page must claim the directory it is served from.

    When the stamp and the directory disagree the site builds, deploys and
    renders perfectly -- and the version switcher silently never highlights the
    current page. Nothing else in the pipeline notices, which is why this is
    checked against every published version on every publication rather than
    only the one just built.
    """
    root = Path(site_root) / component["path"]
    for version in versions:
        index = root / version / "index.html"
        try:
            text = index.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            problems.append(f"{component['id']}/{version}: unreadable index.html")
            continue
        match = VERSION_MATCH.search(text)
        if not match:
            problems.append(
                f"{component['id']}/{version}: no version_match stamp; the "
                "switcher cannot identify this page"
            )
        elif match.group(1) != version:
            problems.append(
                f"{component['id']}/{version}: stamped {match.group(1)!r} but "
                f"served from {version!r}; the switcher can never highlight it"
            )


def check_shell(site_root, problems):
    """The site shell must be present, and `.nojekyll` above all."""
    root = Path(site_root)
    if not (root / SENTINEL).is_file():
        problems.append(
            f"{SENTINEL} is missing from the Pages root. Without it GitHub Pages "
            "runs Jekyll and drops _static/, so every page returns 200 with no "
            "styles and no version switcher."
        )
    for name in SHELL_FILES:
        if name == SENTINEL:
            continue
        if not (root / name).is_file():
            problems.append(f"site shell file {name} is missing")


def check_provenance(site_root, component, versions, problems):
    """Every published version must be able to identify itself."""
    root = Path(site_root) / component["path"]
    for version in versions:
        record = read_provenance(root / version)
        if record is None:
            problems.append(
                f"{component['id']}/{version}: no valid {PROVENANCE_FILE}; its "
                "contents cannot be identified and a later publication cannot "
                "tell whether it would overwrite something newer"
            )
            continue
        if record.get("version_directory") != version:
            problems.append(
                f"{component['id']}/{version}: provenance claims directory "
                f"{record.get('version_directory')!r}"
            )
        if record.get("component") != component["id"]:
            problems.append(
                f"{component['id']}/{version}: provenance claims component "
                f"{record.get('component')!r}"
            )


def snapshot(site_root):
    """Relative path -> content hash, for every file in the tree."""
    root = Path(site_root)
    out = {}
    for path in root.rglob("*"):
        if path.is_file():
            out[str(path.relative_to(root))] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return out


def allowed_write_set(mode, components, version_dir):
    """Which path prefixes this operation is permitted to change.

    Everything else in the tree must come through byte-for-byte. This is what
    makes "a C++ release cannot touch Python content" a checked property rather
    than an intention.
    """
    allowed = set()
    for component in components:
        prefix = f"{component['path']}/" if component["path"] else ""
        allowed.add(f"{prefix}{version_dir}/")
        allowed.add(f"{prefix}nv-versions.json")
        allowed.add(f"{prefix}objects.inv")
        if component["id"] == "cpp":
            allowed.add("versions.json")
    return allowed


def check_write_set(before, after, allowed, problems):
    """Reject any change outside the declared write set."""
    changed = {
        path
        for path in set(before) | set(after)
        if before.get(path) != after.get(path)
    }
    for path in sorted(changed):
        if not any(
            path == rule or path.startswith(rule) for rule in allowed
        ):
            problems.append(
                f"{path} changed, but this operation may only write: "
                + ", ".join(sorted(allowed))
            )


def check_size(site_root, problems):
    """Stop below the hosting limit rather than being refused by it."""
    total = sum(p.stat().st_size for p in Path(site_root).rglob("*") if p.is_file())
    mb = total / 1024 / 1024
    print(f"  served tree: {mb:.0f} MB")
    if total > SIZE_CEILING_BYTES:
        problems.append(
            f"served tree is {mb:.0f} MB, over the {SIZE_CEILING_BYTES // 1024 // 1024} MB "
            "ceiling. Nothing is deleted automatically: retiring a version is a "
            "reviewed decision, not something the publisher may choose."
        )


# --------------------------------------------------------------------------
# Identity of the assembled tree
# --------------------------------------------------------------------------


def subtree_identity(site_root):
    """The Git tree object ID of the assembled Pages source.

    This is the identity approved on staging and required to match in
    production. It is the *subtree* for the Pages source, never the branch root
    tree: the root also spans files outside the Pages source -- a CNAME, for
    instance -- and staging runs in a different repository whose root need not
    match production's. A root-tree comparison would differ even when every
    published byte is identical.

    Tree identity only means something if Git cannot transform or omit files
    while staging them, so the guards below are part of the measurement.
    """
    root = Path(site_root)

    for control in (".gitignore", ".gitattributes"):
        if (root / control).exists():
            raise IdentityError(
                f"error: {control} in the Pages source would let Git omit or "
                "rewrite files while staging them, so the tree ID would no "
                "longer describe what is published."
            )

    executable = [
        str(p.relative_to(root))
        for p in root.rglob("*")
        if p.is_file() and p.stat().st_mode & 0o111
    ]
    if executable:
        raise IdentityError(
            "error: executable files in the assembled Pages tree: "
            + ", ".join(sorted(executable)[:5])
            + ".\n       File modes are part of a Git tree, and documentation "
            "artifacts travel as ZIPs that do not reliably preserve the "
            "executable bit, so an irrelevant mode difference would change the "
            "identity."
        )

    # Staged through a throwaway index so the identity can be computed without
    # touching -- or requiring -- the gh-pages checkout's own index.
    #
    # The index is rooted at site_root, which *is* the Pages source content, so
    # the tree written here is the same object the workflow will find at
    # `git rev-parse $(git write-tree):docs` after committing. Both describe the
    # published content and neither includes whatever else lives at the branch
    # root -- a CNAME, for example, which production has and staging does not.
    with tempfile.TemporaryDirectory() as scratch:
        env = {
            **os.environ,
            "GIT_DIR": str(Path(scratch) / "git"),
            "GIT_WORK_TREE": str(root),
            "GIT_INDEX_FILE": str(Path(scratch) / "index"),
            # Line-ending conversion would alter blob contents, and therefore
            # the identity, for a reason that has nothing to do with content.
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "core.autocrlf",
            "GIT_CONFIG_VALUE_0": "false",
        }

        def git(*args):
            return subprocess.run(
                ["git", *args], env=env, capture_output=True, text=True, check=False
            )

        if git("init", "-q").returncode != 0:
            return None
        if git("add", "-A", "--force", ".").returncode != 0:
            return None
        result = git("write-tree")
        if result.returncode != 0:
            return None
        return result.stdout.strip()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("site_root", help="the staged Pages source directory")
    parser.add_argument("--plan", required=True, help="JSON describing this publication")
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="validate the tree without placing anything",
    )
    args = parser.parse_args(argv)

    site_root = Path(args.site_root)
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))

    # A failed read of the live site must never be interpreted as an empty site;
    # publishing over that would replace the archive with one version.
    if not site_root.is_dir():
        raise IdentityError(f"error: {site_root} does not exist; nothing was seeded.")

    version_dir = plan["version_dir"]
    planned = [c for c in COMPONENTS if c["id"] in {p["id"] for p in plan["components"]}]

    before = snapshot(site_root)

    # Invariants 4 and 5 for an unstable publication, checked against the seed
    # before a single file is replaced.
    if plan["mode"] == "unstable" and not args.verify_only:
        published = require_unstable_pair_agrees(
            site_root, {c["id"]: c["path"] for c in COMPONENTS}
        )
        incoming = plan.get("release_source_sha")
        if published and incoming and plan.get("source_checkout"):
            if not is_ancestor(plan["source_checkout"], published, incoming):
                raise IdentityError(
                    f"error: {incoming} does not descend from the published "
                    f"unstable source {published}.\n"
                    "       Jobs can finish out of order, so an older build "
                    "finishing later\n"
                    "       must not overwrite a newer site."
                )
            print(f"  ancestry: {published[:12]} -> {incoming[:12]} ok")

    if not args.verify_only:
        for entry in plan["components"]:
            component = next(c for c in COMPONENTS if c["id"] == entry["id"])
            provenance = build_provenance(
                component=entry["id"],
                version_directory=version_dir,
                release=plan.get("release"),
                release_tag=plan.get("release_tag"),
                release_source_sha=plan.get("release_source_sha"),
                overlay_sha=plan.get("overlay_sha"),
                publisher_sha=plan.get("publisher_sha"),
                artifact_sha256=entry.get("sha256"),
            )

            target = site_root / component["path"] / version_dir
            if plan.get("release"):
                action, existing = classify_target(target, plan["release"])
                if action == "noop":
                    if not same_content_identity(existing, provenance):
                        raise IdentityError(
                            f"error: {version_dir} already holds {plan['release']}, "
                            "but from a different source or overlay. Publishing "
                            "the same release from different inputs is a change "
                            "of content and needs separate review."
                        )
                    print(f"  {entry['id']}/{version_dir}: already published, unchanged")
                    continue
            place_component(site_root, component, entry["artifact"], version_dir, provenance)
            print(f"  {entry['id']}/{version_dir}: placed")

    problems = []
    for component in COMPONENTS:
        root = site_root / component["path"]
        versions = discover_versions(root)
        if not versions:
            continue
        if not args.verify_only:
            write_manifests(site_root, component, versions)
            write_inventory_alias(site_root, component, versions)
        check_stamps(site_root, component, versions, problems)
        check_provenance(site_root, component, versions, problems)
        print(f"  {component['id']}: {', '.join(versions)}")

    check_shell(site_root, problems)
    check_size(site_root, problems)

    if not args.verify_only:
        check_write_set(
            before, snapshot(site_root),
            allowed_write_set(plan["mode"], planned, version_dir),
            problems,
        )

    tree_id = subtree_identity(site_root)
    if tree_id:
        print(f"  pages subtree: {tree_id}")

    if problems:
        for problem in problems:
            print(f"  error: {problem}", file=sys.stderr)
        raise IdentityError(f"error: {len(problems)} problem(s); nothing was committed")

    print("  site is coherent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
