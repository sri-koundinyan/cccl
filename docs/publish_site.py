#!/usr/bin/env python3
"""Make a published documentation site internally consistent.

Usage:
    publish_site.py <site_root> [--base-url URL] [--verify]

``site_root`` is the directory that becomes the published site -- normally a
checkout of the ``gh-pages`` branch with one freshly built version copied into
place. This script is deliberately **not told what changed**. It walks the tree,
sees which components and versions are actually there, and writes every derived
file so that the result describes itself accurately.

That inversion is the whole design. A script told "I just built cpp 3.4" cannot
see the Python component, so it needs a second checkout to find it and a loop to
re-render it. A script handed the tree has no such category as "the other
components" -- everything is a directory it walks.

What it writes, per component:

* ``nv-versions.json`` / ``versions.json`` -- the version switcher manifests
* ``index.html`` -- for a nested component, a redirect to its default version
* ``latest/`` -- redirect stubs pointing at the newest published release
* ``objects.inv`` -- copied from the newest release, for intersphinx consumers

and once, at the site root: the landing page and the single 404 handler that
GitHub Pages allows for the whole site.

Nothing here is declared that can be observed. Versions are discovered from the
directories that exist; the version a reader lands on by default is the newest
release published. The only hand-maintained data is ``COMPONENTS`` below.
"""

import argparse
import json
import os
import re
import shutil
import sys
import urllib.parse
from pathlib import Path

# --------------------------------------------------------------------------
# The only hand-maintained configuration.
# --------------------------------------------------------------------------

# The C++ libraries and the Python package ship on independent release lines --
# CCCL is on 3.x while cuda-cccl is on its own -- so each gets its own subtree
# and its own version switcher. A reader picks one from the landing page.
#
# C++ deliberately sits at the site root (empty path): it has been published
# there since before versioning existed, and moving it would break every
# documentation URL that currently works.
COMPONENTS = [
    {
        "id": "cpp",
        "label": "C++",
        "path": "",
        "description": "Thrust, CUB, libcu++ and CUDA Experimental",
    },
    {
        "id": "python",
        "label": "Python",
        "path": "python",
        "description": "cuda.compute and cuda.coop",
    },
]

# Which release readers land on by default is normally the newest one published.
# Set this only to deliberately hold readers on an older release -- e.g. a bad
# release shipped and deleting its directory is too heavy a remedy.
#
#     LATEST_STABLE_OVERRIDE = {"cpp": "3.4"}
#
# A version named here that is not actually published is ignored with a warning,
# rather than pointing readers at a 404.
LATEST_STABLE_OVERRIDE = None

# How many release directories to keep per component, newest first. The
# development tip is always kept and does not count.
#
# This is the real constraint on the whole scheme. A built C++ version measures
# roughly 170 MB against GitHub Pages' 1 GB limit, and CCCL ships minor releases
# several times a year, so without a bound the site fills up in about a year and
# every release after that fails until someone intervenes. Retiring the oldest
# automatically keeps that from becoming a decision forced at release time.
#
# Python builds are ~1.5 MB, so its history is effectively free; the number is
# generous there for the same reason it is tight for C++.
KEEP_RELEASES = {
    "cpp": int(os.environ.get("CCCL_KEEP_RELEASES_CPP", "3")),
    "python": int(os.environ.get("CCCL_KEEP_RELEASES_PYTHON", "8")),
}
DEFAULT_KEEP_RELEASES = 3

# GitHub Pages refuses to publish a site larger than 1 GB. With retirement doing
# the real work this is a backstop, not the mechanism: it catches the case where
# versions are unusually large rather than unusually numerous.
SIZE_BUDGET_BYTES = 900 * 1024 * 1024

# A published version directory: the development tip, or a release line. Release
# docs are kept per MAJOR.MINOR rather than per patch because the size budget
# cannot accommodate one directory per patch; the exact patch that built a
# directory is carried in its label instead. See RELEASE_LABEL_FILE.
VERSION_DIR = re.compile(r"^(?:unstable|[0-9]+\.[0-9]+)$")

# Written into a version directory at publish time, holding the full version of
# the release that produced it ("3.4.2" in a directory named "3.4"). The switcher
# matches on the directory name and displays this, which is how readers get
# patch-level precision without a directory per patch.
RELEASE_LABEL_FILE = ".release"

# Sphinx stamps this into every page. It is what the switcher compares against a
# manifest entry's "version" to decide which entry to highlight.
VERSION_MATCH = re.compile(r"version_match\s*=\s*'([^']*)'")

