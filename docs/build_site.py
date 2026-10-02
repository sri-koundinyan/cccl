#!/usr/bin/env python3
"""Build the root project, build each product, and assemble the site.

    python3 docs/build_site.py                      everything, into docs/_site/
    python3 docs/build_site.py --product python     one product, plus the root
    python3 docs/build_site.py --label 3.5.0 --product cpp      a release

This is rapidsai/docs' two-step shape. There, ``make html`` builds a root Sphinx
project that indexes the products, and ``make assemble`` composes the published
site by pulling each product's documentation from S3. The products are built
elsewhere, in their own repositories, and the root never builds them.

CCCL's products live in this repository, so "elsewhere" is a build script rather
than a bucket -- but the separation is the same, and it is what makes the model
hold at three products or ten. The root knows that products exist and where they
go. It does not know how any of them is built, which is just as well: one needs
Doxygen and a C++ toolchain, another imports a Python package.

The assembled tree is what the deploy publishes:

    _site/
      index.html             the root project: the landing index
      _static/               its theme assets
      cpp/
        index.html           redirect to this product's current version
        nv-versions.json     the versions the switcher offers
        unstable/            one version directory per published version
      python/
        ...
"""

import argparse
import pathlib
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import registry

DEFAULT_SITE = HERE / "_site"
# Where the per-product build scripts leave their output.
ARTIFACTS = HERE / "_build" / "artifacts" / "docs"
# The virtual environment the product build scripts create and share.
VENV = HERE / "env"


def run(command, cwd=HERE):
    print(f"  $ {command}")
    result = subprocess.run(command, shell=True, cwd=cwd, check=False)
    if result.returncode != 0:
        raise SystemExit(f"error: command failed: {command}")


def python_bin():
    """The interpreter that has Sphinx, which is the one in docs/env."""
    candidate = VENV / "bin" / "python"
    return str(candidate) if candidate.exists() else sys.executable


def ensure_dependencies():
    """Create the shared virtual environment if nothing has yet.

    The product build scripts do this themselves, but the root project is built
    before any of them, and on a fresh runner there is no Sphinx anywhere. This
    is the same environment those scripts use, so it is created once here or
    once there, whichever runs first.
    """
    if (VENV / "bin" / "python").exists():
        return
    print("creating the documentation virtual environment")
    run(f"{sys.executable} -m venv {VENV}")
    run(
        f"{VENV / 'bin' / 'python'} -m pip install --quiet -r {HERE / 'requirements.txt'}"
    )


def seed_from_branch(branch, site_dir, published_prefix="docs"):
    """Start the assembly from what is already published.

    This is the step that makes the published branch a single commit again.

    The old setup deployed with ``force_orphan``, which recreates the branch
    from the artifact: one commit, a small clone -- and no earlier version,
    because the artifact only ever held the build that had just run. Dropping
    ``force_orphan`` kept the versions and let the branch grow instead; measured
    on this fork, 56 deploys took it from 10 MB to 90 MB.

    Neither is necessary. ``force_orphan`` was never the problem; a *partial*
    artifact was. Seed the assembly with every version already published, overlay
    the one just built, and the artifact is the whole site -- at which point
    recreating the branch from it loses nothing, and the branch stays at one
    commit however many times it is published.

    So the published site becomes a function of (what was published, what was
    just built), which is also why nothing here needs to reason about replacing
    one directory and preserving another. It rebuilds the lot.
    """
    # From the repository root, not from docs/: in `git archive <rev>:<path>`
    # the path is resolved against the current directory's prefix, so the same
    # command run from docs/ would look for docs/docs and silently find nothing.
    repo = HERE.parent

    probe = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{branch}^{{commit}}"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        print(f"  {branch} does not exist yet -- first publication, nothing to seed")
        return 0

    listing = subprocess.run(
        ["git", "archive", f"{branch}:{published_prefix}"],
        cwd=repo,
        capture_output=True,
        check=False,
    )
    if listing.returncode != 0:
        raise SystemExit(
            f"error: cannot read {published_prefix}/ on {branch}.\n"
            "       Carrying on would publish a site missing every version\n"
            "       already on it, and the deploy recreates the branch."
        )

    tar = pathlib.Path(site_dir) / ".seed.tar"
    tar.write_bytes(listing.stdout)
    shutil.unpack_archive(str(tar), str(site_dir), format="tar")
    tar.unlink()

    seeded = sorted(
        p.name
        for p in pathlib.Path(site_dir).iterdir()
        if p.is_dir() and not p.name.startswith((".", "_"))
    )
    print(f"  seeded from {branch}: {', '.join(seeded) or '(nothing)'}")
    return len(seeded)


