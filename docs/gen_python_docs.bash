#!/usr/bin/env bash

# Build the Python documentation on its own.
#
# Usage:
#   ./gen_python_docs.bash
#
# Environment:
#   SPHINX_CCCL_VER            Version directory to publish as, e.g. "1.1".
#                              Defaults to "unstable".
#   CCCL_DOCS_BASE_URL         Public base URL of the Python subtree, e.g.
#                              https://nvidia.github.io/cccl/python/
#   CCCL_PYTHON_DOCS_SOURCE    The docs/python directory to build. Defaults to
#                              the one beside this script; a release backfill
#                              points it at another checkout.
#
# The Python libraries ship on their own release line, so their documentation is
# built separately from the C++ docs and published under its own version tree.
#
# Nothing under docs/python documents C++, so this needs no Doxygen, Breathe or
# Exhale -- which is why it takes a couple of minutes rather than the twenty the
# full documentation build takes.

set -euo pipefail

SCRIPT_PATH=$(cd "$(dirname "${0}")"; pwd -P)
cd "${SCRIPT_PATH}"

VERSION="${SPHINX_CCCL_VER:-unstable}"
# Export it so conf.py resolves `release` from the same value used for the
# output directory; a mismatch leaves the switcher unable to highlight the
# version the reader is on.
export SPHINX_CCCL_VER="${VERSION}"

SOURCE_DIR="${CCCL_PYTHON_DOCS_SOURCE:-${SCRIPT_PATH}/python}"
export CCCL_PYTHON_DOCS_SOURCE="${SOURCE_DIR}"

BASE_URL="${CCCL_DOCS_BASE_URL:-https://nvidia.github.io/cccl/python/}"
BASE_URL="${BASE_URL%/}/"
export CCCL_DOCS_BASE_URL="${BASE_URL}"

BUILDDIR="_build/python"
OUT_DIR="${BUILDDIR}/html/${VERSION}"

if [[ ! -f "${SOURCE_DIR}/index.rst" ]]; then
    echo "Error: no Python docs at ${SOURCE_DIR} (expected index.rst)" >&2
    exit 1
fi

# Reuse the documentation virtualenv the C++ build creates, so both share one
# set of pinned Sphinx dependencies.
if [[ -d "env" ]]; then
    # shellcheck disable=SC1091
    source env/bin/activate
else
    echo "Creating virtual environment..."
    python3 -m venv env
    # shellcheck disable=SC1091
    source env/bin/activate
fi

if ! python -c "import sphinx" 2>/dev/null; then
    echo "Installing documentation dependencies..."
    python3 -m pip install -r requirements.txt
fi

declare -a SPHINXOPTS="(${SPHINXOPTS:---keep-going -W})"

echo "Building Python documentation ${VERSION} from ${SOURCE_DIR}"
rm -rf "${OUT_DIR}"
mkdir -p "${OUT_DIR}"

python -m sphinx.cmd.build \
    -b html \
    -c "${SCRIPT_PATH}/python_conf" \
    -d "${BUILDDIR}/doctrees" \
    -j auto \
    "${SOURCE_DIR}" \
    "${OUT_DIR}" \
    "${SPHINXOPTS[@]}"

# The 404 handler searches this to suggest the closest page when one is missing.
./scrape_docs.bash "${OUT_DIR}"

# The helper that does that searching lives inside each version's tree, so it
# has to be built into this one too.
if [[ -f "${SCRIPT_PATH}/404_helper.inc.html" ]]; then
    {
        echo "<!DOCTYPE html>"
        echo "<html lang=\"en\"><head><title>404</title></head><body>"
        cat "${SCRIPT_PATH}/404_helper.inc.html"
        echo "</body></html>"
    } > "${OUT_DIR}/404_helper.html"
fi

echo "Python documentation built into ${OUT_DIR}"
