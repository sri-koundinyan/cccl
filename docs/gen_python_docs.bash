#!/usr/bin/env bash

# Build the CCCL Python documentation as its own site.
#
# Usage:
#   ./gen_python_docs.bash                     - Build
#   ./gen_python_docs.bash --allow-dep-install - Build, installing missing deps
#   ./gen_python_docs.bash clean               - Clean the build directory
#
# The Python libraries ship on their own release line (cuda-cccl 1.x, against
# CCCL 3.x for C++), so they are published as a separate versioned site under
# /python/ with its own version switcher.
#
# No Doxygen, no breathe, no generated C++ API pages -- see docs/python_conf/conf.py.
# That is the whole reason this exists as its own script: the build takes about
# two minutes instead of nineteen.
#
# Output mirrors gen_docs.bash: _build/python-html/<version>/, so the deploy
# workflow handles both components identically.

set -euo pipefail

ALLOW_DEP_INSTALL=false
CLEAN=false

for arg in "$@"; do
    case "$arg" in
        --allow-dep-install) ALLOW_DEP_INSTALL=true ;;
        clean)               CLEAN=true ;;
        *)                   echo "Unknown argument: $arg"; exit 1 ;;
    esac
done

SCRIPT_PATH=$(cd "$(dirname "${0}")"; pwd -P)
cd "$SCRIPT_PATH"

BUILDDIR="_build"
HTML_DIR="${BUILDDIR}/python-html"

if [[ "$CLEAN" = true ]]; then
    echo "Cleaning Python docs build directory..."
    rm -rf "${HTML_DIR:?}" "${BUILDDIR}/python-doctrees"
    exit 0
fi

# The directory this build is published into, and what conf.py stamps into the
# pages so the version switcher can highlight the reader's current version.
VERSION="${SPHINX_CCCL_VER:-unstable}"
export SPHINX_CCCL_VER="${VERSION}"

# The Python component lives under /python/ on the site.
BASE_URL="${CCCL_DOCS_BASE_URL:-https://nvidia.github.io/cccl/python/}"
BASE_URL="${BASE_URL%/}/"
export CCCL_DOCS_BASE_URL="${BASE_URL}"

VERSIONED_HTML_DIR="${HTML_DIR}/${VERSION}"

# Shared with gen_docs.bash so a developer who has built the C++ docs does not
# pay for a second environment.
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

# Cross-references into the C++ documentation resolve through its inventory
# rather than locally, so no docstring has to change for the split. Prefer a
# locally built objects.inv when there is one: it matches the version being
# published and keeps the build off the network.
if [[ -z "${CCCL_CPP_OBJECTS_INV:-}" && -f "${BUILDDIR}/html/${VERSION}/objects.inv" ]]; then
    export CCCL_CPP_OBJECTS_INV="${SCRIPT_PATH}/${BUILDDIR}/html/${VERSION}/objects.inv"
    echo "Resolving C++ cross-references against the local ${VERSION} inventory"
fi

echo "Building Python documentation (version: ${VERSION})..."
rm -rf "${VERSIONED_HTML_DIR}"
mkdir -p "${VERSIONED_HTML_DIR}"

SPHINXOPTS=(-W --keep-going -j auto)
if [[ -n "${CCCL_DOCS_SPHINXOPTS:-}" ]]; then
    read -r -a SPHINXOPTS <<< "${CCCL_DOCS_SPHINXOPTS}"
fi

# -c selects the configuration directory, so a release's own sources are built
# with this configuration even though the release predates it.
python -m sphinx.cmd.build \
    -b html \
    -c "${SCRIPT_PATH}/python_conf" \
    -d "${BUILDDIR}/python-doctrees" \
    "${SCRIPT_PATH}/python" \
    "${VERSIONED_HTML_DIR}" \
    "${SPHINXOPTS[@]}"

# The page list the 404 handler searches when a URL in this component misses.
./scrape_docs.bash "${VERSIONED_HTML_DIR}"

echo "Python documentation build complete: ${HTML_DIR}/"
