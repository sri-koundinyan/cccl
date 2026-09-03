#!/usr/bin/env python3
"""Remove the Python documentation from a release's C++ documentation build.

The Python libraries ship on their own release line and are published as their
own site. Releases tagged before that change still carry ``python/index`` in
their top-level toctree, so rebuilding one produces a C++ site with a "CCCL
Python Libraries" section and pages at ``/<version>/python/`` -- Python
documentation labelled with a C++ version number, which is the thing the split
exists to stop.

Rather than rebuild history, this patches the release's own docs configuration
before Sphinx runs:

* drops ``python/index`` from the top-level toctree and the link beside it
* excludes ``python`` from the build, so its pages do not then warn about being
  outside any toctree, which would fail a build that treats warnings as errors

Does nothing if the release already keeps them separate, so it is safe to run
against any release.

Usage:
    unbundle_python_docs.py --docs-dir PATH
"""

import argparse
import os
import re
import sys
from pathlib import Path


def patch_index(index_rst):
    """Drop the Python entries from the top-level toctree and link list."""
    text = index_rst.read_text(encoding="utf-8")
    original = text

    # The toctree entry, on its own indented line.
    text = re.sub(r"^[ \t]*python/index[ \t]*\n", "", text, flags=re.MULTILINE)

    # The bullet pointing at it, which may wrap onto continuation lines.
    text = re.sub(
        r"^- :doc:`[^`]*<python/index>`[ \t]*\n(?:[ \t]+\S[^\n]*\n)?(?:[ \t]*\n)?",
        "",
        text,
        flags=re.MULTILINE,
    )

    if text == original:
        return False

    # Leave a way across, so the C++ docs still point at their counterpart.
    text = text.rstrip("\n") + (
        "\n\nThe Python libraries ship on their own release line and are\n"
        "documented separately:\n\n"
        "- `CCCL Python Libraries <../python/>`_\n"
    )
    index_rst.write_text(text, encoding="utf-8")
    return True


def patch_conf(conf_py):
    """Exclude the python directory from this build."""
    text = conf_py.read_text(encoding="utf-8")
    if re.search(r"""^\s*["']python["'],""", text, flags=re.MULTILINE):
        return False

    marker = "exclude_patterns = ["
    if marker not in text:
        raise SystemExit(f"error: {conf_py} has no exclude_patterns to extend")

    text = text.replace(
        marker,
        marker
        + '\n    # Built separately; the Python libraries version independently.\n    "python",',
        1,
    )
    conf_py.write_text(text, encoding="utf-8")
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docs-dir", required=True, help="the release's docs/ dir")
    args = parser.parse_args(argv)

    docs_dir = Path(args.docs_dir)
    index_rst = docs_dir / "index.rst"
    conf_py = docs_dir / "conf.py"

    for path in (index_rst, conf_py):
        if not path.is_file():
            raise SystemExit(f"error: no such file: {path}")

    changed = patch_index(index_rst)
    changed |= patch_conf(conf_py)

    if changed:
        print(f"  removed the Python documentation from {docs_dir}")
    else:
        print(f"  {docs_dir} already keeps the Python documentation separate")

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as f:
            f.write(f"unbundled={'true' if changed else 'false'}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
