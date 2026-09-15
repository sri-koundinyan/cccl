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
    # Maintainer documentation for publishing this site. It lives beside the
    # sources rather than inside them, and belongs in no reader-facing toctree.
    # MyST would otherwise treat each as a document, and a document in no
    # toctree is a warning -- which these builds treat as an error.
    "PUBLISHING.md",
    "publishing-design.md",
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

# Where this site is served from. The switcher manifest is fetched by the
# reader's browser at read time, so these URLs must name the host actually
# serving the page. A fork is a different origin: pages built for production
# would tell the browser to fetch production's manifest, which renders
# perfectly and leaves the version dropdown empty. The workflow derives this
# from the repository, so NVIDIA/cccl gets the production URL unchanged.
_site_root = os.environ.get("CCCL_DOCS_SITE_URL", "https://nvidia.github.io/cccl").rstrip("/")

# Where this component's versions live. C++ and Python are sibling products
# under a neutral root, so each gets its own namespace and its own switcher
# manifest -- the same shape cuda-python uses for cuda-core and cuda-bindings.
# The site root itself is a chooser and claims no version.
_component_root = (
    os.environ.get("CCCL_DOCS_BASE_URL", f"{_site_root}/cpp/").rstrip("/") + "/"
)

# The directory this build is served from, which is also the switcher entry
# that represents it. "latest" is the development branch -- not the newest
# release -- matching cuda-python, whose latest/ is likewise built from main.
# A stable build uses its exact MAJOR.MINOR.PATCH.
_publication_label = os.environ.get("CCCL_DOCS_LABEL", release)

# Sphinx writes html_baseurl into every page as the canonical link. These pages
# are served from <component root>/<label>/, so the label has to be part of it
# -- otherwise every version claims the same canonical URL and the archive
# competes with itself for indexing.
html_baseurl = f"{_component_root}{_publication_label}/"

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
    # A reader landing on latest/ must not mistake development documentation
    # for a release. cuda-python uses the same convention.
    **(
        {
            "announcement": (
                "This is the <strong>development</strong> documentation, built "
                "from the latest commit on <code>main</code>. "
                '<a href="https://nvidia.github.io/cccl/cpp/">Browse released '
                "versions</a>."
            )
        }
        if _publication_label == "latest"
        else {}
    ),
    "switcher": {
        # Deliberately the component root, not html_baseurl: the manifest lists
        # every version, so it cannot live inside one of them.
        "json_url": f"{_component_root}nv-versions.json",
        # Must equal the directory this build is served from: "latest" for a
        # development build, or the exact release for a stable one.
        #
        # cuda-python does not do this -- its latest/ is stamped with the source
        # version (1.2.1.dev72 today), so its switcher can never highlight the
        # entry a reader is actually on. CCCL already passes the publication
        # label to Sphinx, so matching them costs nothing and fixes that.
        "version_match": _publication_label,
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
