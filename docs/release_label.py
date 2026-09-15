#!/usr/bin/env python3
"""Map a release tag to the component and directory its documentation belongs in.

    v3.4.2        ->  cpp     3.4.2    ->  /cccl/cpp/3.4.2/
    python-1.1.1  ->  python  1.1.1    ->  /cccl/python/1.1.1/

The tag is the only input. Nothing else supplies a component or a directory
name, so a Python release cannot be routed into the C++ namespace and one
version cannot be published under another version's name.

This lives in a file rather than inline in the workflow only so it can be
tested. It is not a publication system: it maps a string to two strings.
"""

import argparse
import os
import re
import sys

# Anchored with \Z rather than $ because in Python `$` also matches just before
# a trailing newline -- and these values are written to $GITHUB_OUTPUT as
# key=value lines, where an embedded newline would start a second key.
GRAMMAR = {
    "cpp": re.compile(r"^v([0-9]+\.[0-9]+\.[0-9]+)\Z"),
    "python": re.compile(r"^python-([0-9]+\.[0-9]+\.[0-9]+)\Z"),
}

# What a development build publishes under, for both components.
DEVELOPMENT = "latest"


def resolve(tag):
    """``"v3.4.2"`` -> ``("cpp", "3.4.2")``.

    Only exact final releases are publishable. A pre-release such as
    ``v3.5.0-rc0`` is rejected rather than quietly mapped onto the release it
    precedes, which would put unreleased documentation under a released
    version's URL.
    """
    text = (tag or "").strip()
    for component, pattern in GRAMMAR.items():
        match = pattern.match(text)
        if match:
            return component, match.group(1)

    raise SystemExit(
        f"error: {text!r} is not an exact final release tag.\n"
        "       Expected vMAJOR.MINOR.PATCH or python-MAJOR.MINOR.PATCH.\n"
        "       Pre-release tags are not published to the stable switcher."
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("tag", help="exact final release tag")
    args = parser.parse_args(argv)

    component, version = resolve(args.tag)
    lines = [f"components={component}", f"label={version}"]
    print("\n".join(lines))

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
