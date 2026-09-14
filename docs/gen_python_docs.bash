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


# The STF pages cross-reference C++ labels, so this build needs the C++
# inventory -- an objects.inv, Sphinx's index of every target a project exports.
#
# THE POLICY, stated rather than implied: the Python documentation references
# the newest *published* stable C++ documentation, not the C++ revision sitting
# in this checkout. Those differ -- the python-1.1.1 tree carries C++ 3.5.0
# while the newest C++ release is 3.4.2 -- and referencing the checkout would
# point readers at pages that are not published anywhere. The consequence to
# accept is that a C++ label removed in a later release breaks this build; -W
# turns that into a failure here rather than a dead link for a reader.
#
# When the C++ docs were built in the same job, prefer that inventory: it is
# contemporaneous and needs no network.
if [[ -z "${CCCL_CPP_OBJECTS_INV:-}" && -f "${BUILDDIR}/html/${VERSION}/objects.inv" ]]; then
    export CCCL_CPP_OBJECTS_INV="${SCRIPT_PATH}/${BUILDDIR}/html/${VERSION}/objects.inv"
    echo "Resolving C++ cross-references against the locally built ${VERSION} inventory"
fi

# Otherwise it is fetched over the network, which encodes an ordering that
# nothing else enforces: the C++ docs must already be published. Check it here,
# because the alternative is a Sphinx run that fails several minutes later with
# a list of unresolved references and no indication that the cause is a deploy
# that has not happened yet.
if [[ -z "${CCCL_CPP_OBJECTS_INV:-}" ]]; then
    CPP_BASE="${CCCL_CPP_DOCS_URL:-}"
    if [[ -n "${CPP_BASE}" ]]; then
        if ! curl -sSfL --max-time 30 -o /dev/null "${CPP_BASE%/}/objects.inv"; then
            echo "Error: no C++ inventory at ${CPP_BASE%/}/objects.inv" >&2
            echo "" >&2
            echo "       The Python docs resolve C++ cross-references against the newest" >&2
            echo "       published stable C++ documentation, so those docs have to exist" >&2
            echo "       first. On a first run, or after the C++ line is retired, they may" >&2
            echo "       not." >&2
            echo "" >&2
            echo "       Either deploy the C++ component first, or point this build at an" >&2
            echo "       inventory directly:" >&2
            echo "         CCCL_CPP_OBJECTS_INV=/path/to/objects.inv" >&2
            exit 1
        fi
        echo "Resolving C++ cross-references against ${CPP_BASE%/}/"
    fi
fi

echo "Building Python documentation (version: ${VERSION})..."
rm -rf "${VERSIONED_HTML_DIR}"
mkdir -p "${VERSIONED_HTML_DIR}"

SPHINXOPTS=(-W --keep-going -j auto)
if [[ -n "${CCCL_DOCS_SPHINXOPTS:-}" ]]; then
    read -r -a SPHINXOPTS <<< "${CCCL_DOCS_SPHINXOPTS}"
fi

# Every component needs its own 404_helper.html: the router sends a miss to
# <component>/<version>/404_helper.html, so a component without one turns a
# missing page into a second missing page. The source lives in docs/ and is
# shared, but Sphinx only renders what is under its source directory -- which
# here is docs/python. So stage the two files in, and take them back out again
# whether the build succeeds or fails, because docs/python is tracked.
HELPER_SOURCES=(404_helper.rst 404_helper.inc.html)
staged_helpers=()
for helper in "${HELPER_SOURCES[@]}"; do
    if [[ ! -f "${SCRIPT_PATH}/${helper}" ]]; then
        echo "Error: ${SCRIPT_PATH}/${helper} is missing; the 404 helper cannot be built." >&2
        exit 1
    fi
    if [[ -e "${SCRIPT_PATH}/python/${helper}" ]]; then
        continue   # the component carries its own copy; leave it alone
    fi
    cp "${SCRIPT_PATH}/${helper}" "${SCRIPT_PATH}/python/${helper}"
    staged_helpers+=("${SCRIPT_PATH}/python/${helper}")
done
cleanup_staged_helpers() {
    if [[ ${#staged_helpers[@]} -gt 0 ]]; then
        rm -f "${staged_helpers[@]}"
    fi
}
trap cleanup_staged_helpers EXIT

# -c selects the configuration directory, so a release's own sources are built
# with this configuration even though the release predates it.
python -m sphinx.cmd.build \
    -b html \
    -c "${SCRIPT_PATH}/python_conf" \
    -d "${BUILDDIR}/python-doctrees" \
    "${SCRIPT_PATH}/python" \
    "${VERSIONED_HTML_DIR}" \
    "${SPHINXOPTS[@]}"

# Fail here rather than shipping a component whose 404 handler is itself a 404.
if [[ ! -f "${VERSIONED_HTML_DIR}/404_helper.html" ]]; then
    echo "Error: the build produced no 404_helper.html." >&2
    echo "       Every miss in this component would redirect to a missing page." >&2
    exit 1
fi

# The page list the 404 handler searches when a URL in this component misses.
./scrape_docs.bash "${VERSIONED_HTML_DIR}"

echo "Python documentation build complete: ${HTML_DIR}/"
