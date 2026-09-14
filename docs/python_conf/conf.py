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

# docs/_templates carries a custom search.html. It is a sibling of this
# configuration directory rather than inside it, so it needs a real path.
_templates = CONF_DIR.parent / "_templates"
templates_path = [str(_templates)] if _templates.is_dir() else []
exclude_patterns = [
    "_build",
    "Thumbs.db",
    ".DS_Store",
    "**/.pytest_cache",
]

# -- HTML output -------------------------------------------------------------

html_theme = "nvidia_sphinx_theme"
html_title = "CCCL Python Libraries"

# Where this component's versions live, e.g. .../cccl/python/ . The switcher
# manifest sits here, alongside the version directories.
_component_root = (
    os.environ.get(
        "CCCL_DOCS_BASE_URL", "https://nvidia.github.io/cccl/python/"
    ).rstrip("/")
    + "/"
)

# The root of *this* documentation, which is what Sphinx puts in each page's
# canonical link. Pages are served from <component root>/<version>/, so the
# version belongs here; without it every version claims the same canonical URL.
html_baseurl = f"{_component_root}{release}/"

html_theme_options = {
    # Matches docs/conf.py: the GitHub link in the navbar is part of the shared
    # chrome, and its absence here was a visible difference from the combined
    # build rather than a decision.
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
        # every Python version, so it cannot live inside one of them.
        "json_url": f"{_component_root}nv-versions.json",
        "version_match": release,
    },
}

_static = CONF_DIR.parent / "_static"
html_static_path = [str(_static)] if _static.is_dir() else []
# Shared with the C++ build; lives in docs/_static, already on the static path.
html_js_files = ["deduplicate_toc.js"]

_logo = _static / "nvidia-logo.png"
if _logo.is_file():
    html_logo = str(_logo)

# -- Cross-references --------------------------------------------------------

# The STF pages reference C++ labels -- `stf` and `stf-data-place`, both defined
# in docs/cudax/ -- so the C++ inventory is genuinely required. What matters is
# *which* C++ version it comes from.
#
# These docs and the C++ docs move together on main, so the tip must resolve
# against the tip: `stf-data-place` exists on main and not in 3.4, so a build of
# Python unstable against the newest *release* fails. Releases resolve against
# /latest/, which is the closest thing to contemporaneous for a component on its
# own release line.
#
# CI passes a locally built inventory when the C++ docs were built in the same
# job, which is both fresher and free of a network round trip.
#
# Note what is deliberately *not* here: the one hand-written link to the C++ site
# in index.rst is a plain URL, not an intersphinx :doc: reference. Labels are
# explicit and stable across versions; document paths are not -- 3.4 calls that
# page `cpp` while main calls it `cccl/index` -- so a :doc: cross-reference
# breaks on a rename that a label survives.
_cpp_inventory = os.environ.get("CCCL_CPP_OBJECTS_INV") or None
_cpp_base = os.environ.get(
    "CCCL_CPP_DOCS_URL",
    "https://nvidia.github.io/cccl/"
    + ("unstable" if release == "unstable" else "latest")
    + "/",
)

intersphinx_mapping = {
    "python": ("https://docs.python.org/3/", None),
    "numpy": ("https://numpy.org/doc/stable/", None),
    "cccl": (_cpp_base, _cpp_inventory),
}

# -- autodoc -----------------------------------------------------------------

# Copied from docs/conf.py rather than chosen afresh. These decide *which*
# members appear, so a different set silently changes the rendered API -- my
# earlier values dropped __init__ documentation and flipped undoc-members,
# which is a content change disguised as a configuration tidy-up.
autodoc_default_options = {
    "members": True,
    "member-order": "bysource",
    "special-members": "__init__",
    "undoc-members": True,
    "exclude-members": "__weakref__",
}
autosummary_generate = True
autosummary_imported_members = False

# Heavy or CUDA-dependent imports that cannot be satisfied on a docs runner.
# Copied verbatim from docs/conf.py rather than curated: the entries that matter
# most are the least obvious ones. cuda.compute._bindings loads CUDA libraries
# and reads cuda.bindings.__version__ at import time, so leaving it real makes
# every cuda.compute page fail to document.
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
    # numpy is installed as a real dependency (see requirements.txt)
    "numpydoc_test_module",  # Mock to avoid import errors
    "cupy",
    "cuda.compute._bindings",
    "cuda.compute._bindings_impl",
    # STF's public API lives in a compiled Cython extension that is not built
    # at docs time; mock it so the pure-Python helper layers in stf_api.rst
    # (task_graph, interop.numba, interop.pytorch) can still be imported by autodoc.
    "cuda.stf._experimental._stf_bindings",
    "cuda.stf._experimental._stf_bindings_impl",
]

# -- Settings shared with the C++ configuration -------------------------------
#
# Taken verbatim from docs/conf.py. These control how every docstring renders --
# the napoleon_* block especially -- so omitting any of them would make the
# Python pages look different after the split than they do today: a regression
# disguised as a reorganisation.
#
# Note that docs/conf.py also sets `autodoc_type_hints`, which is not a Sphinx
# option; the real name is `autodoc_typehints`. It is a no-op there, so type
# hints render in the signature today. Spelling it correctly here would quietly
# change every signature relative to what is published, so it is left unset.
# Fixing the typo upstream is a separate decision that also moves the C++ pages.

toc_object_entries_show_parents = "hide"

maximum_signature_line_length = 70

source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

myst_enable_extensions = [
    "colon_fence",
    "deflist",
    "html_image",
]

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

autodoc_type_aliases = {
    "Operator": "Operator",
}

primary_domain = "py"

extlinks = {
    "github": ("https://github.com/NVIDIA/cccl/blob/main/%s", "%s"),
}

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

autoclass_content = "class"
