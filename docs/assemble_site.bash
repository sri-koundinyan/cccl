#!/usr/bin/env bash

# Assemble the published site around a freshly built component.
#
# Usage:
#   ./assemble_site.bash <site_root> <component> <version> <site_base_url>
#
#   site_root      Root of the site being published. The component's own pages
#                  live under <site_root>/<component path>/<version>/.
#   component      Component id from published_versions.json, e.g. cpp, python.
#   version        The version directory that was just built, e.g. "unstable",
#                  "3.4". Must match SPHINX_CCCL_VER, which conf.py turns into
#                  the switcher's version_match.
#   site_base_url  Public base URL of the whole site, e.g.
#                  https://nvidia.github.io/cccl/
#
# The C++ and Python libraries ship on independent release lines, so each is a
# component with its own subtree, its own version list and its own switcher.
# C++ sits at the site root (empty path) because it has been published there
# since before versioning existed and moving it would break every working URL.
#
# Two things are written: the component's own root (switcher manifests, redirect,
# /latest/ alias, objects.inv) and the shared site root (landing page, the single
# 404 handler GitHub Pages allows, .nojekyll).
#
# Everything is derived from published_versions.json rather than from the version
# being built, so any build publishes a complete and correct set of root files.
# That is what lets deployment be purely additive.
#
# Split out of gen_docs.bash so it can be tested without a Doxygen and Sphinx
# run; see test_assemble_site.bash.

set -euo pipefail

if [[ "$#" -ne 4 ]]; then
    echo "usage: $0 <site_root> <component> <version> <site_base_url>" >&2
    exit 1
fi

SCRIPT_PATH=$(cd "$(dirname "${BASH_SOURCE[0]}")"; pwd -P)

SITE_ROOT="$1"
COMPONENT="$2"
VERSION="$3"
SITE_BASE_URL="${4%/}/"

# Overridable so the test harness can exercise layouts that do not exist yet.
VERSIONS_FILE="${CCCL_DOCS_VERSIONS_FILE:-${SCRIPT_PATH}/published_versions.json}"

# The manifest owns where each component lives, so nothing else has to hardcode
# it. Reading it here keeps the shell and the renderer agreeing on one answer.
COMPONENT_PATH="$(python3 - "${VERSIONS_FILE}" "${COMPONENT}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as f:
    manifest = json.load(f)
for component in manifest["components"]:
    if component["id"] == sys.argv[2]:
        print(component.get("path", ""))
        break
else:
    known = ", ".join(c["id"] for c in manifest["components"])
    sys.exit(f"error: no component '{sys.argv[2]}'. Known: {known}")
PY
)"

if [[ -n "${COMPONENT_PATH}" ]]; then
    COMPONENT_ROOT="${SITE_ROOT}/${COMPONENT_PATH}"
    COMPONENT_BASE_URL="${SITE_BASE_URL}${COMPONENT_PATH}/"
else
    COMPONENT_ROOT="${SITE_ROOT}"
    COMPONENT_BASE_URL="${SITE_BASE_URL}"
fi

VERSIONED_HTML_DIR="${COMPONENT_ROOT}/${VERSION}"

if [[ ! -d "${VERSIONED_HTML_DIR}" ]]; then
    echo "Error: expected a built docs tree at ${VERSIONED_HTML_DIR}" >&2
    exit 1
fi

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

# Versions are discovered rather than declared. Search this build first, so the
# version being deployed counts before it has been published, then the
# already-published site if a checkout of it was provided.
PUBLISHED_COMPONENT_ROOT=""
if [[ -n "${CCCL_DOCS_PUBLISHED_SITE:-}" ]]; then
    if [[ -n "${COMPONENT_PATH}" ]]; then
        PUBLISHED_COMPONENT_ROOT="${CCCL_DOCS_PUBLISHED_SITE}/${COMPONENT_PATH}"
    else
        PUBLISHED_COMPONENT_ROOT="${CCCL_DOCS_PUBLISHED_SITE}"
    fi
fi

DISCOVER_ARGS=(--discover-from "${COMPONENT_ROOT}")
if [[ -n "${PUBLISHED_COMPONENT_ROOT}" && -d "${PUBLISHED_COMPONENT_ROOT}" ]]; then
    DISCOVER_ARGS+=(--discover-from "${PUBLISHED_COMPONENT_ROOT}")
fi

render_output="$(python3 "${SCRIPT_PATH}/render_versions.py" \
    --manifest "${VERSIONS_FILE}" \
    --component "${COMPONENT}" \
    --base-url "${COMPONENT_BASE_URL}" \
    --out-dir "${COMPONENT_ROOT}" \
    "${DISCOVER_ARGS[@]}")"
mapfile -t render_lines <<< "${render_output}"

DEFAULT_VERSION="${render_lines[0]}"
SITE_BASE="${render_lines[1]}"
LATEST_STABLE="${render_lines[2]:-}"

echo "Assembling ${COMPONENT} in ${COMPONENT_ROOT}"
echo "  version built:   ${VERSION}"
echo "  default version: ${DEFAULT_VERSION}"
echo "  latest stable:   ${LATEST_STABLE:-<none published>}"
echo "  site base path:  ${SITE_BASE:-/}"

# A nested component gets its own entry point redirecting to its default
# version. The component at the site root does not: that file is the landing
# page, which links straight to this component's version instead.
if [[ -n "${COMPONENT_PATH}" ]]; then
    sed -e "s|@DEFAULT_VERSION@|${DEFAULT_VERSION}|g" \
        "${SCRIPT_PATH}/component_index.html" > "${COMPONENT_ROOT}/index.html"