def build_root(site_dir):
    """The unversioned project at the site root.

    Built with sphinx-build like any other project; it just has no version, so
    nothing stamps it and no switcher is drawn on it.
    """
    root_source = HERE / registry.load()["root"]["source_root"]
    print(f"building the root project from {root_source.relative_to(HERE)}/")
    # -d keeps Sphinx's doctree cache out of the output. Without it the cache
    # lands in the published tree and gets deployed with the site.
    run(
        f"{python_bin()} -m sphinx.cmd.build -b html -q -W --keep-going "
        f"-d {HERE / '_build' / 'root-doctrees'} "
        f"{root_source} {site_dir}"
    )


def build_product(entry, label):
    """One product, via the build command the registry names for it."""
    print(f"building {entry['key']} at {label}")
    run(entry["build"].format(label=label))


def place_product(entry, label, site_dir):
    """Copy a product's build output into the assembled site.

    Everything the product produced moves as it is -- the version directory, the
    manifest the switcher reads, the landing redirect. The assembly does not
    rewrite any of it; it decides where it goes.
    """
    source = ARTIFACTS / entry["key"]
    if not source.is_dir():
        raise SystemExit(
            f"error: {entry['key']} built nothing at {source}.\n"
            f"       Expected the build command to leave output there."
        )

    target = pathlib.Path(site_dir) / entry["key"]
    target.mkdir(parents=True, exist_ok=True)
    for item in sorted(source.iterdir()):
        destination = target / item.name
        if destination.exists():
            shutil.rmtree(destination) if destination.is_dir() else destination.unlink()
        if item.is_dir():
            shutil.copytree(item, destination, symlinks=True)
        else:
            shutil.copy2(item, destination)

    pages = (
        len(list((target / label).rglob("*.html"))) if (target / label).is_dir() else 0
    )
    print(f"  placed {entry['key']}/ -- {label}: {pages} pages")
    return pages


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--label", default=registry.DEVELOPMENT, help="version to build the products at"
    )
    parser.add_argument(
        "--product",
        action="append",
        dest="products",
        help="build only this product (repeatable)",
    )
    parser.add_argument(
        "--site", default=str(DEFAULT_SITE), help="directory to assemble into"
    )
    parser.add_argument(
        "--skip-build", action="store_true", help="assemble from existing build output"
    )
    parser.add_argument(
        "--seed-from", default="", help="branch whose published site to start from"
    )
    args = parser.parse_args(argv)

    if not registry.VERSION.match(args.label):
        raise SystemExit(
            f"error: {args.label!r} is not a publishable version.\n"
            "       Expected 'unstable' or an exact MAJOR.MINOR.PATCH release."
        )

    wanted = args.products or [p["key"] for p in registry.products()]
    entries = [registry.product(key) for key in wanted]

    site_dir = pathlib.Path(args.site)
    site_dir.mkdir(parents=True, exist_ok=True)

    ensure_dependencies()

    if args.seed_from:
        seed_from_branch(args.seed_from, site_dir)

    build_root(site_dir)

    total = 0
    for entry in entries:
        if not args.skip_build:
            build_product(entry, args.label)
        total += place_product(entry, args.label, site_dir)

    # GitHub Pages runs Jekyll unless this exists, and Jekyll drops directories
    # beginning with an underscore -- which is every Sphinx asset directory.
    (site_dir / ".nojekyll").touch()

    print()
    print(f"assembled {site_dir}")
    print(f"  root project + {len(entries)} product(s) at {args.label}, {total} pages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
