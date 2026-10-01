#!/usr/bin/env bash

# Build the development documentation for both components.
#
# Mirrors cuda-python's build_all_docs.sh: it runs each component's own build in
# unstable-only mode and adds the files that belong to the site as a whole rather
# than to either component.
#
# Usage:
#   ./gen_all_docs.bash [--allow-dep-install]
#
# Result, which is exactly what gets deployed onto gh-pages:docs/ :
#
#   _build/artifacts/docs/
#     index.html            neutral C++ / Python chooser
#     .nojekyll
#     cpp/index.html        redirect to unstable/
#     cpp/unstable/         C++ development documentation
#     cpp/nv-versions.json
#     cpp/objects.inv
#     python/index.html     redirect to unstable/
#     python/unstable/      Python development documentation
#     python/nv-versions.json
#     python/objects.inv
#
# This wrapper is for main. A release publishes one component and calls that
# component's build directly, so it never touches the other component or the
# shared shell.

set -euo pipefail

SCRIPT_PATH=$(cd "$(dirname "${0}")"; pwd -P)
cd "$SCRIPT_PATH"

ARTIFACTS="_build/artifacts/docs"

# Both unstable trees come from this one invocation, so they are always built from
# the same commit. Their releases remain independent; only development
# documentation is coupled, because a single push advances both.
./gen_docs.bash unstable-only "$@"
./gen_python_docs.bash unstable-only "$@"

# The site shell. It belongs to neither component, so a component release never
# supplies it -- which is what stops a release rewriting what every reader first
# sees.
cp "${SCRIPT_PATH}/index.html" "${ARTIFACTS}/index.html"

# Without this, GitHub Pages runs Jekyll over the branch and drops
# underscore-prefixed directories -- taking _static/ with them. Every HTML route
# still returns 200 while the styles and the version switcher are gone, so a
# page-level smoke check cannot see the failure.
touch "${ARTIFACTS}/.nojekyll"

echo
echo "Combined development artifact: ${ARTIFACTS}"
find "${ARTIFACTS}" -maxdepth 2 -mindepth 1 \( -name '*.json' -o -name '*.html' -o -name '.nojekyll' -o -type d \) \
  | sed "s|${ARTIFACTS}|  docs|" | sort
