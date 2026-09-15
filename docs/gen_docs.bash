#!/usr/bin/env bash

# This script builds CCCL documentation using Sphinx directly
#
# Usage:
#   ./gen_docs.bash                    - Build documentation
#   ./gen_docs.bash --allow-dep-install - Build, auto-install missing system deps
#   ./gen_docs.bash clean              - Clean build directory
#   ./gen_docs.bash clean --all        - Clean build directory and Doxygen build
#
# The script will optionally build Doxygen 1.9.6 from source to ensure
# consistent documentation generation. The built Doxygen will be stored
# in _build/doxygen-build/ and reused for subsequent runs.

set -euo pipefail

ALLOW_DEP_INSTALL=false
CLEAN=false
CLEAN_ALL=false
LABEL=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --allow-dep-install) ALLOW_DEP_INSTALL=true ;;
        clean)               CLEAN=true ;;
        --all)               CLEAN_ALL=true ;;
        # The directory this build is served from, which is also the switcher
        # entry representing it: "latest" for a development build, or the exact
        # MAJOR.MINOR.PATCH for a release. Supplied explicitly so the stamp
        # never depends on an inherited environment value.
        --label)             LABEL="${2:-}"; shift ;;
        --label=*)           LABEL="${1#*=}" ;;
        # cuda-python's mode name, kept so the two read alike.
        latest-only)         LABEL="latest" ;;
        *)                   echo "Unknown argument: $1"; exit 1 ;;
    esac
    shift
done

SCRIPT_PATH=$(cd "$(dirname "${0}")"; pwd -P)
cd "$SCRIPT_PATH"

BUILDDIR="_build"
DOXYGEN_BUILD_DIR="${SCRIPT_PATH}/_build/doxygen-build"
DOXYGEN_SRC_DIR="${SCRIPT_PATH}/_build/doxygen-src"

