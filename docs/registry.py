#!/usr/bin/env python3
"""Read registry.yml, and answer the questions that depend on the product list.

Four things need to know which products exist, and before this they each knew
it separately: the landing index, every product's cross-reference mapping, the
tag grammar that routes a release, and the script that assembles the site. A
third product meant finding all four. Now they ask here.

This is the rapidsai/docs `_data/docs.yml` idea. The difference is that RAPIDS
renders a static index from its registry and composes the site from S3, while
every CCCL product is built by one workflow in one repository -- so the same
file can also drive the build, the routing and the cross-references.
"""

import os
import pathlib
import re

import yaml

HERE = pathlib.Path(__file__).resolve().parent
REGISTRY = HERE / "registry.yml"

# Where build_site.py assembles the tree it is about to publish. The conf.py
# files run in subprocesses of that script rather than importing it, so the
# directory arrives through the environment -- the same route the site URL
# already takes.
SITE = pathlib.Path(os.environ.get("CCCL_DOCS_SITE_DIR", HERE / "_site"))

# A published version is the development line or an exact release. No rolling
# MAJOR.MINOR directory, whose content would change under a reader's link, and
# no pre-release taking a released version's URL.
DEVELOPMENT = "unstable"
VERSION = re.compile(r"^(unstable|[0-9]+\.[0-9]+\.[0-9]+)\Z")


def load(path=REGISTRY):
    return yaml.safe_load(pathlib.Path(path).read_text(encoding="utf-8"))


def products(path=REGISTRY):
    """Every product, in the order the landing index should list them."""
    return load(path)["products"]


def product(key, path=REGISTRY):
    for entry in products(path):
        if entry["key"] == key:
            return entry
    raise SystemExit(
        f"error: no product {key!r} in registry.yml.\n"
        f"       It lists: {', '.join(p['key'] for p in products(path))}"
    )


def source_root(key, path=REGISTRY):
    """Absolute path to a product's Sphinx source root."""
    return (HERE / product(key, path)["source_root"]).resolve()


def resolve_tag(tag, path=REGISTRY):
    """``"v3.5.0"`` -> ``("cpp", "3.5.0")``.

    The prefix selects the product and the remainder is the version, so one tag
    carries both and nothing else supplies either. A prefix that matches no
    product, or a remainder that is not an exact release, stops the build rather
    than publishing under a name nobody chose.

    Longest prefix first, so a product whose prefix extends another's -- a
    hypothetical ``python-compute-`` beside ``python-`` -- cannot be shadowed by
    the shorter one.
    """
    text = (tag or "").strip()
    for entry in sorted(products(path), key=lambda p: -len(p["tag_prefix"])):
        prefix = entry["tag_prefix"]
        if text.startswith(prefix):
            version = text[len(prefix) :]
            if VERSION.match(version) and version != DEVELOPMENT:
                return entry["key"], version
            break

    expected = " or ".join(
        f"{p['tag_prefix']}MAJOR.MINOR.PATCH" for p in products(path)
    )
    raise SystemExit(
        f"error: {text!r} is not a release tag for any product.\n"
        f"       Expected {expected}.\n"
        "       Pre-release tags are not published to the stable switcher."
    )


def intersphinx_mapping(key, base_url, target=DEVELOPMENT, path=REGISTRY, site=None):
    """Where this product resolves cross-references to its siblings.

    Sphinx resolves a cross-reference inside one project. Two projects means a
    page in one cannot reach a page in the other by name -- unless it is handed
    the other's inventory, which is what intersphinx does: the other project
    publishes ``objects.inv``, this one reads it, and a reference resolves by
    symbol rather than by a URL somebody typed. A symbol that moves fails the
    build; a URL that moves fails silently, for a reader, later.

    ``key`` is the calling product, which is excluded -- a project resolves its
    own names locally, and handing it its own inventory makes every local
    reference ambiguous. The root project passes ``None``: it is not a product,
    so it excludes nothing and maps them all.

    RAPIDS points each project at the *matching* version of its siblings,
    because every RAPIDS project ships 26.08 together. CCCL's products release
    independently, so there is no matching version to point at: C++ 3.5.0 has no
    corresponding Python release. Siblings are therefore targeted at the
    development line, which always exists. Changing that policy is this one
    argument.

    The URL is where the link *points*. The second element of the tuple is where
    the inventory is *read from*, and those are deliberately different: the link
    must be the published address a reader will follow, but the lookup should use
    the tree this run is about to publish, which ``build_site.py`` assembles in
    ``_site/``. Seeding fills that directory from the published branch, and each
    product's build replaces its own subtree, so one path is always the freshest
    inventory that exists -- this run's build if the sibling built, the published
    one otherwise.

    Reading the live site instead, which is what ``None`` falls back to, means
    resolving against the *previous* publish. That is one publish behind by
    construction, and it is why adding a page and referencing it in the same
    commit used to fail: the inventory being consulted predated the build sitting
    beside it on the same runner.
    """
    base = base_url.rstrip("/")
    root = pathlib.Path(SITE if site is None else site)
    mapping = {}
    for entry in products(path):
        sibling = entry["key"]
        if sibling == key:
            continue
        inventory = root / sibling / target / "objects.inv"
        on_disk = inventory.is_file()
        mapping[sibling] = (
            f"{base}/{sibling}/{target}/",
            str(inventory) if on_disk else None,
        )
        # Whether the check ran against fresh data is not otherwise answerable
        # from a build log.
        print(
            f"  intersphinx {sibling}: "
            f"{'assembled site' if on_disk else 'published site over HTTP'}"
        )
    return mapping


def exclude_patterns(key, path=REGISTRY):
    """Source roots this product's build must not sweep in.

    Only matters for a product whose source root contains another's. The C++
    sources sit at docs/, so docs/python/ and docs/site/ are inside its tree,
    and Sphinx would otherwise publish both under a C++ version they never
    shipped under. Derived from the registry so a third product is excluded by
    being added rather than by being remembered.
    """
    registry = load(path)
    mine = (HERE / product(key, path)["source_root"]).resolve()

    roots = [entry["source_root"] for entry in registry["products"]]
    roots.append(registry["root"]["source_root"])

    patterns = []
    for root in roots:
        other = (HERE / root).resolve()
        if other == mine:
            continue
        try:
            patterns.append(str(other.relative_to(mine)))
        except ValueError:
            continue  # not inside this source root; nothing to exclude
    return sorted(patterns)
