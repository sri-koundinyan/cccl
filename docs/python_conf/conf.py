# Sphinx configuration for the Python documentation, built on its own.
#
# The Python libraries ship on a different release line from the C++ ones, so
# their docs are a separate site with their own version switcher rather than a
# subtree of a CCCL release. This config is used with Sphinx's -c flag against
# docs/python as the source directory:
#
#     sphinx-build -c docs/python_conf docs/python <out>
#
# Deliberately lighter than the top-level docs/conf.py: no Doxygen, Breathe or
# Exhale, because nothing under docs/python documents C++. That makes this build
# a couple of minutes rather than the twenty the full docs take.

import os
import sys
from datetime import datetime, timezone

# The source tree this is documenting. For a release backfill that is a
# different checkout from the one holding this config, so it is passed in
# rather than assumed to be alongside.
_source_dir = os.environ.get(
    "CCCL_PYTHON_DOCS_SOURCE",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "python")),
)
_repo_root = os.path.abspath(os.path.join(_source_dir, "..", ".."))

# autodoc imports the package, so it has to be importable. The heavy CUDA
# dependencies are mocked below instead of installed.
sys.path.insert(0, os.path.join(_repo_root, "python", "cuda_cccl"))

# -- Project information -----------------------------------------------------

project = "CCCL Python Libraries"
copyright = f"{datetime.now(tz=timezone.utc).year}, NVIDIA Corporation"
author = "NVIDIA Corporation"

# The version this is published as. Set by the deploy to the directory the docs
# will live under, so that the switcher can highlight the version being read.
release = os.environ.get("SPHINX_CCCL_VER", "unstable")
version = release

# -- General configuration ---------------------------------------------------

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.intersphinx",
    "sphinx.ext.napoleon",
    "sphinx.ext.extlinks",
    "sphinx.ext.mathjax",
    "myst_parser",
    "sphinx_design",
    "sphinx_copybutton",
]

source_suffix = {".rst": "restructuredtext", ".md": "markdown"}

exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# -- HTML output -------------------------------------------------------------

html_theme = "nvidia_sphinx_theme"

# Addresses this component's own subtree, so its switcher reads the Python
# version list rather than the C++ one at the site root.
html_baseurl = (
    os.environ.get("CCCL_DOCS_BASE_URL", "https://nvidia.github.io/cccl/python/").rstrip(
        "/"
    )
    + "/"
)

html_theme_options = {
    "icon_links": [
        {
            "name": "GitHub",
            "url": "https://github.com/NVIDIA/cccl",
            "icon": "fa-brands fa-github",
            "type": "fontawesome",
        }
    ],
    "navigation_depth": 4,
    "show_toc_level": 2,
    "navbar_start": ["navbar-logo"],
    "navbar_end": ["theme-switcher", "navbar-icon-links"],
    "footer_start": ["copyright"],
    "footer_end": ["sphinx-version"],
    "sidebar_includehidden": True,
    "collapse_navigation": False,
    "switcher": {
        "json_url": f"{html_baseurl}nv-versions.json",
        "version_match": release,
    },
}

html_title = "CCCL Python Libraries"

# -- Extension configuration -------------------------------------------------

# Some Python docstrings cross-reference labels defined in the C++ documentation
# (e.g. CUB's "flexible data arrangement"). Those resolved for free while both
# were one Sphinx project; now that they are separate sites, intersphinx is what
# keeps them working. Sphinx resolves a plain :ref: through intersphinx when the
# label is not defined locally, so the docstrings need no changes.
#
# CCCL_CPP_DOCS_INVENTORY may point at a local objects.inv when the C++ docs are
# being built in the same job; otherwise the published one is fetched. If it is
# unavailable the build still succeeds, with those references left as plain text.
_cpp_docs = os.environ.get(
    "CCCL_CPP_DOCS_URL", html_baseurl.rstrip("/").rsplit("/", 1)[0] + "/"
)
_cpp_inventory = os.environ.get("CCCL_CPP_DOCS_INVENTORY") or None

intersphinx_mapping = {
    "python": ("https://docs.python.org/3/", None),
    "numpy": ("https://numpy.org/doc/stable/", None),
    "cccl-cpp": (_cpp_docs, _cpp_inventory),
}

autodoc_default_options = {
    "members": True,
    "member-order": "bysource",
    "special-members": "__init__",
    "undoc-members": True,
    "exclude-members": "__weakref__",
}
autodoc_type_hints = "description"
primary_domain = "py"

# The CUDA and JIT dependencies are not installed at docs time. Mocking them
# lets autodoc import the pure-Python layers and read their docstrings, which is
# all the API pages need.
autodoc_mock_imports = [
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
    "llvmlite",
    "llvmlite.ir",
    "cupy",
    "cuda.compute._bindings",
    "cuda.compute._bindings_impl",
    "cuda.coop._experimental._bindings",
    # STF's public API is a compiled Cython extension that is not built at docs
    # time; mock it so the pure-Python helper layers can still be imported.
    "cuda.stf._experimental._stf_bindings",
    "cuda.stf._experimental._stf_bindings_impl",
]

extlinks = {
    "github": ("https://github.com/NVIDIA/cccl/blob/main/%s", "%s"),
}