# The routing data the site-wide 404 handler reads, carried in a JSON <script>
# block so the checked-in template is valid and usable before substitution.
ROUTING_BLOCK = re.compile(
    r'(<script type="application/json" id="site-routing">).*?(</script>)',
    re.DOTALL,
)

DEFAULT_BASE_URL = "https://nvidia.github.io/cccl/"


# --------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------


def sort_key(version):
    """Order versions newest-first, with the development tip always leading.

    Compared as numeric tuples rather than as strings: lexicographically "3.9"
    sorts after "3.10", and "4.0" lands in the wrong place entirely.
    """
    if version == "unstable":
        return (0,)
    return (1, tuple(-int(part) for part in version.split(".")))


def discover_versions(component_root):
    """List the versions actually published under a component.

    A directory counts only once it contains an ``index.html``, so a failed or
    partial upload is never advertised in the switcher.
    """
    if not component_root.is_dir():
        return []

    found = [
        entry.name
        for entry in component_root.iterdir()
        if entry.is_dir()
        and VERSION_DIR.match(entry.name)
        and (entry / "index.html").is_file()
    ]
    return sorted(found, key=sort_key)


def retire_old_releases(component_root, component_id, versions):
    """Delete release directories beyond the keep-count, oldest first.

    Deleting here rather than on the published branch is what makes retirement
    work at all: the tree being assembled is the complete desired state of the
    site, so a directory removed from it is removed from the published site by
    the same deploy that adds the new release. There is no separate cleanup
    step to run, forget, or get wrong.

    Only releases are considered. The development tip is never retired.
    """
    keep = KEEP_RELEASES.get(component_id, DEFAULT_KEEP_RELEASES)
    releases = [v for v in versions if v != "unstable"]

    if len(releases) <= keep:
        return versions

    # `versions` is already newest-first, so the tail is the oldest.
    retire = releases[keep:]

    # Never retire a version readers are deliberately pinned to. The override
    # exists to hold people off a bad release; retiring its target would delete
    # the safe version and move everyone onto the release they were being
    # protected from -- the exact opposite of what was asked for.
    pinned = (LATEST_STABLE_OVERRIDE or {}).get(component_id)
    if pinned in retire:
        retire.remove(pinned)
        print(
            f"  keeping {component_id} {pinned} past the retention limit:"
            " readers are pinned to it"
        )

    if not retire:
        return versions

    for version in retire:
        directory = component_root / version
        print(
            f"  retiring {component_id} {version} (keeping the newest {keep} releases)"
        )
        if directory.is_dir():
            shutil.rmtree(directory)

    return [v for v in versions if v not in set(retire)]


def release_label(version_dir):
    """The version to display for a directory: the exact release that built it.

    The label is the one thing readers see that is not checked against anything
    else -- the directory name is verified against what Sphinx stamped into the
    pages, but a label is just a string in a file. An unchecked label can claim
    a directory is any version at all, which is a worse lie than having no label,
    so it must be consistent with the directory it describes: "3.4" may be
    labelled "3.4" or "3.4.2", never "3.5.0" or "9.9.9".

    Falls back to the directory name, so a version published before this file
    existed still gets a sensible label rather than nothing.
    """
    label_file = version_dir / RELEASE_LABEL_FILE
    if label_file.is_file():
        label = label_file.read_text(encoding="utf-8").strip()
        if label:
            if label != version_dir.name and not label.startswith(
                version_dir.name + "."
            ):
                raise SystemExit(
                    f"error: {version_dir / RELEASE_LABEL_FILE} says {label!r},"
                    f" which is not a release of {version_dir.name!r}.\n"
                    "       The switcher would show readers a version number"
                    " this directory does not\n"
                    "       contain. Republish the version, or correct the"
                    " label."
                )
            return label
    return version_dir.name


def stamped_version(version_dir):
    """The version Sphinx baked into the built pages, or None if absent."""
    index = version_dir / "index.html"
    if not index.is_file():
        return None
    match = VERSION_MATCH.search(index.read_text(encoding="utf-8", errors="replace"))
    return match.group(1) if match else None


def latest_stable(component_id, versions):
    """The newest published release, or None if only the tip is published.

    Publishing is monotonic -- backfilling was a one-time setup step, and from
    here releases are published newest-first and old ones retired -- so the
    newest published release is always the one readers should land on. Deriving
    it means publishing a release promotes it, with nothing to edit.
    """
    releases = [v for v in versions if v != "unstable"]

    override = (LATEST_STABLE_OVERRIDE or {}).get(component_id)
    if override:
        if override in releases:
            return override
        print(
            f"  warning: LATEST_STABLE_OVERRIDE names {component_id} {override!r},"
            " which is not published; falling back to the newest release",
            file=sys.stderr,
        )

    return releases[0] if releases else None


