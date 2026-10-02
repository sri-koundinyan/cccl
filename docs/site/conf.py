"""The root documentation project: unversioned, and about the repository.

This is the rapidsai/docs equivalent. RAPIDS builds a Sphinx project at the
root of docs.rapids.ai whose job is to index the products and hold everything
that describes the organisation rather than one release of one library --
installation, contributing, maintainer notes. The versioned per-product
documentation is nested underneath it.

Unversioned is the point. A contributor guide has no 3.5.0 and no 1.2.0; it
describes the repository as it is now. Giving it a version would mean choosing
which product's version it inherits, and there is no right answer. So it is
built once, published at the site root, and carries no switcher.

The product list is not written here. It is read from registry.yml, and the
index page below is generated from it, so adding a product adds a card.
"""

import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import registry

_registry = registry.load()
_site = _registry["site"]

project = _site["title"]
author = "NVIDIA Corporation"
copyright = "2026, NVIDIA Corporation"

# No version, deliberately. The switcher and the version stamp belong to the
# product builds; this project has neither.
version = release = ""

extensions = ["myst_parser"]

# Every link on this page points out of this project, at a product directory
# that exists only once the site is assembled. Without this MyST tries to
# resolve them as documents in this project, does not find them, and warns --
# and these builds treat a warning as an error.
myst_all_links_external = True

html_theme = "nvidia_sphinx_theme"
html_baseurl = os.environ.get("CCCL_DOCS_SITE_URL", _site["base_url"]).rstrip("/") + "/"

html_theme_options = {
    "switcher": None,
    "show_version_warning_banner": False,
    "navbar_align": "left",
}

exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

source_suffix = {".md": "markdown", ".rst": "restructuredtext"}


def _write_index(app, config):
    """Generate index.md from the registry, so the two cannot disagree.

    Sphinx runs this on ``config-inited``, before it reads any source file, so
    the page exists by the time the build looks for it. The same hook point the
    C++ build already uses to generate its API stubs.
    """
    products = registry.products()
    lines = [
        f"# {_site['title']}",
        "",
        _site["summary"].strip(),
        "",
        "## Documentation",
        "",
    ]
    for entry in products:
        # Each product's own landing page redirects to its current version, so
        # the index never names a version and never goes stale when one ships.
        lines += [
            f"### [{entry['name']}]({entry['key']}/)",
            "",
            entry["summary"].strip(),
            "",
        ]

    lines += [
        "```{toctree}",
        ":hidden:",
        "",
        "```",
        "",
    ]

    path = pathlib.Path(app.srcdir) / "index.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  generated index.md from registry.yml: {len(products)} products")


def setup(app):
    app.connect("config-inited", _write_index)