fi

# Provide a URL that always resolves to this component's newest release.
#
# Built as redirects rather than a copy: a full duplicate of the C++ docs costs
# 100-300 MB against a 1 GB GitHub Pages budget, and readers are better served
# landing on a pinned version-scoped URL anyway.
#
# Regenerated on EVERY deploy, not only on a deploy of latest_stable. Writing it
# only when the stable version is rebuilt means that changing latest_stable
# leaves the alias pointing at the previous release, so /latest/ silently serves
# the wrong version while the switcher claims otherwise.
if [[ -n "${LATEST_STABLE}" ]]; then
    ALIAS_SOURCE=""
    if [[ -d "${COMPONENT_ROOT}/${LATEST_STABLE}" ]]; then
        ALIAS_SOURCE="${COMPONENT_ROOT}"
    elif [[ -n "${PUBLISHED_COMPONENT_ROOT}" \
            && -d "${PUBLISHED_COMPONENT_ROOT}/${LATEST_STABLE}" ]]; then
        ALIAS_SOURCE="${PUBLISHED_COMPONENT_ROOT}"
    fi

    if [[ -n "${ALIAS_SOURCE}" ]]; then
        python3 "${SCRIPT_PATH}/make_latest_alias.py" \
            --site-root "${COMPONENT_ROOT}" \
            --version "${LATEST_STABLE}" \
            --source-root "${ALIAS_SOURCE}"
    else
        # Refusing here would block the deploy of an unrelated version over a
        # stale alias, which is worse than saying so plainly.
        echo "Warning: cannot rebuild ${COMPONENT} latest/ -- no copy of ${LATEST_STABLE}." >&2
        echo "         It keeps whatever it pointed at before. Republish that" >&2
        echo "         version to refresh it." >&2
    fi
fi

# The root objects.inv is what intersphinx consumers resolve against, so it has
# to track the stable docs rather than whichever version built last. Until a
# stable version exists, publish the current build's so the URL works.
if [[ -z "${LATEST_STABLE}" || "${VERSION}" == "${LATEST_STABLE}" ]]; then
    if [[ -f "${VERSIONED_HTML_DIR}/objects.inv" ]]; then
        cp "${VERSIONED_HTML_DIR}/objects.inv" "${COMPONENT_ROOT}/objects.inv"
    fi
fi

# Every other component's root artifacts are refreshed too, from the copy of it
# on the published site. Without this, changing one component's latest_stable
# and then deploying a different component leaves the first advertising an alias
# that was never built -- the same failure as a stale /latest/, across
# components rather than within one. Only the small root files and alias stubs
# are written; the version content itself stays where it already is.
if [[ -n "${PUBLISHED_SITE_ROOT:=${CCCL_DOCS_PUBLISHED_SITE:-}}" \
      && -d "${PUBLISHED_SITE_ROOT}" ]]; then
    while read -r other_id other_path; do
        [[ "${other_id}" == "${COMPONENT}" ]] && continue

        if [[ -n "${other_path}" ]]; then
            other_root="${SITE_ROOT}/${other_path}"
            other_published="${PUBLISHED_SITE_ROOT}/${other_path}"
            other_base_url="${SITE_BASE_URL}${other_path}/"
        else
            other_root="${SITE_ROOT}"
            other_published="${PUBLISHED_SITE_ROOT}"
            other_base_url="${SITE_BASE_URL}"
        fi

        # Nothing published for it yet; there is nothing to refresh.
        [[ -d "${other_published}" ]] || continue

        echo "Refreshing ${other_id} from the published site"
        other_output="$(python3 "${SCRIPT_PATH}/render_versions.py" \
            --manifest "${VERSIONS_FILE}" \
            --component "${other_id}" \
            --base-url "${other_base_url}" \
            --out-dir "${other_root}" \
            --discover-from "${other_published}")" || continue
        mapfile -t other_lines <<< "${other_output}"

        if [[ -n "${other_path}" ]]; then
            sed -e "s|@DEFAULT_VERSION@|${other_lines[0]}|g" \
                "${SCRIPT_PATH}/component_index.html" > "${other_root}/index.html"
        fi

        other_latest="${other_lines[2]:-}"
        if [[ -n "${other_latest}" && -d "${other_published}/${other_latest}" ]]; then
            python3 "${SCRIPT_PATH}/make_latest_alias.py" \
                --site-root "${other_root}" \
                --version "${other_latest}" \
                --source-root "${other_published}"
        fi
    done < <(python3 - "${VERSIONS_FILE}" <<'PY_INNER'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as f:
    for component in json.load(f)["components"]:
        print(component["id"], component.get("path", ""))
PY_INNER
)
fi

# The shared site root: the landing page readers choose a component from, and
# the single 404 handler GitHub Pages allows for the whole site. Both are
# rendered from the manifest, so any component's deploy produces the same
# correct files.
SITE_ROOT_ARGS=()
if [[ -n "${CCCL_DOCS_PUBLISHED_SITE:-}" && -d "${CCCL_DOCS_PUBLISHED_SITE}" ]]; then
    SITE_ROOT_ARGS+=(--discover-from "${CCCL_DOCS_PUBLISHED_SITE}")
fi

python3 "${SCRIPT_PATH}/render_site_root.py" \
    --manifest "${VERSIONS_FILE}" \
    --site-root "${SITE_ROOT}" \
    --site-base "${SITE_BASE}" \
    --template-dir "${SCRIPT_PATH}" \
    ${SITE_ROOT_ARGS[@]+"${SITE_ROOT_ARGS[@]}"}

touch "${SITE_ROOT}/.nojekyll"
