# CCCL Documentation Configuration File
# Generated to replace repo-docs with direct Sphinx usage

import os
import sys
from datetime import datetime

# Add extension directory to path
sys.path.insert(0, os.path.abspath("_ext"))

# This configuration builds the C++ component only.
#
# The Python libraries ship on their own release line (cuda-cccl 1.x) and are
# published as their own versioned site under /python/, built by
# docs/gen_python_docs.bash with docs/python_conf/conf.py. Nothing here imports
# a Python package, mocks one, or resolves a Python cross-reference: a C++ build
# must succeed with the Python sources absent from the workspace entirely.

# -- Project information -----------------------------------------------------

project = "CUDA Core Compute Libraries"
copyright = f"{datetime.now().year}, NVIDIA Corporation"
author = "NVIDIA Corporation"

# Version information
_env_version = os.environ.get("SPHINX_CCCL_VER")
if _env_version:
    release = _env_version
else:
    try:
        with open("VERSION.md", "r", encoding="utf-8") as f:
            release = f.read().strip()
    except Exception:
        release = "unstable"

version = release

# -- General configuration ---------------------------------------------------

extensions = [
    # No autodoc/autosummary/napoleon: those exist to document Python modules by
    # importing them, which this component does not do. No intersphinx either --
    # cross-component links are ordinary hyperlinks, so a C++ build never fetches
    # another project's inventory and cannot fail because one is unreachable.
    "sphinx.ext.extlinks",
    "sphinx.ext.mathjax",
    "sphinx.ext.graphviz",
    "sphinx.ext.doctest",
    "myst_parser",  # MyST parser for markdown support
    "breathe",  # For Doxygen integration - has built-in embed:rst support
    # "exhale",  # Disabled - causing build timeouts, API docs handled by breathe
    "sphinx_design",  # For dropdown, card, and other directives
    "sphinx_copybutton",
    "nbsphinx",
    # "rst_processor",  # Disabled - breathe handles embed:rst natively
    "auto_api_generator",  # Automatically generate API reference pages from Doxygen XML
]

# Breathe configuration for Doxygen integration
breathe_projects = {
    "cub": "_build/doxygen/cub/xml",
    "thrust": "_build/doxygen/thrust/xml",
    "libcudacxx": "_build/doxygen/libcudacxx/xml",
    "cudax": "_build/doxygen/cudax/xml",
}

breathe_default_project = "cub"
breathe_default_members = ("members", "undoc-members")
breathe_show_enumvalue_initializer = True
breathe_domain_by_extension = {"cuh": "cpp", "h": "cpp", "hpp": "cpp"}

# Configure cpp domain to handle cub namespace
cpp_index_common_prefix = ["cub::"]
# The NVIDIA theme changes toc_object_entries_show_parents from "domain" to
# "hide" and maximum_signature_line_length from None to 70 before the environment
# is pickled. Set the final values explicitly to avoid invalidating the cache.
toc_object_entries_show_parents = "hide"
maximum_signature_line_length = 70

# Preprocessor definitions for Breathe to handle CCCL macros
cpp_id_attributes = [
    "__device__",
    "__host__",
    "__global__",
    "__forceinline__",
    "_CCCL_HOST_DEVICE",
    "_CCCL_DEVICE",
    "_CCCL_HOST",
    "_CCCL_FORCEINLINE",
    "_CCCL_API",
    "_CCCL_HOST_API",
    "_CCCL_DEVICE_API",
    "_CCCL_NODEBUG_API",
    "_CCCL_NODEBUG_HOST_API",
    "_CCCL_NODEBUG_DEVICE_API",
    "_CCCL_TRIVIAL_API",
    "_CCCL_TRIVIAL_HOST_API",
    "_CCCL_TRIVIAL_DEVICE_API",
]
cpp_paren_attributes = ["__declspec", "__align__"]

# Add support for .rst and .md files
source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

templates_path = ["_templates"]