# Handle clean command (before dep checks — clean doesn't need deps)
if [[ "$CLEAN" = true ]]; then
    echo "Cleaning build directory..."
    rm -rf "${BUILDDIR:?}"/*
    if [[ "$CLEAN_ALL" = true ]]; then
        echo "Also removing Doxygen source and build directories..."
        rm -rf "${DOXYGEN_SRC_DIR}" "${DOXYGEN_BUILD_DIR}"
    fi
    exit 0
fi

# Check and optionally install system dependencies
check_system_deps() {
    local missing=()
    # Map of command -> package name
    local -A cmd_to_pkg=(
        [cmake]=cmake
        [ninja]=ninja-build
        [flex]=flex
        [bison]=bison
        [git]=git
    )

    # python3-venv is a package, not a command — check by trying to create a venv
    if ! python3 -m venv --help &>/dev/null; then
        missing+=(python3-venv)
    fi

    for cmd in "${!cmd_to_pkg[@]}"; do
        if ! command -v "$cmd" &>/dev/null; then
            missing+=("${cmd_to_pkg[$cmd]}")
        fi
    done

    if [[ ${#missing[@]} -eq 0 ]]; then
        return 0
    fi

    echo "Missing system dependencies: ${missing[*]}"

    if [[ "$ALLOW_DEP_INSTALL" = true ]]; then
        echo "Installing missing dependencies (--allow-dep-install)..."
        sudo apt-get update -qq
        sudo apt-get install -y -qq "${missing[@]}"
    else
        read -r -p "Install them now? [y/N] " response
        if [[ "$response" =~ ^[Yy]$ ]]; then
            sudo apt-get update -qq
            sudo apt-get install -y -qq "${missing[@]}"
        else
            echo "Error: Missing dependencies. Install with:"
            echo "  sudo apt-get install -y ${missing[*]}"
            exit 1
        fi
    fi
}

check_system_deps

# Configuration
# Keep going to surface all warnings; -W makes warnings fail the build.
declare -a SPHINXOPTS="(${SPHINXOPTS:---keep-going -W})"
DOXYGEN_BIN="${DOXYGEN_BUILD_DIR}/bin/doxygen"

# Use custom-built doxygen if available, otherwise fall back to system doxygen
if [[ -f "${DOXYGEN_BIN}" ]]; then
    DOXYGEN="${DOXYGEN_BIN}"
else
    DOXYGEN="${DOXYGEN:-doxygen}"
fi

## Clean image directory, without this any artifacts will prevent fetching
rm -rf img
mkdir -p img

# Pull cub images
if [[ ! -d cubimg ]]; then
    git clone -b gh-pages https://github.com/NVlabs/cub.git cubimg
fi

if [[ -z "$(find cubimg -name 'example_range.png')" ]]; then
    wget -q https://raw.githubusercontent.com/NVIDIA/NVTX/release-v3/docs/images/example_range.png -O cubimg/example_range.png
fi

if [[ -z "$(find img -name '*.png')" ]]; then
    wget -q https://docs.nvidia.com/cuda/_static/Logo_and_CUDA.png -O img/logo.png

    # Parse files and collects unique names ending with .png
    imgs="$(grep -R -o -h '[[:alpha:][:digit:]_]*.png' ../cub/cub | uniq)"
    declare -a imgs="($imgs)"
    imgs+=( "cub_overview.png" "nested_composition.png" "tile.png" "blocked.png" "striped.png" )

    for img in "${imgs[@]}"
    do
        echo "${img}"
        cp cubimg/"${img}" img/"${img}"
    done
fi

# Function to build Doxygen 1.9.6
build_doxygen() {
    echo "Building Doxygen 1.9.6..."

    # Clone Doxygen if not already cloned
    if [[ ! -d "${DOXYGEN_SRC_DIR}" ]]; then
        echo "Cloning Doxygen repository..."
        git clone https://github.com/doxygen/doxygen.git "${DOXYGEN_SRC_DIR}"
    fi

    # Checkout Release_1_9_6
    cd "${DOXYGEN_SRC_DIR}"
    git fetch
    git checkout Release_1_9_6

    # Create build directory
    mkdir -p "${DOXYGEN_BUILD_DIR}"
    cd "${DOXYGEN_BUILD_DIR}"

    # Configure based on platform
    echo "Configuring Doxygen build..."
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        echo "Detected macOS, configuring with LLVM paths..."
        if ! command -v brew &> /dev/null; then
            echo "Warning: Homebrew not found, building without libclang support"
            cmake -GNinja -DCMAKE_BUILD_TYPE=Release \
                -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
                "${DOXYGEN_SRC_DIR}"
        else
            cmake -GNinja -DCMAKE_BUILD_TYPE=Release \
                -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
                -Duse_libclang=NO \
                -DBISON_EXECUTABLE="$(brew --prefix bison)/bin/bison" \
                "${DOXYGEN_SRC_DIR}"
        fi
    else
        # Linux/Ubuntu
        echo "Configuring for Linux/Ubuntu..."
        cmake -GNinja -DCMAKE_BUILD_TYPE=Release \
            -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
            -Duse_libclang=NO \
            "${DOXYGEN_SRC_DIR}"
    fi

    # Build Doxygen
    echo "Building Doxygen (this may take a few minutes)..."
    ninja

    echo "Doxygen 1.9.6 built successfully at ${DOXYGEN_BIN}"
    cd "${SCRIPT_PATH}"
}

# Check if custom Doxygen needs to be built
if [[ ! -f "${DOXYGEN_BIN}" ]]; then
    echo "Custom Doxygen 1.9.6 not found, building it now..."
    build_doxygen
    DOXYGEN="${DOXYGEN_BIN}"
else
    echo "Using custom-built Doxygen 1.9.6 from ${DOXYGEN_BIN}"
fi

# Check if documentation dependencies are installed
echo "Checking for documentation dependencies..."

# Use virtual environment if it exists, otherwise create one
if [[ -d "env" ]]; then
    echo "Using existing virtual environment..."
    # shellcheck disable=SC1091
    source env/bin/activate
else
    echo "Creating virtual environment..."
    python3 -m venv env
    # shellcheck disable=SC1091
    source env/bin/activate
fi

# Check if dependencies are installed in the virtual environment
if ! python -c "import sphinx" 2>/dev/null; then
    echo "Installing documentation dependencies..."
    python3 -m pip install -r requirements.txt || {
        echo "Error: Failed to install documentation dependencies"
        echo "Please install manually: pip install -r requirements.txt"
        exit 1
    }
fi

# Generate Doxygen XML in parallel (if doxygen is available)
if [[ "${CCCL_DOCS_SKIP_AUTO_API_GENERATOR:-0}" == "1" ]]; then
    echo "Skipping Doxygen XML generation (CCCL_DOCS_SKIP_AUTO_API_GENERATOR=1)"
elif command -v "${DOXYGEN}" > /dev/null 2>&1; then
    echo "Generating Doxygen XML..."
    mkdir -p "${BUILDDIR}"/doxygen/cub "${BUILDDIR}"/doxygen/thrust "${BUILDDIR}"/doxygen/cudax "${BUILDDIR}"/doxygen/libcudacxx

    # Copy all images to Doxygen XML output directories where they're expected
    for project in cub thrust cudax libcudacxx; do
        mkdir -p "${BUILDDIR}"/doxygen/"${project}"/xml
        cp img/*.png "${BUILDDIR}"/doxygen/"${project}"/xml/ 2>/dev/null || true
    done

    # Run all Doxygen builds in parallel, fail if any produce warnings/errors
    (cd cub && ${DOXYGEN} Doxyfile) &
    pids+=($!)
    (cd thrust && ${DOXYGEN} Doxyfile) &
    pids+=($!)
    (cd cudax && ${DOXYGEN} Doxyfile) &
    pids+=($!)
    (cd libcudacxx && ${DOXYGEN} Doxyfile) &
    pids+=($!)

    doxygen_failed=0
    for pid in "${pids[@]}"; do
        if ! wait "$pid"; then
            doxygen_failed=1
        fi
    done
    if [[ "$doxygen_failed" -ne 0 ]]; then
        echo "Error: one or more Doxygen builds failed (see warnings above)"
        exit 1
    fi

    echo "Doxygen complete"
else
    echo "Skipping Doxygen (not installed)"
fi

# The destination directory decides the rendered version stamp, and the two must
# agree or the switcher can never highlight the current page -- a failure that
# renders perfectly and is invisible to a page-level smoke test.
VERSION="${LABEL:-${CCCL_DOCS_LABEL:-latest}}"

if [[ ! "${VERSION}" =~ ^(latest|[0-9]+\.[0-9]+\.[0-9]+)$ ]]; then
    echo "Error: --label must be 'latest' or an exact MAJOR.MINOR.PATCH release," >&2
    echo "       got '${VERSION}'." >&2
    echo "       'latest' is the development branch; a release uses its full" >&2
    echo "       version, e.g. 3.4.2. There is no rolling MAJOR.MINOR directory." >&2
    exit 1
fi

# conf.py reads the label for the canonical URL and the switcher entry, and
# SPHINX_CCCL_VER for the displayed release. For a stable build these are the
# same; for a development build the source version differs from "latest".
export CCCL_DOCS_LABEL="${VERSION}"
export SPHINX_CCCL_VER="${SPHINX_CCCL_VER:-${VERSION}}"

# Artifact layout matches what the deploy action uploads: artifacts/docs/ is
# copied onto gh-pages:docs/, so every path here is a final site path.
HTML_DIR="${BUILDDIR}/artifacts/docs/cpp"
VERSIONED_HTML_DIR="${HTML_DIR}/${VERSION}"

# Full builds validate the regenerated API sources from a fresh Sphinx state.
# Fast local builds preserve the caches and HTML outputs for incremental reuse.
if [[ "${CCCL_DOCS_SKIP_AUTO_API_GENERATOR:-0}" != "1" ]]; then
    rm -rf "${BUILDDIR}/doctrees" "${VERSIONED_HTML_DIR}"
fi

# Build Sphinx HTML documentation directly into the versioned directory.
echo "Building documentation with Sphinx..."
mkdir -p "${VERSIONED_HTML_DIR}"
# Use the virtual environment's Python
python -m sphinx.cmd.build -b html -d "${BUILDDIR}/doctrees" -j auto "." "${VERSIONED_HTML_DIR}" "${SPHINXOPTS[@]}"

# This script produces one component artifact and nothing else. It does not
# assemble a website: no switcher manifest, no inventory alias, no landing page,
# no 404 handler, no .nojekyll.
#
# Those files describe the site as a whole -- which versions exist, which
# component a reader chose -- and a single build cannot know any of that. They
# are written by docs/publish_site.py from the complete published tree, which
# can see every version. A build that guessed at them would overwrite the real
# answer with a one-version view of the world.

# A pre-split source builds the Python pages into this tree, which would publish
# them under a C++ version they never shipped under. The planner rejects such a
# source up front; this is the check that the produced artifact actually honours
# it, and it costs one test.
if [[ -d "${VERSIONED_HTML_DIR}/python" ]]; then
    echo "Error: the C++ artifact contains a top-level python/ directory." >&2
    echo "       This source does not exclude docs/python from the C++ build," >&2
    echo "       so it predates the C++/Python split. Publishing it would put" >&2
    echo "       Python pages under ${VERSION}/python/ labelled '${VERSION}'." >&2
    exit 1
fi

# Each component build ships its own switcher manifest and landing redirect
# alongside the version directory, as cuda-python's component builds do. The
# manifest is checked-in release data: this release's copy of the version list
# travels with this release's documentation.
cp "${SCRIPT_PATH}/cpp_site/nv-versions.json" "${HTML_DIR}/nv-versions.json"
cp "${SCRIPT_PATH}/cpp_site/versions.json" "${HTML_DIR}/versions.json"
cp "${SCRIPT_PATH}/cpp_site/index.html" "${HTML_DIR}/index.html"

# The convenience inventory at the component root, for intersphinx consumers
# who want a stable URL. It tracks the development documentation.
if [[ "${VERSION}" == "latest" && -f "${VERSIONED_HTML_DIR}/objects.inv" ]]; then
    cp "${VERSIONED_HTML_DIR}/objects.inv" "${HTML_DIR}/objects.inv"
fi

# The published entry must claim the directory it is served from, or the
# switcher silently never highlights the current page.
if ! grep -q "version_match = '${VERSION}'" "${VERSIONED_HTML_DIR}/index.html"; then
    echo "Error: pages are not stamped '${VERSION}'." >&2
    echo "       The switcher matches this stamp against its manifest entry;" >&2
    echo "       a mismatch renders correctly and is invisible to a page check." >&2
    exit 1
fi

# The manifest must list the version being published, or the reader has no way
# to reach it, and the two manifests must agree (§4.2). This is the cheap guard
# against the drift visible on cuda-python's own site, where cuda-core's
# versions.json stops at 0.3.2 while its nv-versions.json reaches 1.2.0 --
# each is whatever the last build happened to copy.
python3 "${SCRIPT_PATH}/check_manifests.py" "${HTML_DIR}" "${VERSION}"

echo "C++ documentation build complete: ${VERSIONED_HTML_DIR}"
