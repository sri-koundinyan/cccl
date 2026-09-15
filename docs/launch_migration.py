#!/usr/bin/env python3
"""One-time launch: create the first provenance-complete Pages commit.

DISPOSABLE. This file, its manifest and its workflow are deleted once the
launch is accepted. It is not a supported operation and must never become one.

Why it has to exist at all
--------------------------
The permanent publisher refuses to write over a version directory that cannot
identify itself, because reading "I cannot tell what is here" as "safe to
overwrite" is the fail-open that lets an older release replace a newer one.

The legacy site predates that rule: ``/unstable/`` carries no
``.provenance.json``. So the permanent publisher cannot perform the first
migration -- it would deadlock on exactly the check it exists to establish.
This driver is the single audited bootstrap that breaks that circle, once.

What keeps it from being a back door
------------------------------------
* it takes no inputs at all -- no component, ref, destination or override;
* it imports the permanent publisher's own manifest, stamp and provenance
  functions rather than reimplementing them, so ``P0`` is assembled under the
  same rules the first ordinary publication will apply. Reimplementing them
  would mean the very next push rewrites the files just approved;
* the only thing it does that the permanent publisher may not is start from an
  unprovenanced seed and write the site shell.
"""

import argparse
import json
import sys
from pathlib import Path

from publish_site import (
    COMPONENTS,
    SHELL_FILES,
    check_provenance,
    check_shell,
    check_size,
    check_stamps,
    discover_versions,
    place_component,
    subtree_identity,
    write_inventory_alias,
    write_manifests,
)
from release_version import TIP, IdentityError, build_provenance

# The shell, copied from source at launch and never rewritten afterwards. The
# ordinary publisher is forbidden from touching these, so this is the only
# moment they are authored.
SHELL_SOURCES = {
    "index.html": "index.html",
    "404.html": "404.html",
    "python/index.html": "python_index.html",
}


def write_shell(site_root, docs_dir):
    """Author the site shell and the Pages sentinel.

    ``.nojekyll`` matters more than it looks: without it GitHub Pages runs
    Jekyll over the branch and drops underscore-prefixed directories, taking
    ``_static/`` with them. Every HTML route still returns 200 while the styles
    and the version switcher are simply gone.
    """
    site_root = Path(site_root)
    docs_dir = Path(docs_dir)

    for target, source in SHELL_SOURCES.items():
        destination = site_root / target
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            (docs_dir / source).read_text(encoding="utf-8"), encoding="utf-8"
        )
        print(f"  shell: {target}")

    (site_root / ".nojekyll").write_text("", encoding="utf-8")
    print("  shell: .nojekyll")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("site_root", help="the seeded Pages source directory")
    parser.add_argument("--docs-dir", required=True, help="docs/ in the source checkout")
    parser.add_argument("--source-sha", required=True, help="the main commit being published")
    parser.add_argument("--publisher-sha", required=True, help="the trusted tooling commit")
    parser.add_argument(
        "--artifact", action="append", default=[], metavar="ID=PATH",
        help="component artifact, e.g. cpp=/path/to/html/unstable",
    )
    args = parser.parse_args(argv)

    site_root = Path(args.site_root)
    if not site_root.is_dir():
        raise IdentityError(
            f"error: {site_root} does not exist. The launch seeds from the live "
            "site; a failed read is not an empty site."
        )

    artifacts = {}
    for entry in args.artifact:
        component_id, _, path = entry.partition("=")
        artifacts[component_id] = path
    if set(artifacts) != {c["id"] for c in COMPONENTS}:
        raise IdentityError(
            "error: the launch publishes every component at once. "
            f"Got {sorted(artifacts)}, need {sorted(c['id'] for c in COMPONENTS)}."
        )

    print("Assembling the launch candidate")

    # Both unstable trees from one commit. They must agree on their source,
    # because that is the invariant every later publication relies on.
    for component in COMPONENTS:
        provenance = build_provenance(
            component=component["id"],
            version_directory=TIP,
            release=None,
            release_tag=None,
            release_source_sha=args.source_sha,
            overlay_sha=None,
            publisher_sha=args.publisher_sha,
            artifact_sha256=None,
        )
        place_component(site_root, component, artifacts[component["id"]], TIP, provenance)
        print(f"  {component['id']}/{TIP}: placed with provenance")

    write_shell(site_root, args.docs_dir)

    problems = []
    for component in COMPONENTS:
        versions = discover_versions(site_root / component["path"])
        if not versions:
            continue
        write_manifests(site_root, component, versions)
        write_inventory_alias(site_root, component, versions)
        check_stamps(site_root, component, versions, problems)
        check_provenance(site_root, component, versions, problems)
        print(f"  {component['id']}: {', '.join(versions)}")

    check_shell(site_root, problems)
    check_size(site_root, problems)

    if problems:
        for problem in problems:
            print(f"  error: {problem}", file=sys.stderr)
        raise IdentityError(
            f"error: {len(problems)} problem(s); the candidate is not publishable"
        )

    tree_id = subtree_identity(site_root)
    print(f"  candidate docs/ subtree: {tree_id}")
    print("  candidate is coherent")

    # Everything a reviewer needs to reproduce this exact candidate.
    ledger = {
        "source_sha": args.source_sha,
        "publisher_sha": args.publisher_sha,
        "candidate_subtree": tree_id,
        "components": sorted(artifacts),
        "shell_files": SHELL_FILES,
    }
    (site_root.parent / "launch-ledger.json").write_text(
        json.dumps(ledger, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
