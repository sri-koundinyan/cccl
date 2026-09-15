#!/usr/bin/env python3
"""Release identity: what a tag means, and whether it may replace what is there.

CCCL publishes two independently versioned documentation products, so the first
question any publication must answer is *which component, and which directory*.
This module answers it from one exact final tag and nothing else.

Two rules shape everything here.

**The tag names the destination.** ``v3.4.2`` is the C++ component, directory
``3.4``. ``python-1.1.1`` is the Python component, directory ``python/1.1``. A
caller never supplies the component or the destination, so no input can redirect
a publication somewhere it does not belong.

**A version directory holds a release line, not a release.** ``/cccl/3.4/``
means "the 3.4 line, newest patch". It may advance 3.4.2 -> 3.4.3 and must never
move backwards, because nothing about *when* a job runs guarantees order: GitHub
does not promise execution order within a concurrency group, and re-running an
older release's deploy is ordinary maintenance.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# The two accepted final-release grammars. Anchored with \Z rather than $
# because in Python `$` also matches immediately before a trailing newline, so
# `^v\d+\.\d+\.\d+$` accepts "v3.4.2\n" -- and these values are written to
# $GITHUB_OUTPUT as key=value lines, where an embedded newline starts a second
# key.
TAG_GRAMMAR = {
    "cpp": re.compile(r"^v([0-9]+)\.([0-9]+)\.([0-9]+)\Z"),
    "python": re.compile(r"^python-([0-9]+)\.([0-9]+)\.([0-9]+)\Z"),
}

# Where each component's versions live, relative to the Pages source root.
COMPONENT_PATH = {"cpp": "", "python": "python"}

# A published version directory: the development tip, or a release line.
VERSION_DIR = re.compile(r"^(?:unstable|[0-9]+\.[0-9]+)\Z")

# A full release, as recorded in .release and provenance.
RELEASE = re.compile(r"^([0-9]+)\.([0-9]+)\.([0-9]+)\Z")

TIP = "unstable"

PROVENANCE_FILE = ".provenance.json"
RELEASE_FILE = ".release"

# The marker proving a source carries the split-build contract. Its absence
# means the source predates the split and would build the old combined site.
SPLIT_MARKER = Path("docs/python_conf/conf.py")


class IdentityError(SystemExit):
    """A publication that must not proceed."""


# --------------------------------------------------------------------------
# Tags
# --------------------------------------------------------------------------


def classify_tag(tag):
    """``"v3.4.2"`` -> ``("cpp", "3.4", "3.4.2")``.

    Pre-release suffixes, branch names, abbreviated SHAs and anything that
    merely resembles a version are rejected. There is no "close enough": a tag
    either is one of the two final-release forms or it is not a publishable
    input.
    """
    text = (tag or "").strip()
    for component, pattern in TAG_GRAMMAR.items():
        match = pattern.match(text)
        if match:
            major, minor, patch = match.groups()
            return component, f"{major}.{minor}", f"{major}.{minor}.{patch}"

    raise IdentityError(
        f"error: {text!r} is not an exact final release tag.\n"
        "       Expected vMAJOR.MINOR.PATCH (C++) or python-MAJOR.MINOR.PATCH.\n"
        "       Pre-release tags, branches and commit SHAs are not publishable:\n"
        "       the tag is what determines the component and destination, so it\n"
        "       has to be unambiguous."
    )


def peel_tag(checkout, tag):
    """Resolve a tag to the commit it ultimately names.

    Annotated tags are objects in their own right, and one annotated tag can
    point at another before reaching a commit -- ``v3.4.2`` does exactly that.
    ``^{commit}`` peels recursively, however many layers there are.

    Returns ``(tag_object_sha, source_sha)``. The tag object is useful audit
    evidence but is deliberately not published: re-creating a tag object over
    the same commit changes it without changing a single byte of documentation.
    """
    def rev(spec):
        result = subprocess.run(
            ["git", "rev-parse", "--verify", "--end-of-options", spec],
            cwd=checkout, capture_output=True, text=True, check=False,
        )
        if result.returncode != 0:
            raise IdentityError(
                f"error: cannot resolve {spec!r} in {checkout}.\n"
                f"       {result.stderr.strip()}\n"
                "       Tag objects need a complete checkout; a shallow one may\n"
                "       simply not have them."
            )
        return result.stdout.strip()

    return rev(f"refs/tags/{tag}"), rev(f"refs/tags/{tag}^{{commit}}")


def require_split_build_contract(checkout):
    """Reject a source that predates the C++/Python split, before building it.

    A pre-split source builds the old combined site: Python pages land under the
    C++ version directory, labelled with a C++ release they never shipped under.

    Checked by the presence of ``docs/python_conf/conf.py``, which exists only
    on sources carrying the split. It is a fast, unambiguous marker -- this
    rejects in seconds rather than after a fifteen-minute Doxygen build. It is
    not the only guard: gen_docs.bash separately rejects a finished C++ artifact
    containing a top-level ``python/`` directory, which catches a source whose
    marker is present but whose exclusion is broken.
    """
    if not (Path(checkout) / SPLIT_MARKER).is_file():
        raise IdentityError(
            f"error: {checkout} does not contain {SPLIT_MARKER}.\n"
            "       That file marks a source carrying the split-build contract.\n"
            "       Without it the C++ build produces the old combined site,\n"
            "       publishing Python pages under a C++ version.\n"
            "       Backport the split build to this release branch before\n"
            "       publishing documentation from it."
        )


# --------------------------------------------------------------------------
# Whether an incoming release may replace what is published
# --------------------------------------------------------------------------


def release_order(release):
    """``"3.4.2"`` -> ``(3, 4, 2)``, or ``None`` if it is not a full release."""
    match = RELEASE.match((release or "").strip())
    return tuple(int(part) for part in match.groups()) if match else None


def is_downgrade(existing, incoming):
    """``True`` (refuse), ``False`` (allow), or ``None`` ("cannot tell").

    ``None`` is the case worth being careful about, and the reason this returns
    three values rather than two. It means something is published there but will
    not say what, so whether this would move the directory backwards is
    unknowable. Reading that as "safe to overwrite" is a fail-open: a directory
    built from 1.1.1 but carrying no provenance would happily accept 1.1.0.

    The caller decides what to do with ``None``; see ``classify_target``.
    """
    old, new = release_order(existing), release_order(incoming)
    if new is None:
        return False          # not publishing a release; nothing to compare
    if old is None:
        return None           # something is there, but it will not identify itself
    return new < old


def classify_target(directory, incoming_release):
    """Decide what publishing ``incoming_release`` into ``directory`` may do.

    A stable target has three states, not two, and conflating the last two is
    how a fail-open gets written:

    ``absent``   nothing published yet. Valid for a genuinely new release line
                 such as the first ``/3.5/``; the publication creates the
                 directory, its ``.release`` and its provenance atomically.
    ``create``   -- as above.
    ``replace``  published, provenance valid, incoming is newer. Ordinary.
    ``noop``     published and identical. Nothing to do.
    (raises)     published but older, mismatched, or unidentifiable.
    """
    directory = Path(directory)
    if not directory.is_dir():
        return "create", None

    provenance = read_provenance(directory)
    if provenance is None:
        raise IdentityError(
            f"error: {directory} exists but records no valid provenance.\n"
            "       Its contents cannot be identified, so whether this would\n"
            "       overwrite a newer build is unknowable. Absence of a\n"
            "       directory is a new release line; absence of provenance\n"
            "       inside one is not permission to overwrite it."
        )

    existing = provenance.get("release")
    verdict = is_downgrade(existing, incoming_release)
    if verdict:
        raise IdentityError(
            f"error: refusing to publish {incoming_release} over {existing}\n"
            f"       in {directory}. A version directory tracks the newest patch\n"
            "       in its line, and job order is not guaranteed -- a delayed or\n"
            "       re-run older release must not overwrite a newer one."
        )
    if existing == incoming_release:
        return "noop", provenance
    return "replace", provenance


def read_provenance(directory):
    """Return a version directory's provenance record, or ``None`` if unusable.

    Unreadable, malformed and self-inconsistent all collapse to ``None``: the
    caller treats every one of them as "cannot identify this", which is the only
    safe reading.
    """
    path = Path(directory) / PROVENANCE_FILE
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict):
        return None
    if record.get("component") not in COMPONENT_PATH:
        return None
    if not VERSION_DIR.match(str(record.get("version_directory", ""))):
        return None
    return record


def same_content_identity(existing, incoming):
    """Is this exactly the release already published, from the same inputs?

    Compares what determined the content: component, destination, release, tag
    and the source and overlay it was built from. ``publisher_sha`` is
    deliberately excluded -- a later publisher verifying an existing identity
    changes nothing, and including it would turn routine re-dispatch into a
    failure without preventing any content replacement, since an equal identity
    writes nothing either way.
    """
    keys = (
        "component",
        "version_directory",
        "release",
        "release_tag",
        "release_source_sha",
        "overlay_sha",
    )
    return all(existing.get(k) == incoming.get(k) for k in keys)


def build_provenance(
    component,
    version_directory,
    release=None,
    release_tag=None,
    release_source_sha=None,
    overlay_sha=None,
    publisher_sha=None,
    artifact_sha256=None,
):
    """The record written into a published version directory.

    Minimal on purpose. The build source is not stored as a separate field
    because it is exactly ``overlay_sha`` when an overlay exists and
    ``release_source_sha`` otherwise -- a second field could only ever disagree
    with the two that derive it.
    """
    return {
        "component": component,
        "version_directory": version_directory,
        "release": release,
        "release_tag": release_tag,
        "release_source_sha": release_source_sha,
        "overlay_sha": overlay_sha,
        "publisher_sha": publisher_sha,
        "artifact_sha256": artifact_sha256,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Resolve an exact release tag.")
    parser.add_argument("tag", help="exact final tag, e.g. v3.4.2 or python-1.1.1")
    parser.add_argument("--checkout", default=".", help="repository to resolve it in")
    args = parser.parse_args(argv)

    component, version_directory, release = classify_tag(args.tag)
    tag_object, source = peel_tag(args.checkout, args.tag)

    for line in (
        f"component={component}",
        f"version_dir={version_directory}",
        f"release={release}",
        f"release_tag={args.tag}",
        f"tag_object_sha={tag_object}",
        f"release_source_sha={source}",
    ):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
