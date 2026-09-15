#!/usr/bin/env python3
"""Decide what a documentation publication will build and where it will go.

This runs *before* anything is built. It sees the triggering event and a
repository; it does not see a single built file. The publisher
(``publish_site.py``) is the mirror image: it runs after the builds and sees
only finished HTML, never the event. Neither can do the other's job, and keeping
them apart is what lets each be tested without Sphinx, Doxygen or a network.

There are exactly two entry points, and no third:

    push to protected main   ->  both components, as "unstable"
    dispatch with one tag    ->  the single component that tag names

Everything a caller might otherwise choose -- component, source ref,
destination directory, output branch, rollback permission, permission to
publish over missing provenance -- is absent by construction rather than
validated. An option that does not exist cannot be misused, and every one of
those is a way to publish content somewhere it does not belong.

Why this is a Python module rather than inline workflow YAML: nothing
type-checks bash embedded in a workflow, and it cannot be run without a live git
remote. As a module it is callable from a test with no git, no shell and no
workflow runner.
"""

import argparse
import json
import os
import sys

from release_version import (
    COMPONENT_PATH,
    TIP,
    IdentityError,
    classify_tag,
    peel_tag,
    require_split_build_contract,
)

# Where each component's build writes its artifact, relative to docs/_build.
BUILD_SUBDIR = {"cpp": "html", "python": "python-html"}


def plan_main_push(source_sha):
    """A push to main publishes both components, from one commit, in one commit.

    Both together because one push advances both: publishing them separately
    would let the two unstable trees drift apart, each claiming a different
    source. It also means a failure in either build publishes neither.
    """
    return {
        "mode": "unstable",
        "components": ["cpp", "python"],
        "version_dir": TIP,
        "release": None,
        "release_tag": None,
        "source_sha": source_sha,
        "checkout_ref": source_sha,
    }


def plan_release(tag, checkout):
    """An exact final tag publishes exactly one component's release line."""
    component, version_dir, release = classify_tag(tag)
    tag_object_sha, source_sha = peel_tag(checkout, tag)

    # Reject a pre-split source here, in seconds, rather than after a
    # fifteen-minute Doxygen build produces an artifact we would have to throw
    # away anyway.
    require_split_build_contract(checkout)

    return {
        "mode": "release",
        "components": [component],
        "version_dir": version_dir,
        "release": release,
        "release_tag": tag,
        "tag_object_sha": tag_object_sha,
        "source_sha": source_sha,
        # Fully qualified: `git rev-parse` resolved a *tag*, but an unqualified
        # name handed to actions/checkout resolves as a *branch* first, so a
        # same-named branch would be what actually got built.
        "checkout_ref": f"refs/tags/{tag}",
    }


def plan(event, *, release_tag="", source_sha="", checkout="."):
    """Return the complete plan for one publication."""
    if event == "push":
        if not source_sha:
            raise IdentityError(
                "error: a main-push publication needs the triggering commit SHA."
            )
        return plan_main_push(source_sha)

    if event == "workflow_dispatch":
        if not release_tag:
            raise IdentityError(
                "error: a manual publication needs exactly one input, release_tag.\n"
                "       There is no way to publish an arbitrary branch or commit:\n"
                "       the tag is what determines component and destination."
            )
        return plan_release(release_tag, checkout)

    raise IdentityError(
        f"error: {event!r} does not publish documentation.\n"
        "       The only triggers are a push to main and a manual dispatch\n"
        "       carrying one exact release tag."
    )


def emittable(key, value):
    """Refuse to write a value that could forge a second $GITHUB_OUTPUT key.

    Steps communicate by appending ``key=value`` lines to a file, so a value
    containing a newline writes a second key -- and a forged key becomes a
    forged decision downstream. The grammars in release_version.py are the real
    defence; this is the backstop that does not depend on remembering to anchor
    the next pattern someone adds.
    """
    text = "" if value is None else str(value)
    if any(c in text for c in "\r\n\x00"):
        raise IdentityError(
            f"error: refusing to emit {key}={text!r}: it contains a newline or\n"
            "       NUL, which would inject an additional workflow output."
        )
    return text


def as_outputs(result):
    """Flatten a plan into workflow outputs."""
    return {
        "mode": result["mode"],
        "components": " ".join(result["components"]),
        "component_plan": json.dumps(
            [
                {
                    "id": c,
                    "path": COMPONENT_PATH[c],
                    "build": BUILD_SUBDIR[c],
                }
                for c in result["components"]
            ],
            separators=(",", ":"),
        ),
        "version_dir": result["version_dir"],
        "release": result.get("release") or "",
        "release_tag": result.get("release_tag") or "",
        "source_sha": result["source_sha"],
        "checkout_ref": result["checkout_ref"],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--event", required=True, choices=("push", "workflow_dispatch"))
    parser.add_argument("--release-tag", default="", help="exact final tag (dispatch only)")
    parser.add_argument("--source-sha", default="", help="triggering commit (push only)")
    parser.add_argument("--checkout", default=".", help="repository to resolve the tag in")
    args = parser.parse_args(argv)

    result = plan(
        args.event,
        release_tag=args.release_tag,
        source_sha=args.source_sha,
        checkout=args.checkout,
    )

    lines = [f"{k}={emittable(k, v)}" for k, v in as_outputs(result).items()]
    print("\n".join(lines))

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