# Exclude patterns
exclude_patterns = [
    # The Python libraries are a separate versioned product under /python/.
    # Excluding them here is what stops a C++ release publishing Python pages
    # labelled with a C++ version they never shipped under.
    "python",
    "_build",
    "_repo",
    "tools",
    "VERSION.md",
    "Thumbs.db",
    ".DS_Store",
    "env/**",  # Virtual environment
    "**/.pytest_cache",
    "**/__pycache__",
    "*.pyc",
    "*.pyo",
]

# -- Options for HTML output -------------------------------------------------

html_theme = "nvidia_sphinx_theme"

html_logo = "_static/nvidia-logo.png"

# Where this component's versions live, e.g. https://nvidia.github.io/cccl/ .
# The switcher manifest sits here, alongside the version directories.
_component_root = (
    os.environ.get("CCCL_DOCS_BASE_URL", "https://nvidia.github.io/cccl/").rstrip("/")
    + "/"
)

# Sphinx defines html_baseurl as the root of *this* generated documentation and
# writes it into every page as the canonical link. These pages are served from
# <component root>/<version>/, so the version has to be part of it -- otherwise
# every version claims the same canonical URL and the archive competes with
# itself for indexing.
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
        # Deliberately the component root, not html_baseurl: the manifest lists
        # every version, so it cannot live inside one of them.
        "json_url": f"{_component_root}nv-versions.json",
        # Must equal the directory this build is served from ("unstable" or
        # "X.Y"), never the full patch. gen_docs.bash validates that and exports
        # it as SPHINX_CCCL_VER; a disagreement leaves the switcher unable to
        # highlight the current page while every route still returns 200.
        "version_match": release,
    },
}

html_static_path = ["_static"] if os.path.exists("_static") else []

# Images directory
if os.path.exists("img"):
    html_static_path.append("img")

html_js_files = ["deduplicate_toc.js"]

html_title = "CUDA Core Compute Libraries"

# -- Options for extensions --------------------------------------------------

# No intersphinx_mapping: the Python and NumPy inventories exist to resolve
# Python references, and this component has none. Links to the Python
# documentation site are ordinary hyperlinks.

# MyST parser configuration
myst_enable_extensions = [
    "colon_fence",
    "deflist",
    "html_image",
]

# No Napoleon, Autodoc, or mock-import configuration. Those settings govern how
# Python modules are imported and rendered; they moved to docs/python_conf/conf.py
# with the component they serve. Leaving them here would let a Python-only
# dependency break the C++ build.

# External links configuration
extlinks = {
    "github": ("https://github.com/NVIDIA/cccl/blob/main/%s", "%s"),
}


# Exhale not used - API documentation is handled directly through breathe directives

# Suppress specific warning categories that arise from breathe (Doxygen-to-Sphinx
# bridge) limitations.  These cannot be fixed in our source headers or RST files.
#
# See also _BREATHE_SKIP_SYMBOLS in _ext/auto_api_generator.py for symbols that
# are excluded from page generation entirely due to unparsable declarations.
suppress_warnings = [
    # Breathe walks each Doxygen XML file independently.  When a symbol appears
    # in both a namespace XML and a class/group XML (which is normal for Doxygen),
    # breathe emits the C++ declaration twice, triggering a duplicate-declaration
    # warning.  There is no way to control this from our side without patching
    # breathe's XML traversal.
    "cpp.duplicate_declaration",
    # When breathe expands doxygenfunction/doxygenvariable directives, it writes
    # the resolved C++ signature into RST.  Signatures containing default argument
    # values (e.g. ``= {}``) or complex SFINAE expressions produce RST that the
    # docutils parser cannot handle (mismatched inline-literal markers, unexpected
    # braces, etc.).  The source C++ is valid; the issue is that what breathe
    # emits as RST is not valid RST.
    "docutils",
]

copybutton_prompt_text = ">>> |$ |# "


def setup(app):
    if os.path.exists("_static/custom.css"):
        app.add_css_file("custom.css")
