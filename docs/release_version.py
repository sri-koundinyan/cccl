#!/usr/bin/env python3
"""Derive the published version directory and label from a checkout.

Usage:
    release_version.py <checkout-dir> [--component cpp|python] [--tip]

Prints two ``key=value`` lines, suitable for appending to ``$GITHUB_OUTPUT``::

    version_dir=3.4
    release_label=3.4.2

The version is taken from **the source tree being published**, never from the
ref name that was requested. That is the property worth having: it makes it
structurally impossible to publish 3.4's documentation into a directory labelled
3.5, however the deploy was triggered. cuda-python does the same thing, reading
the version from the installed package rather than from a workflow input.

``libcudacxx/include/cuda/std/__cccl/version.h`` is the canonical source::

    #define CCCL_VERSION 3004002        ->  3.4.2

The directory keeps only ``MAJOR.MINOR`` because the size budget cannot
accommodate one directory per patch release; the full version travels alongside
as the label the version switcher displays. So a reader browsing ``/cccl/3.4/``
sees "3.4.2" in the dropdown and knows exactly which release they are reading.

The Python package is versioned separately, from its own ``python-*`` tags::

    python-1.1.1                ->  1.1.1

Note that ``python/cuda_cccl/pyproject.toml`` on ``main`` currently derives the
package version from ``v[0-9]*`` -- the *C++* tags -- which is exactly the
entanglement that publishing the two as separate sites exists to undo. The docs
site therefore versions the Python component by Python's own release tags
regardless of what the packaging happens to declare on a given ref.

With ``--tip`` (a build of the development branch) the directory is ``unstable``
and no release label applies.
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

VERSION_HEADER = Path("libcudacxx/include/cuda/std/__cccl/version.h")
VERSION_MD = Path("docs/VERSION.md")

CCCL_VERSION = re.compile(r"^\s*#define\s+CCCL_VERSION\s+([0-9]+)\s*$", re.MULTILINE)

# The Python libraries' own release tags, e.g. "python-1.1.1".
PYTHON_TAG = re.compile(r"^python-([0-9]+)\.([0-9]+)\.([0-9]+)$")
PYTHON_TAG_GLOB = "python-[0-9]*"

TIP_DIRECTORY = "unstable"


def parse_cccl_version(header_text):
    """Turn ``#define CCCL_VERSION 3004002`` into ``(3, 4, 2)``.

    The encoding is the one the header itself documents: major * 1000000 plus
    minor * 1000 plus patch.
    """
    match = CCCL_VERSION.search(header_text)
    if not match:
        raise SystemExit(
            f"error: no CCCL_VERSION define found in {VERSION_HEADER}.\n"
            "       The published version is derived from the source tree, so"
            " this cannot be guessed."
        )

    encoded = int(match.group(1))
    return encoded // 1000000, (encoded // 1000) % 1000, encoded % 1000


def parse_python_tag(tag):
    """Turn ``python-1.1.1`` into ``(1, 1, 1)``."""
    match = PYTHON_TAG.match(tag.strip())
    if not match:
        raise SystemExit(
            f"error: {tag!r} is not a Python release tag (expected python-X.Y.Z).\n"
            "       The Python component is versioned from its own release tags."
        )
    return tuple(int(part) for part in match.groups())


def describe_python_release(checkout):
    """The most recent ``python-*`` tag reachable from this checkout."""
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0", "--match", PYTHON_TAG_GLOB],
            cwd=checkout,
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError:
        raise SystemExit(
            "error: git is not available; cannot determine the Python version"
        )
    except subprocess.CalledProcessError:
        raise SystemExit(
            f"error: no {PYTHON_TAG_GLOB} tag is reachable from {checkout}.\n"
            "       Python documentation is published from a Python release ref,"
            " e.g. python-1.1.1.\n"
            "       Make sure tags were fetched (actions/checkout needs"
            " fetch-depth: 0)."
        )
    return result.stdout.strip()


def derive(checkout, component="cpp", tip=False):
    """Return ``(version_dir, release_label)`` for a checkout."""
    if tip:
        return TIP_DIRECTORY, ""

    if component == "python":
        major, minor, patch = parse_python_tag(describe_python_release(checkout))
        return f"{major}.{minor}", f"{major}.{minor}.{patch}"

    header = checkout / VERSION_HEADER
    if not header.is_file():
        raise SystemExit(f"error: no such file: {header}")

    major, minor, patch = parse_cccl_version(header.read_text(encoding="utf-8"))
    version_dir = f"{major}.{minor}"
    label = f"{major}.{minor}.{patch}"

    # docs/VERSION.md is what conf.py falls back to when SPHINX_CCCL_VER is
    # unset, so a disagreement between the two would mean the pages could be
    # stamped with one version and published under another -- exactly the drift
    # the switcher cannot survive. Cross-checking here is free.
    version_md = checkout / VERSION_MD
    if version_md.is_file():
        declared = version_md.read_text(encoding="utf-8").strip()
        if declared and declared != version_dir:
            raise SystemExit(
                f"error: {VERSION_MD} says {declared!r} but {VERSION_HEADER}"
                f" says {label!r}.\n"
                "       These must agree; the release is internally"
                " inconsistent."
            )

    return version_dir, label


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout", help="root of the checked-out source tree")
    parser.add_argument(
        "--component",
        choices=("cpp", "python"),
        default="cpp",
        help="which component is being published (they version independently)",
    )
    parser.add_argument(
        "--tip",
        action="store_true",
        help="this is a build of the development branch, not a release",
    )
    args = parser.parse_args(argv)

    version_dir, label = derive(
        Path(args.checkout), component=args.component, tip=args.tip
    )

    lines = [f"version_dir={version_dir}", f"release_label={label}"]
    print("\n".join(lines))

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
