#!/usr/bin/env bash

# Tests for the documentation versioning logic.
#
# Usage: ./test_assemble_site.bash
#
# These exercise assemble_site.bash and render_versions.py against stub Sphinx
# output, so they run in about a second and need neither Doxygen nor Sphinx.
# What they cover is the part that decides where documentation is published and
# which versions the switcher offers -- the part where a mistake silently breaks
# links rather than failing a build.
#
# Not covered here, because it cannot be checked without deploying: whether
# GitHub Pages actually preserves previously published version directories
# across a deploy. That is a property of the deploy action's settings and has to
# be verified by publishing twice to a fork. See docs-deploy.yml.

set -euo pipefail

SCRIPT_PATH=$(cd "$(dirname "${BASH_SOURCE[0]}")"; pwd -P)

FAILURES=0
CASE=""

WORK_DIR="$(mktemp -d)"
trap 'rm -rf "${WORK_DIR}"' EXIT

start_case() {
    CASE="$1"
    echo
    echo "== ${CASE}"
}

pass() {
    echo "  ok   $1"
}

fail() {
    echo "  FAIL $1" >&2
    FAILURES=$((FAILURES + 1))
}

assert_eq() {
    # <description> <expected> <actual>
    if [[ "$2" == "$3" ]]; then
        pass "$1"
    else
        fail "$1: expected '$2', got '$3'"
    fi
}

assert_file() {
    if [[ -f "$2" ]]; then
        pass "$1"
    else
        fail "$1: missing file $2"
    fi
}

assert_no_dir() {
    if [[ ! -d "$2" ]]; then
        pass "$1"
    else
        fail "$1: directory should not exist: $2"
    fi
}

assert_fails() {
    # <description> <command...>
    local description="$1"
    shift
    if "$@" > "${WORK_DIR}/stderr.log" 2>&1; then
        fail "${description}: command unexpectedly succeeded"
    else
        pass "${description}"
    fi
}

# Read a value out of a JSON file using a python expression over `data`.
json_query() {
    python3 -c '
import json
import sys

with open(sys.argv[1], encoding="utf-8") as f:
    data = json.load(f)
print(eval(sys.argv[2]))  # noqa: S307 - test helper, expression is a literal
' "$1" "$2"
}

# Create a stub Sphinx build for one version. The optional third argument is the
# version the pages claim via the theme's switcher config; it defaults to
# matching the directory, which is the correct case.
make_version_build() {
    # <site_root> <version> [stamped_version]
    local stamped="${3:-$2}"
    mkdir -p "$1/$2/sub"
    cat > "$1/$2/index.html" <<EOF
<html><body>docs for $2
<script>var version_match = '${stamped}';</script>
</body></html>
EOF
    echo "<html><body>nested page in $2</body></html>" > "$1/$2/sub/page.html"
    echo "<html><body>404 helper for $2</body></html>" > "$1/$2/404_helper.html"
    echo "/index.html,/sub/page.html," > "$1/$2/pagelist.txt"
    echo "objects-inv-for-$2" > "$1/$2/objects.inv"
}

write_manifest() {
    # <path> <cpp_latest_stable-or-null> [python_latest_stable-or-null]
    #
    # Versions are discovered from the site rather than declared, so what a test
    # publishes is decided by which directories it creates. Only the per
    # component latest_stable is configuration.
    local path="$1"
    local cpp_latest="$2"
    local py_latest="${3:-null}"
    python3 -c '
import json
import sys

path, cpp_latest, py_latest = sys.argv[1], sys.argv[2], sys.argv[3]
manifest = {
    "size_budget_versions": 5,
    "components": [
        {
            "id": "cpp",
            "label": "C++",
            "path": "",
            "description": "Thrust, CUB, libcu++ and CUDA Experimental",
            "latest_stable": None if cpp_latest == "null" else cpp_latest,
        },
        {
            "id": "python",
            "label": "Python",
            "path": "python",
            "description": "cuda.compute and cuda.coop",
            "latest_stable": None if py_latest == "null" else py_latest,
        },
    ],
}
with open(path, "w", encoding="utf-8") as f:
    json.dump(manifest, f, indent=2)
' "${path}" "${cpp_latest}" "${py_latest}"
}

assemble() {
    # <site_root> <version> <manifest> [published_site]  -- the cpp component
    assemble_component "$1" cpp "$2" "$3" "${4:-}"
}

assemble_component() {
    # <site_root> <component> <version> <manifest> [published_site]
    #
    # published_site stands in for the checkout of the already-deployed site
    # that the workflow provides, which is where versions other than the one
    # being built are discovered from.
    CCCL_DOCS_VERSIONS_FILE="$4" CCCL_DOCS_PUBLISHED_SITE="${5:-}" \
        "${SCRIPT_PATH}/assemble_site.bash" \
        "$1" "$2" "$3" "https://nvidia.github.io/cccl/" > /dev/null
}

# ---------------------------------------------------------------------------
start_case "Day one: only unstable published, no stable release yet"
# This is the state the checked-in manifest ships in, so it is also an assertion
# that merging this change does not move any URL that exists today.

ROOT="${WORK_DIR}/case_a"
MANIFEST="${WORK_DIR}/manifest_a.json"
write_manifest "${MANIFEST}" null
make_version_build "${ROOT}" unstable
assemble "${ROOT}" unstable "${MANIFEST}"

assert_eq "switcher lists exactly one version" \
    "1" "$(json_query "${ROOT}/nv-versions.json" 'len(data)')"
