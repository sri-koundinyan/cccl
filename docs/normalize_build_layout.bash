#!/usr/bin/env bash

# Normalises a documentation build so that site assembly works the same way for
# every release, including ones that predate versioned publishing.
#
# Usage:
#   ./normalize_build_layout.bash <site_root> <version>
#
# Releases from before this scheme existed build a flat tree -- index.html and
# the library directories sit directly at the root of the build output, with no
# version directory -- and never generate the page list the 404 handler
# searches. Rather than backporting the build script to every old tag, those
# outputs are reshaped here into the layout the rest of the pipeline expects.
#
# Both operations are no-ops for a modern build, so this can run unconditionally.

set -euo pipefail

if [[ "$#" -ne 2 ]]; then
    echo "usage: $0 <site_root> <version>" >&2
    exit 1
fi

SCRIPT_PATH=$(cd "$(dirname "${BASH_SOURCE[0]}")"; pwd -P)

SITE_ROOT="$1"
VERSION="$2"

if [[ ! -d "${SITE_ROOT}" ]]; then
    echo "Error: no build to normalise at ${SITE_ROOT}" >&2
    exit 1
fi

if [[ ! -d "${SITE_ROOT}/${VERSION}" ]]; then
    # A flat build. Move everything down one level, via a scratch directory so
    # the destination cannot be moved into itself.
    if [[ -z "$(find "${SITE_ROOT}" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
        echo "Error: ${SITE_ROOT} is empty; nothing was built" >&2
        exit 1
    fi
    echo "  build is flat; nesting it under ${VERSION}/"
    scratch="$(mktemp -d "${SITE_ROOT}.XXXXXX")"
    find "${SITE_ROOT}" -mindepth 1 -maxdepth 1 -exec mv {} "${scratch}/" \;
    mkdir -p "${SITE_ROOT}/${VERSION}"
    find "${scratch}" -mindepth 1 -maxdepth 1 -exec mv {} "${SITE_ROOT}/${VERSION}/" \;
    rmdir "${scratch}"
fi

if [[ ! -f "${SITE_ROOT}/${VERSION}/pagelist.txt" ]]; then
    # Without this the 404 handler has nothing to match against, so a missing
    # page in this version would offer no suggestions.
    echo "  generating the page list for ${VERSION}/"
    "${SCRIPT_PATH}/scrape_docs.bash" "${SITE_ROOT}/${VERSION}"
fi
