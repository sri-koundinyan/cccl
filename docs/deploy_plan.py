#!/usr/bin/env python3
"""Decide what a documentation deploy publishes, and where.

Usage:
    deploy_plan.py --event push
    deploy_plan.py --event release --release-tag v3.4.2
    deploy_plan.py --event workflow_dispatch --component cpp --source-ref v3.4.2

Writes ``key=value`` lines to stdout and, when set, to ``$GITHUB_OUTPUT``.

This decides which component's documentation gets published, from which ref,
and into which directory -- the highest-consequence decision in the deploy, and
the one thing that can silently publish the wrong documentation under the right
URL.

It lives here rather than in the workflow because it was bash embedded in YAML,
which nothing type-checks and which cannot be run without a live git remote. In
that form it accumulated three bugs in as many days:

* every tag was validated against the C++ pattern, so no Python release could
  ever be published;
* a branch cut from ``main`` published as a *release* of ``main``'s version,
  which put a 3.6 that was never released onto a live site;
* the component list was resolved before the release event had set the
  component, so publishing a Python release would have rebuilt C++.

None of those are subtle once the logic is callable from a test.

Component site layout is imported from ``publish_site`` rather than repeated,
so the two halves of the system cannot disagree about where a component lives.
"""

import argparse
import json
import os
import re
import subprocess
import sys

from publish_site import COMPONENTS

# Where each component's build lands, relative to docs/_build. This is build
# layout, not site layout -- site layout comes from COMPONENTS -- so the two are
# deliberately separate facts rather than a duplicated one.
BUILD_SUBDIR = {"cpp": "html", "python": "python-html"}