# --------------------------------------------------------------------------
# Consistency checks
# --------------------------------------------------------------------------


def check_version_match(component_root, versions):
    """Fail if a version's pages disagree with the directory serving them.

    The switcher highlights the reader's current version by comparing the stamp
    Sphinx baked into the page against the manifest. If the two drift apart the
    dropdown silently stops working, so this is checked rather than trusted --
    and checked for every published version, not only the one just built.

    A version published before the switcher existed stamps nothing at all, which
    is expected and not an error.
    """
    for version in versions:
        stamped = stamped_version(component_root / version)
        if stamped is None:
            print(f"  {version}: no version_match stamped; skipping check")
        elif stamped != version:
            raise SystemExit(
                f"error: pages in {component_root / version} declare"
                f" version_match {stamped!r} but are served as {version!r}.\n"
                "       The switcher cannot highlight an entry it was not told"
                " about.\n"
                "       Rebuild that version with SPHINX_CCCL_VER set to the"
                " directory name,\n"
                f"       or remove it: git rm -r docs/{version}"
            )


def check_size(site_root):
    """Refuse to publish a site GitHub Pages would reject."""
    total = 0
    per_version = {}

    for component in COMPONENTS:
        component_root = (
            site_root / component["path"] if component["path"] else site_root
        )
        for version in discover_versions(component_root):
            size = sum(
                f.stat().st_size
                for f in (component_root / version).rglob("*")
                if f.is_file()
            )
            per_version[f"{component['id']}/{version}"] = size

    total = sum(f.stat().st_size for f in site_root.rglob("*") if f.is_file())

    mb = lambda n: f"{n / 1024 / 1024:.0f} MB"  # noqa: E731
    print(
        f"\nPublished size: {mb(total)} across {len(per_version)} version directories"
    )
    for name, size in sorted(per_version.items(), key=lambda kv: -kv[1]):
        print(f"  {name:24s} {mb(size):>9s}")

    if total > SIZE_BUDGET_BYTES:
        largest = (
            max(per_version.items(), key=lambda kv: kv[1]) if per_version else None
        )
        raise SystemExit(
            f"\nerror: the site would be {mb(total)}, over the {mb(SIZE_BUDGET_BYTES)}"
            " budget.\n"
            "       GitHub Pages refuses to publish a site larger than 1 GB, so this"
            " stops\n"
            "       here rather than letting the upload be rejected.\n"
            + (
                f"       Largest directory: {largest[0]} at {mb(largest[1])}."
                " Retire a version:\n"
                f"       git rm -r docs/<version> on gh-pages.\n"
                if largest
                else ""
            )
        )


# --------------------------------------------------------------------------
# Writing
# --------------------------------------------------------------------------


def write_manifests(component_root, component, versions, default_version, base_url):
    """Write the version switcher manifests for one component.

    ``version`` is the match key, compared against the stamp in the page.
    ``name`` is what the reader sees. Keeping them separate is what lets a
    directory named "3.4" display as "3.4.2".
    """
    entries = []
    for version in versions:
        entries.append(
            {
                "name": release_label(component_root / version),
                "version": version,
                "url": f"{base_url}{version}/",
                "latest": version == default_version,
                "preferred": version == default_version,
            }
        )

    (component_root / "nv-versions.json").write_text(
        json.dumps(entries, indent=2) + "\n", encoding="utf-8"
    )

    # Kept for anything still reading the older format.
    legacy = {entry["version"]: entry["name"] for entry in entries}
    (component_root / "versions.json").write_text(
        json.dumps(legacy, indent=2) + "\n", encoding="utf-8"
    )


