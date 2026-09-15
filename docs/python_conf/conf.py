# Sphinx configuration for the CCCL Python documentation.
#
# The Python libraries ship on their own release line (cuda-cccl 1.x) while the
# C++ libraries are on 3.x, so they are published as two independent products:
# C++ at /cccl/<version>/ and Python at /cccl/python/<version>/. This file
# configures the Python component only.
#
# It lives in its own directory rather than beside the sources because Sphinx's
# ``-c`` flag selects a configuration directory separate from the source
# directory. That is what lets a historical release be built with current
# configuration even though the release predates it:
#
#     sphinx-build -b html -c docs/python_conf docs/python <out>
#
# Deliberately absent, and required to stay absent:
#
#   * breathe, Doxygen, and auto_api_generator -- there are no C++ headers here,
#     which is why this build takes about three minutes rather than fifteen;
#   * any intersphinx mapping onto the C++ inventory. Cross-component links are
#     ordinary hyperlinks, so a broken or unpublished C++ inventory can never
#     fail this build. That trades automatic symbol resolution for a release
#     boundary that does not depend on another component being published first.

import os
import sys
from datetime import datetime

# cuda-cccl and cuda-stf are separate distributions that both contribute to the
# shared ``cuda`` namespace; Autodoc imports from whichever are present.
for _pkg in ("../../python/cuda_cccl", "../../python/cuda_stf"):
    _path = os.path.abspath(os.path.join(os.path.dirname(__file__), _pkg))
    if os.path.exists(_path):
        sys.path.insert(0, _path)

# -- Project information -----------------------------------------------------

project = "CCCL Python Libraries"  # cuda-cccl 1.1
copyright = f"{datetime.now().year}, NVIDIA Corporation"
author = "NVIDIA Corporation"

# The directory this build will be served from: "unstable" or "X.Y", never a
# full patch such as 1.1.1. gen_python_docs.bash validates the value and exports
# it; falling back to "unstable" keeps a bare local build coherent.
release = os.environ.get("SPHINX_CCCL_VER", "unstable")
version = release

# -- General configuration ---------------------------------------------------

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",
    "sphinx.ext.extlinks",
    "sphinx.ext.mathjax",
    "myst_parser",
    "sphinx_design",
    "sphinx_copybutton",
]

source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

# Shared with the C++ build: search.html and other theme overrides.
templates_path = [os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "_templates"))]

exclude_patterns = [
    "_build",
    "Thumbs.db",
    ".DS_Store",
    "**/.pytest_cache",
    "**/__pycache__",
    "*.pyc",
    "*.pyo",
]

# -- Options for HTML output -------------------------------------------------

html_theme = "nvidia_sphinx_theme"

_static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "_static"))
html_static_path = [_static_dir] if os.path.exists(_static_dir) else []

_logo = os.path.join(_static_dir, "nvidia-logo.png")
if os.path.exists(_logo):
    html_logo = _logo

html_title = "CCCL Python Libraries"

# Where this component's versions live. Note the /python/ segment: this is a
# separate namespace from the C++ component at the site root, with its own
# switcher manifest and its own version list.
_component_root = (
    os.environ.get(
        "CCCL_DOCS_BASE_URL", "https://nvidia.github.io/cccl/python/"
    ).rstrip("/")
    + "/"
)

# Canonical URL of this build. The version is part of it because these pages are
# served from <component root>/<version>/; without it every version would claim
# the same canonical address.
html_baseurl = f"{_component_root}{release}/"

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
        # The component root, not html_baseurl: the manifest lists every version,
        # so it cannot live inside one of them. This is the Python manifest --
        # it never lists a C++ version.
        "json_url": f"{_component_root}nv-versions.json",
        # Must equal the directory this build is served from.
        "version_match": release,
    },
}

# -- Options for extensions --------------------------------------------------

myst_enable_extensions = [
    "colon_fence",
    "deflist",
    "html_image",
]

# Napoleon settings, carried over unchanged from the combined configuration so
# that docstrings render exactly as they did before the split.
napoleon_google_docstring = True
napoleon_numpy_docstring = True
napoleon_include_init_with_doc = False
napoleon_include_private_with_doc = False
napoleon_include_special_with_doc = True
napoleon_use_admonition_for_examples = False
napoleon_use_admonition_for_notes = False
napoleon_use_admonition_for_references = False
napoleon_use_ivar = False
napoleon_use_param = True
napoleon_use_rtype = True
napoleon_preprocess_types = False
napoleon_type_aliases = None

# Autodoc settings, likewise carried over unchanged. Dropping any of these
# quietly changes which members appear on an API page.
autodoc_default_options = {
    "members": True,
    "member-order": "bysource",
    "special-members": "__init__",
    "undoc-members": True,
    "exclude-members": "__weakref__",
}

autodoc_type_hints = "description"
autodoc_type_aliases = {
    "Operator": "Operator",
}

primary_domain = "py"

# This list is the python-1.1.1 tag's own, plus llvmlite.binding.
#
# It deliberately does NOT come from main. This release documents cuda.coop
# and has no STF; main is the reverse. Importing main's assumptions here
# could produce a clean build that silently omits the cooperative API this
# release actually shipped.
#
# llvmlite.binding is required because the cooperative type machinery imports
# LLVM support while Autodoc loads the module. cuda.coop itself is absent on
# purpose: a mock stands in for an unavailable dependency, never for the API
# being documented -- mocking it renders an empty page and still exits zero.
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
    "llvmlite.binding",
    "llvmlite.ir",
    "numpydoc_test_module",
    "cupy",
    "cuda.compute._bindings",
    "cuda.compute._bindings_impl",
]

autosummary_imported_members = False
autosummary_generate = True
autoclass_content = "class"

extlinks = {
    "github": ("https://github.com/NVIDIA/cccl/blob/main/%s", "%s"),
}

copybutton_prompt_text = ">>> |$ |# "


def setup(app):
    custom_css = os.path.join(_static_dir, "custom.css")
    if os.path.exists(custom_css):
        app.add_css_file("custom.css")