assert_eq "that version is unstable" \
    "unstable" "$(json_query "${ROOT}/nv-versions.json" 'data[0]["version"]')"
assert_eq "no version is marked preferred while none is stable" \
    "0" "$(json_query "${ROOT}/nv-versions.json" 'sum("preferred" in e for e in data)')"

if grep -q 'href="/cccl/unstable/"' "${ROOT}/index.html"; then
    pass "landing page sends C++ readers to unstable/ when no stable exists"
else
    fail "landing page should link C++ to unstable/ when no stable exists"
fi

assert_no_dir "no latest/ alias is created before a stable release" "${ROOT}/latest"
assert_file "root objects.inv is published" "${ROOT}/objects.inv"
assert_file ".nojekyll is published" "${ROOT}/.nojekyll"

if grep -q '@SITE_BASE@\|@DEFAULT_VERSION@' "${ROOT}/404.html" "${ROOT}/index.html"; then
    fail "template placeholders were left unsubstituted"
else
    pass "all template placeholders are substituted"
fi

if grep -q 'var SITE_BASE = "/cccl";' "${ROOT}/404.html"; then
    pass "404 handler is pinned to the site base path"
else
    fail "404 handler did not receive the site base path"
fi

# ---------------------------------------------------------------------------
start_case "A stable release is published and becomes latest"

ROOT="${WORK_DIR}/case_b"
MANIFEST="${WORK_DIR}/manifest_b.json"
write_manifest "${MANIFEST}" 3.4
make_version_build "${ROOT}" unstable
make_version_build "${ROOT}" 3.4
assemble "${ROOT}" 3.4 "${MANIFEST}"

assert_eq "switcher lists latest plus both versions" \
    "3" "$(json_query "${ROOT}/nv-versions.json" 'len(data)')"
assert_eq "the synthetic latest entry comes first" \
    "latest" "$(json_query "${ROOT}/nv-versions.json" 'data[0]["version"]')"
assert_eq "latest points at the stable alias URL" \
    "https://nvidia.github.io/cccl/latest/" \
    "$(json_query "${ROOT}/nv-versions.json" 'data[0]["url"]')"
assert_eq "the stable version is the preferred one, not the alias" \
    "3.4" \
    "$(json_query "${ROOT}/nv-versions.json" '[e["version"] for e in data if e.get("preferred")][0]')"
assert_eq "release URLs are absolute and version-scoped" \
    "https://nvidia.github.io/cccl/3.4/" \
    "$(json_query "${ROOT}/nv-versions.json" '[e["url"] for e in data if e["version"] == "3.4"][0]')"

# The root must target the concrete version, not the latest/ alias: the alias is
# only written by a build of latest_stable, so a root pointing at it would 404
# for every deploy between naming a new latest_stable and rebuilding it.
if grep -q 'href="/cccl/3.4/"' "${ROOT}/index.html"; then
    pass "landing page links C++ to the concrete stable version"
else
    fail "landing page should link C++ to 3.4/, not to the latest/ alias"
fi
if grep -q 'href="/cccl/latest/"' "${ROOT}/index.html"; then
    fail "the landing page must not depend on the latest/ alias existing"
else
    pass "the landing page does not depend on the alias"
fi
if grep -q '"default": "3.4"' "${ROOT}/404.html"; then
    pass "the 404 handler falls back to the concrete stable version"
else
    fail "the 404 handler should fall back to 3.4, not to the alias"
fi

# /latest/ is redirect stubs, not a copy: a duplicate of the stable build costs
# ~150 MB against a 1 GB GitHub Pages limit.
if grep -q 'http-equiv="refresh"' "${ROOT}/latest/index.html" \
   && grep -q '3.4/index.html' "${ROOT}/latest/index.html"; then
    pass "latest/ redirects to the stable build rather than copying it"
else
    fail "latest/index.html should be a redirect stub pointing at 3.4/"
fi
if [[ "$(wc -c < "${ROOT}/latest/index.html")" -lt 1000 ]]; then
    pass "the alias stub is small"
else
    fail "the alias stub should be a few hundred bytes, not a page copy"
fi
assert_file "the 404 helper is copied verbatim, not redirected" \
    "${ROOT}/latest/404_helper.html"
if grep -q 'http-equiv="refresh"' "${ROOT}/latest/404_helper.html"; then
    fail "404_helper.html must not be a redirect; it needs its query string"
else
    pass "404_helper.html keeps its own content so the query survives"
fi
assert_eq "root objects.inv comes from the stable build" \
    "objects-inv-for-3.4" "$(cat "${ROOT}/objects.inv")"
assert_eq "legacy versions.json stays consistent with the switcher" \
    "latest,unstable,3.4" \
    "$(json_query "${ROOT}/versions.json" '",".join(data)')"

# ---------------------------------------------------------------------------
start_case "An unstable build must not hijack latest/ or objects.inv"
# The regression that would quietly turn the stable docs into development docs.

make_version_build "${ROOT}" unstable
assemble "${ROOT}" unstable "${MANIFEST}"

if grep -q '3.4/index.html' "${ROOT}/latest/index.html"; then
    pass "latest/ still points at the stable build"
else
    fail "an unstable deploy repointed latest/ away from the stable build"
fi
# The alias is regenerated on every deploy, so what matters is not that it was
# left alone but that it was rebuilt pointing at the stable version rather than
# at whatever this deploy happened to build.
if grep -q 'unstable/index.html' "${ROOT}/latest/index.html"; then
    fail "an unstable deploy made latest/ serve the development docs"
else
    pass "latest/ never points at the development docs"
