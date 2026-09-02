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
    # <path> <latest_stable-or-null> <version-dirs...>
    local path="$1"
    local latest="$2"
    shift 2
    python3 -c '
import json
import sys

path, latest = sys.argv[1], sys.argv[2]
dirs = sys.argv[3:]
manifest = {
    "latest_stable": None if latest == "null" else latest,
    "versions": [{"dir": d, "label": d} for d in dirs],
}
with open(path, "w", encoding="utf-8") as f:
    json.dump(manifest, f, indent=2)
' "${path}" "${latest}" "$@"
}

assemble() {
    # <site_root> <version> <manifest>
    CCCL_DOCS_VERSIONS_FILE="$3" "${SCRIPT_PATH}/assemble_site.bash" \
        "$1" "$2" "https://nvidia.github.io/cccl/" > /dev/null
}

# ---------------------------------------------------------------------------
start_case "Day one: only unstable published, no stable release yet"
# This is the state the checked-in manifest ships in, so it is also an assertion
# that merging this change does not move any URL that exists today.

ROOT="${WORK_DIR}/case_a"
MANIFEST="${WORK_DIR}/manifest_a.json"
write_manifest "${MANIFEST}" null unstable
make_version_build "${ROOT}" unstable
assemble "${ROOT}" unstable "${MANIFEST}"

assert_eq "switcher lists exactly one version" \
    "1" "$(json_query "${ROOT}/nv-versions.json" 'len(data)')"
assert_eq "that version is unstable" \
    "unstable" "$(json_query "${ROOT}/nv-versions.json" 'data[0]["version"]')"
assert_eq "no version is marked preferred while none is stable" \
    "0" "$(json_query "${ROOT}/nv-versions.json" 'sum("preferred" in e for e in data)')"

if grep -q 'url=unstable/' "${ROOT}/index.html"; then
    pass "site root still redirects to unstable/ (today's behavior preserved)"
else
    fail "site root should redirect to unstable/ when no stable version exists"
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
write_manifest "${MANIFEST}" 3.4 unstable 3.4
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
if grep -q 'url=3.4/' "${ROOT}/index.html"; then
    pass "site root redirects to the concrete stable version"
else
    fail "site root should redirect to 3.4/, not to the latest/ alias"
fi
if grep -q 'url=latest/' "${ROOT}/index.html"; then
    fail "site root must not depend on the latest/ alias existing"
else
    pass "site root does not depend on the alias"
fi
if grep -q 'DEFAULT_VERSION = "3.4"' "${ROOT}/404.html"; then
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
echo "sentinel" > "${ROOT}/latest/sentinel.txt"
assemble "${ROOT}" unstable "${MANIFEST}"

if grep -q '3.4/index.html' "${ROOT}/latest/index.html"; then
    pass "latest/ still points at the stable build"
else
    fail "an unstable deploy repointed latest/ away from the stable build"
fi
assert_file "latest/ was not rebuilt from scratch" "${ROOT}/latest/sentinel.txt"
assert_eq "root objects.inv still points at the stable build" \
    "objects-inv-for-3.4" "$(cat "${ROOT}/objects.inv")"
if grep -q 'url=3.4/' "${ROOT}/index.html"; then
    pass "site root still points at the stable version after an unstable deploy"
else
    fail "an unstable deploy changed the site root redirect"
fi

# The regression the live fork deploy caught: publishing a version other than
# latest_stable must still leave a root redirect that resolves, even though this
# build does not write the alias.
if [[ ! -d "${ROOT}/latest" ]]; then
    fail "precondition: this case expects no alias written by an unstable build"
else
    rm -rf "${ROOT}/latest"
    assemble "${ROOT}" unstable "${MANIFEST}"
    target="$(grep -o 'url=[^"]*' "${ROOT}/index.html" | head -1 | sed 's|url=||;s|/$||')"
    if [[ -d "${ROOT}/${target}" ]]; then
        pass "root redirect resolves even when the alias is absent"
    else
        fail "root redirects to '${target}/', which does not exist"
    fi
fi

# ---------------------------------------------------------------------------
start_case "Every build publishes the same version list"
# This is the property that makes an additive deploy safe: publishing 3.4 and
# publishing unstable must not disagree about which versions exist.

ROOT_STABLE="${WORK_DIR}/case_d_stable"
ROOT_UNSTABLE="${WORK_DIR}/case_d_unstable"
make_version_build "${ROOT_STABLE}" 3.4
make_version_build "${ROOT_UNSTABLE}" unstable
assemble "${ROOT_STABLE}" 3.4 "${MANIFEST}"
assemble "${ROOT_UNSTABLE}" unstable "${MANIFEST}"

for artifact in nv-versions.json versions.json index.html 404.html; do
    if cmp -s "${ROOT_STABLE}/${artifact}" "${ROOT_UNSTABLE}/${artifact}"; then
        pass "${artifact} is identical regardless of which version built it"
    else
        fail "${artifact} differs between a stable build and an unstable build"
    fi
done

# ---------------------------------------------------------------------------
start_case "Bad input is rejected instead of silently publishing broken links"

ROOT="${WORK_DIR}/case_e"
make_version_build "${ROOT}" unstable

BAD="${WORK_DIR}/manifest_missing_latest.json"
write_manifest "${BAD}" 3.9 unstable
assert_fails "latest_stable that names an unpublished version is rejected" \
    assemble "${ROOT}" unstable "${BAD}"

BAD="${WORK_DIR}/manifest_duplicate.json"
write_manifest "${BAD}" null unstable 3.4 3.4
assert_fails "duplicate version directories are rejected" \
    assemble "${ROOT}" unstable "${BAD}"

BAD="${WORK_DIR}/manifest_empty.json"
write_manifest "${BAD}" null
assert_fails "an empty version list is rejected" \
    assemble "${ROOT}" unstable "${BAD}"

GOOD="${WORK_DIR}/manifest_ok.json"
write_manifest "${GOOD}" null unstable
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
        "${ROOT}" unstable "https://nvidia.github.io/cccl/" > /dev/null; then
    pass "published_versions.json renders without error"
else
    fail "published_versions.json is not valid"
fi

for entry_dir in $(json_query "${CHECKED_IN}" '" ".join(v["dir"] for v in data["versions"])'); do
    if [[ "${entry_dir}" =~ ^(unstable|[0-9]+\.[0-9]+)$ ]]; then
        pass "version directory '${entry_dir}' matches the published URL scheme"
    else
        fail "version directory '${entry_dir}' is not 'unstable' or MAJOR.MINOR"
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
start_case "A published site is verified before history is compacted"
# The compaction workflow force-pushes an orphan commit, so this check is the
# interlock standing between a maintenance job and an outage.

VERIFY="${SCRIPT_PATH}/verify_published_site.py"
VROOT="${WORK_DIR}/verify"
VMANIFEST="${WORK_DIR}/verify_manifest.json"
write_manifest "${VMANIFEST}" 3.4 unstable 3.4
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
cp "${SCRIPT_PATH}/index.html" "${WORK_DIR}/verify_broken/index.html"
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
