"""Sphinx configuration for the CCCL Python libraries, built as their own site.

The Python packages ship on their own release line -- ``cuda-cccl`` is on 1.x
while the C++ libraries are on CCCL 3.x -- so they are published as a separate
versioned site under ``/python/`` with its own version switcher. Building them
inside the C++ documentation would label Python pages with a C++ version they
never shipped under.

Used as a separate configuration directory, so the release's own sources are
built with this configuration rather than one that has to be present in the ref
being built::

    sphinx-build -c docs/python_conf docs/python <output>

Deliberately does not load ``breathe``, ``exhale`` or ``auto_api_generator``:
those exist to turn Doxygen XML into C++ API pages, and none of them apply here.
Dropping them is why this build takes about two minutes rather than nineteen.
"""

import os
import sys
from datetime import datetime
from pathlib import Path

CONF_DIR = Path(__file__).resolve().parent
REPO_ROOT = CONF_DIR.parent.parent

# Add the Python CCCL packages for autodoc. cuda-cccl and cuda-stf are separate
# distributions that both contribute to the shared ``cuda`` namespace, so both
# have to be importable or the STF pages fail to document anything.
for _pkg in ("python/cuda_cccl", "python/cuda_stf"):
    _path = REPO_ROOT / _pkg
    if _path.is_dir():
        sys.path.insert(0, str(_path))

# -- Project information -----------------------------------------------------

project = "CCCL Python Libraries"
copyright = f"{datetime.now().year}, NVIDIA Corporation"
author = "NVIDIA Corporation"

# The version directory this build is published into. The switcher matches on
# this, so it must equal the directory name -- publish_site.py checks that it
# does rather than trusting it.
release = os.environ.get("SPHINX_CCCL_VER", "unstable")
version = release

# -- General configuration ---------------------------------------------------

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.intersphinx",
    "sphinx.ext.napoleon",
    "sphinx.ext.mathjax",
    "myst_parser",
    "sphinx_design",
    "sphinx_copybutton",
]

templates_path = []
exclude_patterns = [
    "_build",
    "Thumbs.db",
    ".DS_Store",
    "**/.pytest_cache",
]

# -- HTML output -------------------------------------------------------------

html_theme = "nvidia_sphinx_theme"
html_title = "CCCL Python Libraries"

# The Python component lives under /python/, so the deploy passes that as the
# base URL. Everything the switcher needs hangs off it.
html_baseurl = (
    os.environ.get(
        "CCCL_DOCS_BASE_URL", "https://nvidia.github.io/cccl/python/"
    ).rstrip("/")
    + "/"
)

html_theme_options = {
    "navigation_depth": 4,
    "show_toc_level": 2,
    "navbar_start": ["navbar-logo"],
    "navbar_end": ["theme-switcher", "navbar-icon-links"],
    "footer_start": ["copyright"],
    "footer_end": ["sphinx-version"],
    "sidebar_includehidden": True,
    "collapse_navigation": False,
    "switcher": {
        # This component's own manifest, listing only Python releases.
        "json_url": f"{html_baseurl}nv-versions.json",
        "version_match": release,
    },
}

_static = CONF_DIR.parent / "_static"
html_static_path = [str(_static)] if _static.is_dir() else []
_logo = _static / "nvidia-logo.png"
if _logo.is_file():
    html_logo = str(_logo)

# -- Cross-references into the C++ documentation -----------------------------

# The Python docs point at C++ pages in a few places, and the docstrings carry
# :ref:s into C++ labels. Now that the two are separate sites those cannot
# resolve locally, so they resolve through the C++ inventory instead -- which
# means no docstring has to be edited to accommodate the split.
#
# CI points this at the C++ objects.inv it just built, so the reference is to
# the matching version and the build does not depend on the network. Falls back
# to the published site for local builds.
_cpp_inventory = os.environ.get("CCCL_CPP_OBJECTS_INV") or None
_cpp_base = os.environ.get("CCCL_CPP_DOCS_URL", "https://nvidia.github.io/cccl/latest/")

intersphinx_mapping = {
    "python": ("https://docs.python.org/3/", None),
    "numpy": ("https://numpy.org/doc/stable/", None),
    "cccl": (_cpp_base, _cpp_inventory),
}

# A missing C++ inventory should not fail the build: the Python docs are still
# correct and useful, the cross-links just degrade to plain text.
intersphinx_disabled_reftypes = []
nitpicky = False

# -- autodoc -----------------------------------------------------------------

autodoc_default_options = {
    "members": True,
    "undoc-members": False,
    "show-inheritance": True,
}
autodoc_typehints = "description"
autosummary_generate = True
autosummary_imported_members = False

# Heavy or CUDA-dependent imports that cannot be satisfied on a docs runner.
# Kept in step with docs/conf.py; anything importable at build time should be
# removed from here so its signatures are documented properly.
autodoc_mock_imports = [
    # cuda.coop's type machinery builds LLVM IR at import time. llvmlite comes
    # in with numba, which is mocked here, so it has to be mocked too --
    # otherwise every module that imports from cuda.coop._experimental._types
    # fails to import and autodoc documents nothing.
    "llvmlite",
    "llvmlite.binding",
    "llvmlite.ir",
    "numba",
    "numba.core",
    "numba.core.cgutils",
    "numba.core.extending",
    "numba.core.typing",
    "numba.core.typing.ctypes_utils",
    "numba.core.typing.templates",
    "numba.cuda",
    "numba.cuda.cudadecl",
    "numba.cuda.dispatcher",
    "numba.extending",
    "numba.types",
    "cuda.bindings",
    "cuda.bindings.driver",
    "cuda.bindings.runtime",
    "cuda.core",
    "cuda.core.experimental",
    "cuda.core.experimental._utils",
    "cuda.core.experimental._utils.cuda_utils",
    "cuda.pathfinder",
]

napoleon_google_docstring = True
napoleon_numpy_docstring = True