def write_latest_alias(component_root, target):
    """Build ``latest/`` as redirect stubs pointing into the newest release.

    Stubs rather than a copy: duplicating a built C++ version costs 110-290 MB
    against a 1 GB budget, and a reader is better served landing on a pinned,
    version-scoped URL anyway.

    Rebuilt on *every* deploy, not only when the target is republished. Writing
    it only when the stable version is rebuilt means that promoting a new release
    leaves the alias pointing at the previous one, so ``/latest/`` silently
    serves the wrong version while the switcher claims otherwise.
    """
    alias = component_root / "latest"
    source = component_root / target

    if alias.exists():
        shutil.rmtree(alias)
    alias.mkdir(parents=True)

    stubs = 0
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(source)

        # The 404 helper resolves its own location to find its page list, so it
        # has to be a real copy; a stub would lose the query string carrying the
        # path the reader asked for. Its data files come with it.
        if relative.name in ("404_helper.html", "pagelist.txt", "objects.inv"):
            (alias / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, alias / relative)
            continue

        if path.suffix != ".html":
            continue

        destination = alias / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        up = "../" * len(relative.parts)
        href = f"{up}{target}/{relative.as_posix()}"
        destination.write_text(
            "<!DOCTYPE html>\n"
            '<html lang="en">\n'
            "<head>\n"
            '  <meta charset="utf-8">\n'
            f'  <meta http-equiv="refresh" content="0; url={href}">\n'
            f'  <link rel="canonical" href="{href}">\n'
            "</head>\n"
            f'<body><a href="{href}">Continue to the {target} documentation</a></body>\n'
            "</html>\n",
            encoding="utf-8",
        )
        stubs += 1

    print(f"  latest/ -> {target} ({stubs} redirect stubs)")


def write_component_index(component_root, default_version):
    """A nested component's entry point, redirecting to its default version.

    The component at the site root does not get one: that file is the landing
    page, which links straight to each component's current version instead.
    """
    (component_root / "index.html").write_text(
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        f'  <meta http-equiv="refresh" content="0; url={default_version}/">\n'
        f'  <link rel="canonical" href="{default_version}/">\n'
        "  <title>CUDA Core Compute Libraries</title>\n"
        "</head>\n"
        f'<body><a href="{default_version}/">Documentation</a></body>\n'
        "</html>\n",
        encoding="utf-8",
    )


def write_site_root(site_root, published, base_url, template_dir):
    """The landing page and the single 404 handler, shared by all components.

    With only one component published there is nothing to choose between, so the
    root stays a redirect into that component -- the behaviour readers have
    today. The chooser appears once a second component exists.
    """
    root_component = next((c for c in COMPONENTS if not c["path"]), None)

    if len(published) == 1 and root_component and root_component["id"] in published:
        default_version = published[root_component["id"]]["default"]
        (site_root / "index.html").write_text(
            "<!DOCTYPE html>\n"
            '<html lang="en">\n'
            "<head>\n"
            '  <meta charset="utf-8">\n'
            f'  <meta http-equiv="refresh" content="0; url={default_version}/">\n'
            f'  <link rel="canonical" href="{default_version}/">\n'
            "  <title>CUDA Core Compute Libraries</title>\n"
            "</head>\n"
            f'<body><a href="{default_version}/">'
            "CUDA Core Compute Libraries documentation</a></body>\n"
            "</html>\n",
            encoding="utf-8",
        )
        print("  site root: redirect (one component published)")
    else:
        cards = []
        for component in COMPONENTS:
            state = published.get(component["id"])
            if not state:
                continue  # nothing published for it yet; do not link into a 404
            href = (
                f"{component['path']}/{state['default']}/"
                if component["path"]
                else f"{state['default']}/"
            )
            cards.append(
                f'      <a class="card" href="{href}">\n'
                f"        <h2>{component['label']}</h2>\n"
                f"        <p>{component['description']}</p>\n"
                f'        <p class="version">{state["label"]}</p>\n'
                f"      </a>"
            )
        landing = (template_dir / "landing.html").read_text(encoding="utf-8")
        (site_root / "index.html").write_text(
            landing.replace("@CARDS@", "\n".join(cards)), encoding="utf-8"
        )
        print(f"  site root: landing page ({len(cards)} components)")

    # GitHub Pages allows exactly one 404 handler for the whole site, so it has
    # to be able to route a miss in any component to that component's own
    # per-version helper.
    site_path = urllib.parse.urlparse(base_url).path or "/"
    routing = {
        "sitePath": site_path,
        "components": [
            {
                "path": component["path"],
                "default": published[component["id"]]["default"],
                "versions": published[component["id"]]["versions"],
            }
            for component in COMPONENTS
            if component["id"] in published
        ],
        "pythonPath": next(
            (
                c["path"]
                for c in COMPONENTS
                if c["id"] == "python" and c["id"] in published
            ),
            None,
        ),
        "pythonDefault": published.get("python", {}).get("default"),
    }
    # The routing data lives in a JSON <script> block rather than a placeholder
    # so that the checked-in 404.html is a valid, working handler on its own --
    # local and PR-preview builds copy it straight through without publish_site.py
    # having run.
    template = (template_dir / "404.html").read_text(encoding="utf-8")
    rendered, substitutions = ROUTING_BLOCK.subn(
        lambda m: m.group(1) + "\n" + json.dumps(routing, indent=4) + "\n" + m.group(2),
        template,
        count=1,
    )
    if substitutions != 1:
        raise SystemExit(
            f"error: no site-routing block found in {template_dir / '404.html'};"
            " the 404 handler would not know how to route a miss"
        )
    (site_root / "404.html").write_text(rendered, encoding="utf-8")

    (site_root / ".nojekyll").touch()


