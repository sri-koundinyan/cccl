#!/usr/bin/env bash

# Assemble the site-root artifacts around an already-built versioned docs tree.
#
# Usage:
#   ./assemble_site.bash <html_dir> <version> <base_url>
#
#   html_dir  Site root. Must already contain <html_dir>/<version>/ as produced
#             by Sphinx.
#   version   The version directory that was just built, e.g. "unstable", "3.4".
#             Must match SPHINX_CCCL_VER, which docs/conf.py turns into the
#             switcher's version_match.
#   base_url  Public base URL of the docs site, e.g. https://nvidia.github.io/cccl/
#
# Everything written here is derived from published_versions.json rather than
# from the version being built, so any build publishes a complete and correct
# set of root files. That is what lets the deployment be purely additive: a
# 3.4 deploy and an unstable deploy write byte-identical root artifacts instead
# of overwriting each other's version lists.
#
# This is split out of gen_docs.bash so it can be tested without a Doxygen and
# Sphinx run; see test_assemble_site.bash.

set -euo pipefail

if [[ "$#" -ne 3 ]]; then
    echo "usage: $0 <html_dir> <version> <base_url>" >&2
    exit 1
fi

SCRIPT_PATH=$(cd "$(dirname "${BASH_SOURCE[0]}")"; pwd -P)

HTML_DIR="$1"
VERSION="$2"
BASE_URL="${3%/}/"

VERSIONED_HTML_DIR="${HTML_DIR}/${VERSION}"

if [[ ! -d "${VERSIONED_HTML_DIR}" ]]; then
    echo "Error: expected a built docs tree at ${VERSIONED_HTML_DIR}" >&2
    exit 1
fi

# Overridable so the test harness can exercise version layouts that do not exist
# yet. Production builds always use the checked-in manifest.
VERSIONS_FILE="${CCCL_DOCS_VERSIONS_FILE:-${SCRIPT_PATH}/published_versions.json}"

# Render nv-versions.json and versions.json, and read back the derived values.
render_output="$(python3 "${SCRIPT_PATH}/render_versions.py" \
    --manifest "${VERSIONS_FILE}" \
    --base-url "${BASE_URL}" \
    --out-dir "${HTML_DIR}")"
mapfile -t render_lines <<< "${render_output}"

DEFAULT_VERSION="${render_lines[0]}"
SITE_BASE="${render_lines[1]}"
LATEST_STABLE="${render_lines[2]:-}"

# The switcher can only highlight the version the reader is on if the value
# Sphinx stamped into the pages matches the directory they are served from.
# These drift apart silently, so check rather than trust.
#
# Releases predating the version switcher stamp nothing at all, so a missing
# value is expected and must not be fatal. The `|| true` is load-bearing: under
# `set -o pipefail` a grep that matches nothing fails the whole pipeline.
INDEX_PAGE="${VERSIONED_HTML_DIR}/index.html"
if [[ -f "${INDEX_PAGE}" ]]; then
    STAMPED_VERSION="$(sed -n "s/.*version_match = '\([^']*\)'.*/\1/p" \
        "${INDEX_PAGE}" | head -1 || true)"
    if [[ -z "${STAMPED_VERSION}" ]]; then
        echo "  no version_match in the built pages; skipping the consistency check"
    elif [[ "${STAMPED_VERSION}" != "${VERSION}" ]]; then
        echo "Error: built pages declare version_match '${STAMPED_VERSION}'," >&2
        echo "       but they are being published as '${VERSION}'." >&2
        echo "       The version switcher cannot match an entry it was not told about." >&2
        exit 1
    fi
fi

echo "Assembling site root in ${HTML_DIR}"
echo "  version built:   ${VERSION}"
echo "  default version: ${DEFAULT_VERSION}"
echo "  latest stable:   ${LATEST_STABLE:-<none published>}"
echo "  site base path:  ${SITE_BASE:-/}"

# Root redirect and 404 handler. Both are templates so that the version scheme
# lives in one place and so forks (which have a different base URL) route
# correctly instead of hard-coding /cccl.
sed -e "s|@DEFAULT_VERSION@|${DEFAULT_VERSION}|g" \
    "${SCRIPT_PATH}/index.html" > "${HTML_DIR}/index.html"
sed -e "s|@DEFAULT_VERSION@|${DEFAULT_VERSION}|g" \
    -e "s|@SITE_BASE@|${SITE_BASE}|g" \
    "${SCRIPT_PATH}/404.html" > "${HTML_DIR}/404.html"

# Provide a URL that always resolves to the newest release. Only the build of
# latest_stable may write it; an unstable build must not, or /latest/ would
# silently become the development docs.
#
# Built as redirects rather than a copy: a full duplicate costs about 150 MB
# against a 1 GB GitHub Pages budget, and readers are better served landing on
# a pinned version-scoped URL anyway.
if [[ -n "${LATEST_STABLE}" && "${VERSION}" == "${LATEST_STABLE}" ]]; then
    python3 "${SCRIPT_PATH}/make_latest_alias.py" \
        --site-root "${HTML_DIR}" --version "${VERSION}"
fi

# The root objects.inv is what intersphinx consumers resolve against, so it has
# to track the stable docs rather than whichever version happened to build last.
# Until a stable version exists, publish the current build's so the URL works.
if [[ -z "${LATEST_STABLE}" || "${VERSION}" == "${LATEST_STABLE}" ]]; then
    if [[ -f "${VERSIONED_HTML_DIR}/objects.inv" ]]; then
        cp "${VERSIONED_HTML_DIR}/objects.inv" "${HTML_DIR}/objects.inv"
    fi
fi

touch "${HTML_DIR}/.nojekyll"
