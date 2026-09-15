#!/usr/bin/env bash

# Build the CCCL Python documentation as a standalone component.
#
# Usage:
#   ./gen_python_docs.bash                        - Build into _build/python-html/1.1.1
#   ./gen_python_docs.bash --version-dir 1.1.1    - The same, stated explicitly
#   ./gen_python_docs.bash --allow-dep-install    - Build, installing missing deps
#   ./gen_python_docs.bash clean                  - Remove the Python build output
#
# The Python libraries ship on their own release line and are published as their
# own versioned site under /cccl/python/. This script produces that component's
# artifact and nothing else -- no Doxygen, no site assembly, no C++ inventory.
#
# Output mirrors gen_docs.bash: _build/python-html/<version>/, so the publisher
# can treat the two components identically.

set -euo pipefail

ALLOW_DEP_INSTALL=false
CLEAN=false
VERSION_DIR=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --allow-dep-install) ALLOW_DEP_INSTALL=true ;;
        clean)               CLEAN=true ;;
        --version-dir)       VERSION_DIR="${2:-}"; shift ;;
        --version-dir=*)     VERSION_DIR="${1#*=}" ;;
        *)                   echo "Unknown argument: $1"; exit 1 ;;
    esac
    shift
done

SCRIPT_PATH=$(cd "$(dirname "${0}")"; pwd -P)
cd "$SCRIPT_PATH"

BUILDDIR="_build"
HTML_DIR="${BUILDDIR}/python-html"

# This branch exists to rebuild one already-released version, python-1.1.1,
# into the component layout that did not exist when it was tagged. The default
# is the exact release so the branch reproduces its one artifact on its own.
#
# Every release gets its own exact directory and no rolling MAJOR.MINOR
# directory is created, so 1.1.1 is the label -- the inverse of the earlier
# rule this script was written under, which rejected patch releases outright.
VERSION="${VERSION_DIR:-${SPHINX_CCCL_VER:-1.1.1}}"

if [[ ! "${VERSION}" =~ ^(latest|[0-9]+\.[0-9]+\.[0-9]+)$ ]]; then
    echo "Error: version directory must be 'latest' or MAJOR.MINOR.PATCH," >&2
    echo "       got '${VERSION}'. Each release is served from its own exact" >&2
    echo "       version directory; there is no rolling MAJOR.MINOR alias." >&2
    exit 1
fi

export SPHINX_CCCL_VER="${VERSION}"

VERSIONED_HTML_DIR="${HTML_DIR}/${VERSION}"

if [[ "${CLEAN}" = true ]]; then
    echo "Removing ${HTML_DIR}..."
    rm -rf "${HTML_DIR:?}" "${BUILDDIR}/python-doctrees"
    exit 0
fi

if [[ -d "env" ]]; then
    # shellcheck disable=SC1091
    source env/bin/activate
elif [[ "${ALLOW_DEP_INSTALL}" = true ]]; then
    echo "Creating virtual environment..."
    python3 -m venv env
    # shellcheck disable=SC1091
    source env/bin/activate
else
    echo "Error: no virtual environment in ${SCRIPT_PATH}/env" >&2
    echo "       Re-run with --allow-dep-install, or create it yourself." >&2
    exit 1
fi

if ! python -c "import sphinx" 2>/dev/null; then
    if [[ "${ALLOW_DEP_INSTALL}" != true ]]; then
        echo "Error: documentation dependencies are not installed." >&2
        echo "       Re-run with --allow-dep-install, or: pip install -r requirements.txt" >&2
        exit 1
    fi
    echo "Installing documentation dependencies..."
    python3 -m pip install -r requirements.txt
fi

echo "Building Python documentation (version: ${VERSION})..."
rm -rf "${VERSIONED_HTML_DIR}"
mkdir -p "${VERSIONED_HTML_DIR}"

# Warnings are errors. That is what turns a docstring whose cross-reference no
# longer resolves into a build failure here rather than a dead link for a reader.
SPHINXOPTS=(-W --keep-going -j auto)
if [[ -n "${CCCL_DOCS_SPHINXOPTS:-}" ]]; then
    read -r -a SPHINXOPTS <<< "${CCCL_DOCS_SPHINXOPTS}"
fi

# -c selects the configuration directory separately from the source directory,
# so a release's own sources can be built with configuration that postdates it.
python -m sphinx.cmd.build \
    -b html \
    -c "${SCRIPT_PATH}/python_conf" \
    -d "${BUILDDIR}/python-doctrees" \
    "${SCRIPT_PATH}/python" \
    "${VERSIONED_HTML_DIR}" \
    "${SPHINXOPTS[@]}"

# A zero exit status is not by itself evidence that the API was documented:
# Autodoc can warn about an import and still emit a page with no members. The
# inventory is the thing that proves otherwise.
if [[ ! -f "${VERSIONED_HTML_DIR}/objects.inv" ]]; then
    echo "Error: the build produced no objects.inv." >&2
    echo "       Sphinx records every documented target there, so its absence" >&2
    echo "       means this artifact documents nothing." >&2
    exit 1
fi

# Like the C++ build, this produces one component artifact. The switcher
# manifest, inventory alias, landing page and 404 handler describe the site as a
# whole and are written by docs/publish_site.py from the complete published tree.

echo "Python documentation build complete: ${VERSIONED_HTML_DIR}"
