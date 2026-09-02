#!/usr/bin/env python3
"""Add version-switcher configuration to a release that predates it.

The switcher was configured in ``docs/conf.py`` from 3.4 onwards. Releases
before that render with no version dropdown at all, so a reader who arrives on
one of those pages from a search result has no way to discover that newer
documentation exists, and no way to navigate out of that version.

Rather than rewrite the generated HTML, this appends the missing configuration
to the release's own ``conf.py`` before Sphinx runs, so the pages are generated
with a switcher the normal way. Everything else those releases already have --
the same theme, the same navbar layout, a ``release`` string read from
VERSION.md -- so only the switcher block itself is missing.

Does nothing if the file already configures a switcher, so it is safe to run
against any release.

Usage:
    backport_switcher_config.py --conf-py PATH
"""

import argparse
import sys
from pathlib import Path

SNIPPET = """

# --- appended by the CCCL docs deploy -----------------------------------------
# This release predates the version switcher. Without this block its pages
# render with no version dropdown, leaving a reader who lands here unable to
# reach any other version. See docs/backport_switcher_config.py.
import os as _cccl_os  # noqa: E402

_cccl_base_url = (
    _cccl_os.environ.get("CCCL_DOCS_BASE_URL", "https://nvidia.github.io/cccl/").rstrip(
        "/"
    )
    + "/"
)

html_baseurl = _cccl_base_url

# version_match must equal the directory this version is published under, or the
# switcher cannot highlight it. The deploy sets SPHINX_CCCL_VER to that
# directory; `release` is the release's own idea of its version, used as a
# fallback for local builds.
html_theme_options["switcher"] = {
    "json_url": f"{_cccl_base_url}nv-versions.json",
    "version_match": _cccl_os.environ.get("SPHINX_CCCL_VER", release),  # noqa: F821
}
# --- end appended block -------------------------------------------------------
"""


def needs_backport(text):
    """True when the config has no switcher and could accept one."""
    return '"switcher"' not in text and "'switcher'" not in text


def backport(conf_py):
    path = Path(conf_py)
    if not path.is_file():
        raise SystemExit(f"error: no such file: {path}")

    text = path.read_text(encoding="utf-8")

    if not needs_backport(text):
        return False

    # The snippet mutates html_theme_options, so the release must define it.
    # Every release that uses the NVIDIA theme does; bail loudly if not.
    if "html_theme_options" not in text:
        raise SystemExit(
            f"error: {path} does not define html_theme_options; cannot add a "
            f"switcher to it."
        )

    path.write_text(text + SNIPPET, encoding="utf-8")
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--conf-py", required=True, help="the release's docs/conf.py")
    args = parser.parse_args(argv)

    if backport(args.conf_py):
        print(f"  added version-switcher configuration to {args.conf_py}")
    else:
        print(f"  {args.conf_py} already configures a switcher; left alone")
    return 0


if __name__ == "__main__":
    sys.exit(main())