fi
assert_eq "root objects.inv still points at the stable build" \
    "objects-inv-for-3.4" "$(cat "${ROOT}/objects.inv")"
if grep -q 'href="/cccl/3.4/"' "${ROOT}/index.html"; then
    pass "landing page still points C++ at the stable version after an unstable deploy"
else
    fail "an unstable deploy changed where the landing page sends C++ readers"
fi

# The regression the live fork deploy caught: publishing a version other than
# latest_stable must still leave a root redirect that resolves, even though this
# build does not write the alias.
if [[ ! -d "${ROOT}/latest" ]]; then
    fail "precondition: this case expects no alias written by an unstable build"
else
    rm -rf "${ROOT}/latest"
    assemble "${ROOT}" unstable "${MANIFEST}"
    target="$(grep -oE 'href="/cccl/[^"/]+/"' "${ROOT}/index.html" | head -1 \
        | sed 's|href="/cccl/||;s|/"$||')"
    if [[ -d "${ROOT}/${target}" ]]; then
        pass "root redirect resolves even when the alias is absent"
    else
        fail "root redirects to '${target}/', which does not exist"
    fi
fi

# ---------------------------------------------------------------------------
start_case "Every build publishes the same version list"
# The property that makes an additive deploy safe: given the same published
# site, deploying 3.4 and deploying unstable must not disagree about which
# versions exist. Each deploy sees only its own build plus the published site,
# which is what the workflow supplies via CCCL_DOCS_PUBLISHED_SITE.

PUBLISHED_D="${WORK_DIR}/case_d_published"
make_version_build "${PUBLISHED_D}" unstable
make_version_build "${PUBLISHED_D}" 3.4

ROOT_STABLE="${WORK_DIR}/case_d_stable"
ROOT_UNSTABLE="${WORK_DIR}/case_d_unstable"
make_version_build "${ROOT_STABLE}" 3.4
make_version_build "${ROOT_UNSTABLE}" unstable
assemble "${ROOT_STABLE}" 3.4 "${MANIFEST}" "${PUBLISHED_D}"
assemble "${ROOT_UNSTABLE}" unstable "${MANIFEST}" "${PUBLISHED_D}"

for artifact in nv-versions.json versions.json index.html 404.html; do
    if cmp -s "${ROOT_STABLE}/${artifact}" "${ROOT_UNSTABLE}/${artifact}"; then
        pass "${artifact} is identical regardless of which version built it"
    else
        fail "${artifact} differs between a stable build and an unstable build"
    fi
done

# A newly built version is listed before it has been published anywhere.
ROOT_NEW="${WORK_DIR}/case_d_new"
make_version_build "${ROOT_NEW}" 3.5
assemble "${ROOT_NEW}" 3.5 "${MANIFEST}" "${PUBLISHED_D}"
assert_eq "a version being deployed is listed alongside published ones" \
    "unstable,3.5,3.4" \
    "$(json_query "${ROOT_NEW}/nv-versions.json" \
       '",".join(e["version"] for e in data if e["version"] != "latest")')"

# ---------------------------------------------------------------------------
start_case "C++ and Python are versioned independently"
# They ship on separate release lines, so each needs its own subtree, its own
# version list and its own switcher. C++ stays at the site root so that no
# existing documentation URL moves.

TWO="${WORK_DIR}/two_components"
TWO_MANIFEST="${WORK_DIR}/two_components.json"
write_manifest "${TWO_MANIFEST}" 3.4 1.1

make_version_build "${TWO}" unstable
make_version_build "${TWO}" 3.4
make_version_build "${TWO}/python" unstable
make_version_build "${TWO}/python" 1.1

assemble_component "${TWO}" cpp 3.4 "${TWO_MANIFEST}"
assemble_component "${TWO}" python 1.1 "${TWO_MANIFEST}"

assert_eq "C++ versions live at the site root" \
    "latest,unstable,3.4" \
    "$(json_query "${TWO}/nv-versions.json" '",".join(e["version"] for e in data)')"
assert_eq "Python versions live under python/" \
    "latest,unstable,1.1" \
    "$(json_query "${TWO}/python/nv-versions.json" '",".join(e["version"] for e in data)')"
assert_eq "the C++ switcher offers no Python version" \
    "0" "$(json_query "${TWO}/nv-versions.json" 'sum(e["version"] == "1.1" for e in data)')"
assert_eq "the Python switcher offers no C++ version" \
    "0" "$(json_query "${TWO}/python/nv-versions.json" 'sum(e["version"] == "3.4" for e in data)')"
assert_eq "Python switcher URLs are scoped to the component" \
    "https://nvidia.github.io/cccl/python/1.1/" \
    "$(json_query "${TWO}/python/nv-versions.json" '[e["url"] for e in data if e["version"]=="1.1"][0]')"
assert_eq "each component marks its own preferred version" \
    "3.4|1.1" \
    "$(json_query "${TWO}/nv-versions.json" '[e["version"] for e in data if e.get("preferred")][0]')|$(json_query "${TWO}/python/nv-versions.json" '[e["version"] for e in data if e.get("preferred")][0]')"

assert_file "Python gets its own /latest/ alias" "${TWO}/python/latest/index.html"
if grep -q '1.1/index.html' "${TWO}/python/latest/index.html"; then
    pass "the Python alias points at the Python stable version"
else
    fail "the Python alias should point at 1.1"
fi

# The landing page is the only thing at the site root that is not C++ content.
if grep -q 'href="/cccl/3.4/"' "${TWO}/index.html" \
   && grep -q 'href="/cccl/python/1.1/"' "${TWO}/index.html"; then
    pass "the landing page links to both components' current versions"
else
    fail "the landing page should link to both components"
fi

# One 404 handler serves the whole site, so it must know both namespaces, and
# must try the nested component before the one at the root.
assert_eq "the 404 router tries the nested component first" \
    "python" \
    "$(python3 -c "
import json, re, sys
html = open('${TWO}/404.html', encoding='utf-8').read()
routes = json.loads(re.search(r'COMPONENT_ROUTES = (\[.*?\]);', html, re.S).group(1))
print(routes[0]['path'])")"
assert_eq "the 404 router knows each component's fallback version" \
    "3.4,1.1" \
    "$(python3 -c "
import json, re
html = open('${TWO}/404.html', encoding='utf-8').read()
routes = json.loads(re.search(r'COMPONENT_ROUTES = (\[.*?\]);', html, re.S).group(1))
by_path = {r['path']: r['default'] for r in routes}
print(f\"{by_path['']},{by_path['python']}\")")"

# ---------------------------------------------------------------------------
start_case "Deploying one component refreshes the other's root"
# Setting a component's latest_stable and then deploying a *different* component
# used to leave the first advertising a /latest/ that was never built. A live
# deploy hit exactly this, and the post-deploy verification caught it.

CROSS_PUB="${WORK_DIR}/cross_published"
CROSS="${WORK_DIR}/cross"
CROSS_MANIFEST="${WORK_DIR}/cross.json"

# The published site: both components live, Python not yet marked stable.
write_manifest "${CROSS_MANIFEST}" 3.4
make_version_build "${CROSS_PUB}" 3.4
make_version_build "${CROSS_PUB}/python" 1.1
make_version_build "${CROSS_PUB}" unstable

# Now Python 1.1 is marked stable, and the next deploy is of C++.
write_manifest "${CROSS_MANIFEST}" 3.4 1.1
make_version_build "${CROSS}" unstable
assemble_component "${CROSS}" cpp unstable "${CROSS_MANIFEST}" "${CROSS_PUB}"

assert_file "the other component's alias is built from the published copy" \
    "${CROSS}/python/latest/index.html"
if grep -q '1.1/index.html' "${CROSS}/python/latest/index.html"; then
    pass "that alias points at the newly stable Python version"
else
    fail "the Python alias should point at 1.1"
fi
assert_file "the other component's switcher is refreshed" \
    "${CROSS}/python/nv-versions.json"
assert_eq "the refreshed switcher offers the published Python versions" \
    "latest,1.1" \
    "$(json_query "${CROSS}/python/nv-versions.json" '",".join(e["version"] for e in data)')"

# Refreshing must not drag the other component's page content into this deploy;
# only its small root files and alias stubs belong here.
assert_no_dir "the other component's version content is not copied in" \
    "${CROSS}/python/1.1"

# ---------------------------------------------------------------------------
start_case "Bad input is rejected instead of silently publishing broken links"

ROOT="${WORK_DIR}/case_e"
make_version_build "${ROOT}" unstable

# A latest_stable naming a version that is not published must not point the site
# root at a directory that 404s. Warn and fall back rather than failing, so an
# unrelated release is not blocked by a stale setting.
BAD="${WORK_DIR}/manifest_missing_latest.json"
write_manifest "${BAD}" 3.9
ROOT_MISSING="${WORK_DIR}/case_e_missing_latest"
make_version_build "${ROOT_MISSING}" unstable
if assemble "${ROOT_MISSING}" unstable "${BAD}"; then
    pass "an unpublished latest_stable does not fail the deploy"
else
    fail "an unpublished latest_stable should warn, not block the deploy"
fi
if grep -q 'href="/cccl/unstable/"' "${ROOT_MISSING}/index.html"; then
    pass "the landing page falls back to a version that exists"
else
    fail "the site root should fall back rather than point at an absent version"
fi
assert_eq "no latest entry is offered for an unpublished version" \
    "0" "$(json_query "${ROOT_MISSING}/nv-versions.json" \
           'sum(e["version"] == "latest" for e in data)')"

# A site root with no version directories at all means nothing was built.
assert_fails "a site with no version directories is rejected" \
    assemble "${WORK_DIR}/case_e_bare" unstable "${BAD}"

# A directory without a landing page is a partial upload; it must not be
# advertised, and it must not be mistaken for the version being deployed.
ROOT_PARTIAL="${WORK_DIR}/case_e_partial"
make_version_build "${ROOT_PARTIAL}" unstable
mkdir -p "${ROOT_PARTIAL}/3.2/sub"
echo "orphan" > "${ROOT_PARTIAL}/3.2/sub/page.html"
GOOD="${WORK_DIR}/manifest_ok.json"
write_manifest "${GOOD}" null
assemble "${ROOT_PARTIAL}" unstable "${GOOD}"
assert_eq "a version directory with no index.html is not advertised" \
    "unstable" \
    "$(json_query "${ROOT_PARTIAL}/nv-versions.json" '",".join(e["version"] for e in data)')"
assert_fails "assembling a version that was never built is rejected" \
    assemble "${WORK_DIR}/case_e_empty" 3.4 "${GOOD}"

# conf.py resolves `release` from SPHINX_CCCL_VER and otherwise falls back to
# VERSION.md, so an unset variable stamps pages with a version that no switcher
# entry matches. Publishing that silently is worse than failing.
ROOT_MISMATCH="${WORK_DIR}/case_e_mismatch"
make_version_build "${ROOT_MISMATCH}" unstable 3.6
assert_fails "pages stamped with a different version than they publish as are rejected" \
    assemble "${ROOT_MISMATCH}" unstable "${GOOD}"

# Releases before the version switcher existed stamp nothing. That is expected,
# not an error -- and under `set -o pipefail` a grep matching nothing would
# otherwise kill the script before it could say so.
ROOT_UNSTAMPED="${WORK_DIR}/case_e_unstamped"
mkdir -p "${ROOT_UNSTAMPED}/unstable"
echo "<html><body>a release with no switcher config</body></html>" \
    > "${ROOT_UNSTAMPED}/unstable/index.html"
if assemble "${ROOT_UNSTAMPED}" unstable "${GOOD}"; then
    pass "pages with no version_match at all are published, not rejected"
else
    fail "a build with no version_match should warn and continue"
fi
assert_file "the unstamped build still gets a site root" \
    "${ROOT_UNSTAMPED}/nv-versions.json"

# ---------------------------------------------------------------------------
start_case "The checked-in manifest is valid"

ROOT="${WORK_DIR}/case_f"
make_version_build "${ROOT}" unstable
CHECKED_IN="${SCRIPT_PATH}/published_versions.json"
if CCCL_DOCS_VERSIONS_FILE="${CHECKED_IN}" "${SCRIPT_PATH}/assemble_site.bash" \
        "${ROOT}" cpp unstable "https://nvidia.github.io/cccl/" > /dev/null; then
    pass "published_versions.json renders without error"
else
    fail "published_versions.json is not valid"
fi

assert_eq "the checked-in manifest declares both language components" \
    "cpp,python" \
    "$(json_query "${CHECKED_IN}" '",".join(c["id"] for c in data["components"])')"

# C++ must stay at the site root: it has been published there since before
# versioning existed, and moving it would break every working documentation URL.
assert_eq "C++ stays at the site root" \
    "" "$(json_query "${CHECKED_IN}" '[c["path"] for c in data["components"] if c["id"]=="cpp"][0]')"

for entry_dir in $(json_query "${CHECKED_IN}" \
        '" ".join(c.get("latest_stable") or "" for c in data["components"])'); do
    if [[ "${entry_dir}" =~ ^(unstable|[0-9]+\.[0-9]+)$ ]]; then
        pass "latest_stable '${entry_dir}' matches the published URL scheme"
    else
        fail "latest_stable '${entry_dir}' is not 'unstable' or MAJOR.MINOR"
    fi
done

# ---------------------------------------------------------------------------
start_case "Release refs map to the documented URL scheme"
# Mirrors version_dir_for_ref() in .github/workflows/docs-deploy.yml. Patch
# releases collapse into their minor directory; the ".x" of a release branch is
# a branching convention and must not appear in a URL.

version_dir_for_ref() {
    if [[ "$1" =~ ^v([0-9]+\.[0-9]+)\.[0-9]+$ ]]; then
        printf '%s' "${BASH_REMATCH[1]}"
    elif [[ "$1" =~ ^branch/([0-9]+\.[0-9]+)\.x$ ]]; then
        printf '%s' "${BASH_REMATCH[1]}"
    fi
}

if grep -qF 'version_dir_for_ref()' "${SCRIPT_PATH}/../.github/workflows/docs-deploy.yml"; then
    pass "the tested function is the one the workflow defines"
else
    fail "docs-deploy.yml no longer defines version_dir_for_ref; update this test"
fi

check_ref_mapping() {
    # <ref> <expected dir, or empty for "skip">
    assert_eq "${1} -> ${2:-<skipped>}" "${2}" "$(version_dir_for_ref "$1")"
}

# Release tags: every patch of a series shares one directory.
check_ref_mapping "v3.4.0" "3.4"
check_ref_mapping "v3.4.1" "3.4"
check_ref_mapping "v3.4.2" "3.4"
check_ref_mapping "v3.5.0" "3.5"
check_ref_mapping "v2.8.1" "2.8"
check_ref_mapping "v12.10.3" "12.10"
# Release branches remain resolvable for backfilling, without the ".x".
check_ref_mapping "branch/3.4.x" "3.4"
check_ref_mapping "branch/2.8.x" "2.8"
# Everything else is not a release and must not publish.
check_ref_mapping "v3.5.0-rc0" ""
check_ref_mapping "v3.6.0.dev" ""
check_ref_mapping "branch/testing" ""
check_ref_mapping "branch/test-backport" ""
check_ref_mapping "backport-10873-to-branch/3.5.x" ""
check_ref_mapping "main" ""

# ---------------------------------------------------------------------------
start_case "Removed documentation URLs are detected and reported"

write_pagelist() {
    # <path> <page...>   scrape_docs.bash emits comma-separated paths on one line
    local path="$1"
    shift
    printf '%s,' "$@" > "${path}"
    printf '\n' >> "${path}"
}

PAGES_DIR="${WORK_DIR}/pages"
mkdir -p "${PAGES_DIR}"
CHECK="${SCRIPT_PATH}/check_removed_pages.py"

write_pagelist "${PAGES_DIR}/baseline.txt" /index.html /thrust/api.html /cub/reduce.html
write_pagelist "${PAGES_DIR}/same.txt" /index.html /thrust/api.html /cub/reduce.html
write_pagelist "${PAGES_DIR}/moved.txt" /index.html /users/how-to/reduce.html
write_pagelist "${PAGES_DIR}/grown.txt" \
    /index.html /thrust/api.html /cub/reduce.html /cub/scan.html

report="$(python3 "${CHECK}" --current "${PAGES_DIR}/same.txt" \
    --baseline "${PAGES_DIR}/baseline.txt")"
if [[ "${report}" == *"No documentation URLs are removed"* ]]; then
    pass "an unchanged page list reports no removals"
else
    fail "an unchanged page list should report no removals"
fi

# The restructure case: pages move, so old URLs disappear.
report="$(python3 "${CHECK}" --current "${PAGES_DIR}/moved.txt" \
    --baseline "${PAGES_DIR}/baseline.txt")"
assert_eq "a restructure reports every removed URL" \
    "2" "$(grep -c '^- `/' <<< "${report}")"
bt='`'  # the report wraps paths in backticks for Markdown
if [[ "${report}" == *"${bt}/thrust/api.html${bt}"* \
   && "${report}" == *"${bt}/cub/reduce.html${bt}"* ]]; then
    pass "removed URLs are named individually"
else
    fail "removed URLs should be named individually"
fi
if [[ "${report}" == *"1 new page(s) added"* ]]; then
    pass "newly added pages are counted"
else
    fail "newly added pages should be counted"
fi

report="$(python3 "${CHECK}" --current "${PAGES_DIR}/grown.txt" \
    --baseline "${PAGES_DIR}/baseline.txt")"
if [[ "${report}" == *"No documentation URLs are removed"* ]]; then
    pass "adding pages without removing any reports no removals"
else
    fail "adding pages should not report removals"
fi

# Advisory by default, so a restructure is never blocked by this check alone.
if python3 "${CHECK}" --current "${PAGES_DIR}/moved.txt" \
        --baseline "${PAGES_DIR}/baseline.txt" > /dev/null; then
    pass "removals are advisory by default"
else
    fail "removals should not fail the check by default"
fi
assert_fails "--strict turns removals into a failure" \
    python3 "${CHECK}" --current "${PAGES_DIR}/moved.txt" \
    --baseline "${PAGES_DIR}/baseline.txt" --strict

# A missing baseline means the docs were never published, which must not fail CI.
if python3 "${CHECK}" --current "${PAGES_DIR}/same.txt" \
        --baseline "${PAGES_DIR}/does-not-exist.txt" > /dev/null; then
    pass "an unreachable baseline is skipped rather than failing"
else
    fail "an unreachable baseline should be skipped, not fatal"
fi

# ---------------------------------------------------------------------------
start_case "Changing latest_stable repoints /latest/ without republishing it"
# The alias used to be written only by a deploy of latest_stable, so promoting a
# new release left /latest/ pointing at the previous one -- serving the wrong
# version silently, while the switcher claimed it was current.

PROMO="${WORK_DIR}/promotion"
PUBLISHED="${WORK_DIR}/promotion_published"
make_version_build "${PROMO}" 3.4
make_version_build "${PROMO}" 3.5
make_version_build "${PROMO}" unstable

M_OLD="${WORK_DIR}/promo_old.json"
write_manifest "${M_OLD}" 3.4
assemble "${PROMO}" 3.4 "${M_OLD}"
if grep -q '3.4/index.html' "${PROMO}/latest/index.html"; then
    pass "latest/ points at the stable version it was built for"
else
    fail "latest/ should point at 3.4"
fi

# Simulate the published site as it now stands, then promote 3.5 and deploy
# something unrelated -- the sequence that used to leave the alias stale.
rm -rf "${PUBLISHED}"; cp -r "${PROMO}" "${PUBLISHED}"
M_NEW="${WORK_DIR}/promo_new.json"
write_manifest "${M_NEW}" 3.5

CCCL_DOCS_PUBLISHED_SITE="${PUBLISHED}" CCCL_DOCS_VERSIONS_FILE="${M_NEW}" \
    "${SCRIPT_PATH}/assemble_site.bash" "${PROMO}" cpp unstable "https://nvidia.github.io/cccl/" \
    > /dev/null

if grep -q '3.5/index.html' "${PROMO}/latest/index.html"; then
    pass "deploying an unrelated version still repoints latest/ at the new stable"
else
    fail "latest/ still points at the old stable after promotion"
fi
assert_eq "the switcher and the alias agree on which version is latest" \
    "3.5" \
    "$(json_query "${PROMO}/nv-versions.json" '[e["version"] for e in data if e.get("preferred")][0]')"

# Nested pages must be repointed too, not just the landing page.
if grep -q '3.5/sub/page.html' "${PROMO}/latest/sub/page.html"; then
    pass "nested alias stubs are repointed as well"
else
    fail "nested alias stubs still point at the old version"
fi

# With no copy of the stable version anywhere, the deploy must still succeed.
NOCOPY="${WORK_DIR}/promotion_nocopy"
make_version_build "${NOCOPY}" unstable
if CCCL_DOCS_VERSIONS_FILE="${M_NEW}" \
        "${SCRIPT_PATH}/assemble_site.bash" "${NOCOPY}" cpp unstable \
        "https://nvidia.github.io/cccl/" > /dev/null 2>&1; then
    pass "a deploy proceeds when the stable version is not available to mirror"
else
    fail "an unavailable stable version should warn, not block the deploy"
fi

# ---------------------------------------------------------------------------
start_case "Builds from releases predating versioning are reshaped"
# v3.3.4 and earlier build a flat tree with no version directory and no page
# list. Backfilling them must not require backporting the build script.

NORMALIZE="${SCRIPT_PATH}/normalize_build_layout.bash"

FLAT="${WORK_DIR}/flat"
mkdir -p "${FLAT}/cub" "${FLAT}/_static"
echo "<html>flat index</html>" > "${FLAT}/index.html"
echo "<html>cub page</html>" > "${FLAT}/cub/index.html"
echo "css" > "${FLAT}/_static/theme.css"
touch "${FLAT}/.nojekyll"

"${NORMALIZE}" "${FLAT}" 3.3 > /dev/null

assert_file "a flat build is nested under its version" "${FLAT}/3.3/index.html"
assert_file "nested subdirectories are preserved" "${FLAT}/3.3/cub/index.html"
assert_file "dotfiles move too" "${FLAT}/3.3/.nojekyll"
assert_file "a page list is generated for the 404 handler" "${FLAT}/3.3/pagelist.txt"
if grep -q '/cub/index.html' "${FLAT}/3.3/pagelist.txt"; then
    pass "the generated page list covers nested pages"
else
    fail "the generated page list should cover nested pages"
fi
assert_no_dir "nothing is left at the old top level" "${FLAT}/_static"

# Re-running must not nest an already-nested build a second time.
"${NORMALIZE}" "${FLAT}" 3.3 > /dev/null
assert_no_dir "re-running does not double-nest" "${FLAT}/3.3/3.3"
assert_file "the build survives a second run" "${FLAT}/3.3/index.html"

# A modern build already has both, so nothing should change.
MODERN="${WORK_DIR}/modern"
make_version_build "${MODERN}" 3.4
before="$(cat "${MODERN}/3.4/pagelist.txt")"
"${NORMALIZE}" "${MODERN}" 3.4 > /dev/null
assert_eq "a modern build is left untouched" "${before}" "$(cat "${MODERN}/3.4/pagelist.txt")"

assert_fails "an empty build directory is rejected" \
    "${NORMALIZE}" "${WORK_DIR}/nonexistent" 3.3

# ---------------------------------------------------------------------------
start_case "Releases predating the switcher get one added"
# Without this, a reader arriving on a pre-3.4 page from a search result has no
# dropdown, so no way to discover that newer documentation exists.

BACKPORT="${SCRIPT_PATH}/backport_switcher_config.py"
CONF_DIR="${WORK_DIR}/backport"
mkdir -p "${CONF_DIR}"
echo "3.3" > "${CONF_DIR}/VERSION.md"

# A pre-3.4 conf.py: same theme and navbar as 3.4, no switcher block.
cat > "${CONF_DIR}/conf.py" <<'EOF'
release = "3.3"
html_theme = "nvidia_sphinx_theme"
html_theme_options = {
    "navigation_depth": 4,
    "navbar_end": ["theme-switcher", "navbar-icon-links"],
}
EOF

python3 "${BACKPORT}" --conf-py "${CONF_DIR}/conf.py" > /dev/null
switcher="$(cd "${CONF_DIR}" && CCCL_DOCS_BASE_URL="https://nvidia.github.io/cccl/" \
    SPHINX_CCCL_VER="3.3" python3 -c "
import runpy
ns = runpy.run_path('conf.py')
s = ns['html_theme_options']['switcher']
print(f\"{s['version_match']}|{s['json_url']}|{ns['html_baseurl']}\")")"

assert_eq "the patched config declares the publish directory as version_match" \
    "3.3" "$(cut -d'|' -f1 <<< "${switcher}")"
assert_eq "the switcher points at the site-root manifest" \
    "https://nvidia.github.io/cccl/nv-versions.json" "$(cut -d'|' -f2 <<< "${switcher}")"
assert_eq "html_baseurl follows the deploy's base URL" \
    "https://nvidia.github.io/cccl/" "$(cut -d'|' -f3 <<< "${switcher}")"

# version_match must track the publish directory, not the release's own idea of
# its version, or assemble_site.bash will refuse to publish the build.
alt="$(cd "${CONF_DIR}" && CCCL_DOCS_BASE_URL="https://x/" SPHINX_CCCL_VER="9.9" \
    python3 -c "
import runpy
print(runpy.run_path('conf.py')['html_theme_options']['switcher']['version_match'])")"
assert_eq "version_match follows SPHINX_CCCL_VER when it differs" "9.9" "${alt}"

# Running twice must not append the block again.
python3 "${BACKPORT}" --conf-py "${CONF_DIR}/conf.py" > /dev/null
assert_eq "the block is added exactly once" \
    "1" "$(grep -c 'appended by the CCCL docs deploy' "${CONF_DIR}/conf.py")"

# A release that already configures a switcher is left completely alone.
MODERN_CONF="${WORK_DIR}/backport_modern"
mkdir -p "${MODERN_CONF}"
cat > "${MODERN_CONF}/conf.py" <<'EOF'
release = "3.4"
html_theme_options = {"switcher": {"json_url": "x", "version_match": release}}
EOF
before="$(cat "${MODERN_CONF}/conf.py")"
python3 "${BACKPORT}" --conf-py "${MODERN_CONF}/conf.py" > /dev/null
assert_eq "a release that already has a switcher is untouched" \
    "${before}" "$(cat "${MODERN_CONF}/conf.py")"

assert_fails "a config without html_theme_options is rejected rather than broken" \
    python3 "${BACKPORT}" --conf-py "${WORK_DIR}/VERSION.md"

# ---------------------------------------------------------------------------
start_case "Old releases stop bundling the Python docs"
# A release tagged before the split still lists python/index in its toctree, so
# rebuilding it would publish Python pages under a C++ version number.

UNBUNDLE="${SCRIPT_PATH}/unbundle_python_docs.py"
REL="${WORK_DIR}/old_release"
mkdir -p "${REL}"
cat > "${REL}/index.rst" <<'EOF'
CUDA Core Compute Libraries
===========================

.. toctree::
   :hidden:
   :maxdepth: 3

   cpp
   python/index
   maintainers/index

Welcome.

- :ref:`cccl-cpp-libraries`

- :doc:`Python Libraries <python/index>`

- :doc:`Maintainer Docs <maintainers/index>`
EOF
cat > "${REL}/conf.py" <<'EOF'
exclude_patterns = [
    "_build",
]
EOF

python3 "${UNBUNDLE}" --docs-dir "${REL}" > /dev/null

if grep -q "python/index" "${REL}/index.rst"; then
    fail "the Python toctree entry and link should both be gone"
else
    pass "the Python toctree entry and link are removed"
fi
if grep -q "cpp" "${REL}/index.rst" && grep -q "maintainers/index" "${REL}/index.rst"; then
    pass "the other toctree entries survive"
else
    fail "unrelated toctree entries must not be removed"
fi
if grep -qE '^\s*"python",' "${REL}/conf.py"; then
    pass "the python directory is excluded from the build"
else
    fail "conf.py should exclude the python directory"
fi
# The two are separate sites, reached from the landing page; the C++ docs make
# no mention of Python at all.
if grep -qi "python" "${REL}/index.rst"; then
    fail "the C++ index should not mention Python once unbundled"
else
    pass "no reference to Python is left in the C++ index"
fi

# Running twice must not duplicate the exclusion.
python3 "${UNBUNDLE}" --docs-dir "${REL}" > /dev/null
assert_eq "the exclusion is added exactly once" \
    "1" "$(grep -cE '^\s*"python",' "${REL}/conf.py")"

# A release that already keeps them separate is left alone.
MODERN_REL="${WORK_DIR}/modern_release"
mkdir -p "${MODERN_REL}"
printf 'Title\n=====\n\n.. toctree::\n\n   cpp\n' > "${MODERN_REL}/index.rst"
printf 'exclude_patterns = [\n    "python",\n]\n' > "${MODERN_REL}/conf.py"
before_index="$(cat "${MODERN_REL}/index.rst")"
python3 "${UNBUNDLE}" --docs-dir "${MODERN_REL}" > /dev/null
assert_eq "a release without the Python tree is untouched" \
    "${before_index}" "$(cat "${MODERN_REL}/index.rst")"

assert_fails "a docs dir with no conf.py is rejected" \
    python3 "${UNBUNDLE}" --docs-dir "${WORK_DIR}"

# ---------------------------------------------------------------------------
start_case "A published site is verified before history is compacted"
# The compaction workflow force-pushes an orphan commit, so this check is the
# interlock standing between a maintenance job and an outage.

VERIFY="${SCRIPT_PATH}/verify_published_site.py"
VROOT="${WORK_DIR}/verify"
VMANIFEST="${WORK_DIR}/verify_manifest.json"
write_manifest "${VMANIFEST}" 3.4
make_version_build "${VROOT}" 3.4
make_version_build "${VROOT}" unstable
assemble "${VROOT}" 3.4 "${VMANIFEST}"

if python3 "${VERIFY}" --site-root "${VROOT}" --manifest "${VMANIFEST}" > /dev/null; then
    pass "a complete site passes verification"
else
    fail "a complete site should pass verification"
fi

# Each of these would be silently baked in permanently by a force-push.
rm -rf "${WORK_DIR}/verify_broken"
cp -r "${VROOT}" "${WORK_DIR}/verify_broken"
rm -rf "${WORK_DIR}/verify_broken/3.4"
assert_fails "a missing version directory is caught" \
    python3 "${VERIFY}" --site-root "${WORK_DIR}/verify_broken" --manifest "${VMANIFEST}"

rm -rf "${WORK_DIR}/verify_broken"
cp -r "${VROOT}" "${WORK_DIR}/verify_broken"
rm -rf "${WORK_DIR}/verify_broken/latest"
assert_fails "a missing latest/ alias is caught" \
    python3 "${VERIFY}" --site-root "${WORK_DIR}/verify_broken" --manifest "${VMANIFEST}"

rm -rf "${WORK_DIR}/verify_broken"
cp -r "${VROOT}" "${WORK_DIR}/verify_broken"
rm -f "${WORK_DIR}/verify_broken/nv-versions.json"
assert_fails "a missing switcher manifest is caught" \
    python3 "${VERIFY}" --site-root "${WORK_DIR}/verify_broken" --manifest "${VMANIFEST}"

rm -rf "${WORK_DIR}/verify_broken"
cp -r "${VROOT}" "${WORK_DIR}/verify_broken"
cp "${SCRIPT_PATH}/landing.html" "${WORK_DIR}/verify_broken/index.html"
assert_fails "an unrendered template is caught" \
    python3 "${VERIFY}" --site-root "${WORK_DIR}/verify_broken" --manifest "${VMANIFEST}"

rm -rf "${WORK_DIR}/verify_broken"
cp -r "${VROOT}" "${WORK_DIR}/verify_broken"
make_version_build "${WORK_DIR}/verify_broken" 3.3
assert_fails "a version published but absent from the manifest is caught" \
    python3 "${VERIFY}" --site-root "${WORK_DIR}/verify_broken" --manifest "${VMANIFEST}"

# ---------------------------------------------------------------------------
echo
if [[ "${FAILURES}" -eq 0 ]]; then
    echo "All documentation versioning tests passed."
else
    echo "${FAILURES} test(s) failed." >&2
    exit 1
fi