# --------------------------------------------------------------------------


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "site_root", help="the directory that becomes the published site"
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("CCCL_DOCS_BASE_URL", DEFAULT_BASE_URL),
        help="public base URL of the whole site",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="re-check the written site and report what a reader would get",
    )
    args = parser.parse_args(argv)

    site_root = Path(args.site_root)
    if not site_root.is_dir():
        raise SystemExit(f"error: no such directory: {site_root}")

    base_url = args.base_url.rstrip("/") + "/"
    template_dir = Path(__file__).resolve().parent

    published = {}

    for component in COMPONENTS:
        component_root = (
            site_root / component["path"] if component["path"] else site_root
        )
        component_base = (
            f"{base_url}{component['path']}/" if component["path"] else base_url
        )

        versions = discover_versions(component_root)
        if not versions:
            print(f"{component['id']}: nothing published")
            continue

        print(f"\n{component['id']} in {component_root}")
        check_version_match(component_root, versions)
        versions = retire_old_releases(component_root, component["id"], versions)

        stable = latest_stable(component["id"], versions)
        default_version = stable or "unstable"
        if default_version not in versions:
            default_version = versions[0]

        print(f"  versions:        {', '.join(versions)}")
        print(f"  default:         {default_version}")
        print(f"  latest stable:   {stable or '<none published>'}")

        write_manifests(
            component_root, component, versions, default_version, component_base
        )

        if component["path"]:
            write_component_index(component_root, default_version)

        if stable:
            write_latest_alias(component_root, stable)
            # The root objects.inv is what intersphinx consumers resolve
            # against, so it tracks the stable docs rather than whichever
            # version happened to build last.
            source_inv = component_root / stable / "objects.inv"
            if source_inv.is_file():
                shutil.copy2(source_inv, component_root / "objects.inv")
        elif (component_root / "unstable" / "objects.inv").is_file():
            # Until a release exists, publish the tip's so the URL works at all.
            shutil.copy2(
                component_root / "unstable" / "objects.inv",
                component_root / "objects.inv",
            )

        published[component["id"]] = {
            "versions": versions,
            "default": default_version,
            "label": release_label(component_root / default_version),
        }

    if not published:
        raise SystemExit(
            "error: no published versions found anywhere under the site root"
        )

    print("\nsite root")
    write_site_root(site_root, published, base_url, template_dir)

    check_size(site_root)

    if args.verify:
        verify(site_root, published)

    return 0


def verify(site_root, published):
    """Re-read what was written and confirm a reader would get a coherent site."""
    print("\nVerifying")
    problems = []

    for component in COMPONENTS:
        state = published.get(component["id"])
        if not state:
            continue
        root = site_root / component["path"] if component["path"] else site_root

        manifest = json.loads((root / "nv-versions.json").read_text(encoding="utf-8"))
        listed = {entry["version"] for entry in manifest}
        if listed != set(state["versions"]):
            problems.append(
                f"{component['id']}: manifest lists {sorted(listed)}"
                f" but {sorted(state['versions'])} are published"
            )

        preferred = [e["version"] for e in manifest if e.get("preferred")]
        if preferred != [state["default"]]:
            problems.append(
                f"{component['id']}: manifest prefers {preferred},"
                f" expected [{state['default']!r}]"
            )

        for version in state["versions"]:
            if not (root / version / "pagelist.txt").is_file():
                problems.append(
                    f"{component['id']}/{version}: no pagelist.txt; 404 search will fail"
                )

        alias = root / "latest"
        if alias.is_dir() and not (alias / "index.html").is_file():
            problems.append(f"{component['id']}: latest/ exists but has no index.html")

        print(
            f"  {component['id']}: {len(state['versions'])} versions, default {state['default']}"
        )

    if problems:
        for problem in problems:
            print(f"  error: {problem}", file=sys.stderr)
        raise SystemExit(f"error: {len(problems)} problem(s) in the assembled site")

    print("  site is coherent")


if __name__ == "__main__":
    sys.exit(main())