# The components version independently and tag differently.
#
# Every pattern here ends with \Z, not $. In Python `$` also matches just before
# a trailing newline, so `^[0-9]+\.[0-9]+$` accepts "3.4\n" -- and these values
# are written to $GITHUB_OUTPUT as `key=value` lines, where an embedded newline
# starts a second key. \Z means end-of-string and nothing else.
RELEASE_TAG = {
    "cpp": (re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+\Z"), "v3.5.0"),
    "python": (re.compile(r"^python-[0-9]+\.[0-9]+\.[0-9]+\Z"), "python-1.1.1"),
}

VERSION_DIR = re.compile(r"^[0-9]+\.[0-9]+\Z")

# gh-pages, or a gh-pages-<suffix> rehearsal branch. Spelled out in full rather
# than checked with startswith(), which accepted "gh-pages-x\nkey=value".
DOCS_BRANCH = re.compile(r"^gh-pages(-[A-Za-z0-9._-]+)?\Z")

TIP = "unstable"


class PlanError(SystemExit):
    """A deploy that must not proceed."""


def component_path(component_id):
    for component in COMPONENTS:
        if component["id"] == component_id:
            return component["path"]
    raise PlanError(f"error: unknown component {component_id!r}")


def classify_ref_with_git(ref):
    """Is this ref a tag, a branch, or neither? Asks the remote."""
    for kind, namespace in (("tag", "tags"), ("branch", "heads")):
        result = subprocess.run(
            [
                "git",
                "ls-remote",
                "--exit-code",
                f"--{namespace}",
                "origin",
                f"refs/{namespace}/{ref}",
            ],
            capture_output=True,
        )
        if result.returncode == 0:
            return kind
    return None


def plan(
    event,
    *,
    release_tag="",
    release_prerelease=False,
    component="",
    source_ref="",
    publish_as="",
    docs_branch="",
    classify_ref=classify_ref_with_git,
):
    """Return the deploy plan, or raise PlanError explaining why there is none."""
    component = component or "cpp"
    docs_branch = docs_branch or "gh-pages"
    source_ref = source_ref or ""
    expect = ""

    # A published release names its own ref and component, so nothing is typed
    # and nothing can be mistyped.
    #
    # Whether a release should be published at all is decided here rather than
    # in the workflow's job condition, so that it is testable and stated once.
    # The tag pattern below already rejects v3.5.0-rc1 and friends; this catches
    # the case a pattern cannot see -- a clean tag like v3.5.0 whose GitHub
    # Release was marked pre-release by hand.
    if event == "release":
        if release_prerelease:
            raise PlanError(
                f"error: {release_tag} is marked a pre-release; its documentation"
                " is not published."
            )
        source_ref = release_tag
        component = "python" if release_tag.startswith("python-") else "cpp"
        docs_branch = "gh-pages"

    # Resolved only now, so a Python release does not inherit the default of cpp.
    if event == "push" or component == "all":
        if source_ref not in ("", "main"):
            raise PlanError(
                "error: 'all' publishes both components from main.\n"
                "       A release belongs to one component; publish it by name."
            )
        component_ids = [c["id"] for c in COMPONENTS]
        component = component_ids[0]
    else:
        component_ids = [component]

    # A rehearsal must not be able to target production by typo -- and the value
    # is also a git ref and a $GITHUB_OUTPUT value, so it has to be well-formed
    # as both.
    if not DOCS_BRANCH.match(docs_branch):
        raise PlanError(
            "error: docs_branch must be gh-pages or a gh-pages-<suffix> branch"
            " of [A-Za-z0-9._-],"
            f" got {docs_branch!r}"
        )

    # The ref is emitted fully qualified, because the validation above and the
    # checkout below must be talking about the same object. classify_ref asks
    # the remote for tags first, so "release-3.4" is validated as a tag -- but
    # actions/checkout resolves an unqualified name as a *branch* first, so a
    # branch of the same name would be what actually got built and published.
    # refs/tags/... and refs/heads/... are unambiguous to both.
    release_tag_out = ""
    if source_ref in ("", "main"):
        source_ref = "main"
        qualified_ref = "refs/heads/main"
        is_tip = True
        if publish_as not in ("", TIP):
            raise PlanError(
                "error: main always publishes to unstable; drop publish_as."
            )
    else:
        is_tip = False
        kind = classify_ref(source_ref)
        qualified_ref = {
            "tag": f"refs/tags/{source_ref}",
            "branch": f"refs/heads/{source_ref}",
        }.get(kind, source_ref)

        if kind == "tag":
            # A tag is an immutable release marker and must look like one.
            pattern, example = RELEASE_TAG[component]
            if not pattern.match(source_ref):
                raise PlanError(
                    f"error: {source_ref!r} is a tag, but not a {component} release"
                    f" tag.\n       Expected something like {example}.\n"
                    "       Pre-release tags must not be published as the release"
                    " they precede,\n       and the components must not be published"
                    " under each other's numbers."
                )
            release_tag_out = source_ref
        elif kind == "branch":
            # A branch is not self-describing: one cut from main carries main's
            # version, so publishing it as a release would create a directory for
            # a version that was never released. Make the caller say which
            # directory they mean; it is checked against what the tree derives,
            # so it can acknowledge a version but never invent one.
            if not publish_as:
                raise PlanError(
                    f"error: {source_ref!r} is a branch, so publish_as is required.\n"
                    "       Use publish_as=unstable to preview it as the development"
                    " docs, or\n       publish_as=MAJOR.MINOR to publish a release"
                    " built from a patched branch."
                )
            if publish_as == TIP:
                is_tip = True
            elif VERSION_DIR.match(publish_as):
                expect = publish_as
            else:
                raise PlanError(
                    "error: publish_as must be 'unstable' or MAJOR.MINOR,"
                    f" got {publish_as!r}"
                )
        else:
            raise PlanError(
                f"error: {source_ref!r} is neither a tag nor a branch on origin."
            )

    return {
        "component": component,
        "components": " ".join(component_ids),
        "component_plan": json.dumps(
            [
                {
                    "id": cid,
                    "path": component_path(cid),
                    "build": BUILD_SUBDIR[cid],
                }
                for cid in component_ids
            ],
            separators=(",", ":"),
        ),
        "source_ref": qualified_ref,
        "is_tip": "true" if is_tip else "false",
        "expect": expect,
        # The exact tag being published -- empty unless the ref really is a tag.
        # release_version.py uses it instead of `git describe`, which returns
        # *a* reachable tag rather than this one: two python-* tags on a single
        # commit make publishing python-1.2.0 derive 1.1.1.
        "release_tag": release_tag_out,
        "docs_branch": docs_branch,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", required=True)
    parser.add_argument("--release-tag", default="")
    parser.add_argument("--release-prerelease", default="")
    parser.add_argument("--component", default="")
    parser.add_argument("--source-ref", default="")
    parser.add_argument("--publish-as", default="")
    parser.add_argument("--docs-branch", default="")
    args = parser.parse_args(argv)

    result = plan(
        args.event,
        release_tag=args.release_tag,
        release_prerelease=args.release_prerelease == "true",
        component=args.component,
        source_ref=args.source_ref,
        publish_as=args.publish_as,
        docs_branch=args.docs_branch,
    )

    lines = [f"{key}={emittable(key, value)}" for key, value in result.items()]
    print("\n".join(lines))

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    return 0


def emittable(key, value):
    """Refuse to write a value that could forge a second $GITHUB_OUTPUT key.

    The validators above are the real defence; this is the backstop that does
    not depend on remembering to write `\\Z` in the next pattern someone adds.
    Outputs are consumed downstream as step outputs, so a forged key becomes a
    forged decision.
    """
    text = str(value)
    if any(c in text for c in "\r\n\x00"):
        raise PlanError(
            f"error: refusing to emit {key}={text!r}: it contains a newline or"
            " NUL, which would\n"
            "       inject an additional key into $GITHUB_OUTPUT."
        )
    return text


if __name__ == "__main__":
    sys.exit(main())
