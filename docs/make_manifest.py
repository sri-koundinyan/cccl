#!/usr/bin/env python3
"""Generate a component's version manifest from what is actually published.

    nv-versions.json   the version list the theme fetches to draw the switcher

The manifest answers one question: which versions of this component exist, and
where does each one live. That is a fact about the published site, so it is read
from the published site rather than maintained by hand.

The source is the documentation branch itself. Not the served URL, which goes
through a CDN and can lag a deploy by minutes; and not ``main``, which records
what someone intended to publish rather than what is published. On the branch,
every subdirectory of ``docs/<component>/`` is a version and every file beside
them is site plumbing, so a directory listing is the version list.

Deriving rather than editing removes both failure modes a checked-in list has.
A version cannot be forgotten, because the one being published is added here.
And a version cannot be silently dropped, because nothing is carried forward
from the previous manifest -- the file is rewritten from the listing every time,
so the only way to remove an entry is to remove the directory it names.

With no branch to read -- a local build, or the first deploy to a branch that
does not exist yet -- the manifest lists only the version being built, which is
the correct answer for a site with one version on it. A branch that was named
but could not be read is an error rather than an empty list: publishing a
one-entry manifest over a populated site would empty the switcher.
"""

import argparse
import json
import pathlib
import re
import subprocess
import sys

# The same grammar the build scripts validate against. Applied to the listing
# as well, so a stray directory on the branch cannot reach the switcher.
VERSION = re.compile(r"^(unstable|[0-9]+\.[0-9]+\.[0-9]+)\Z")

PRODUCTION = "https://nvidia.github.io/cccl"

DEVELOPMENT = "unstable"


def _git(args, repo):
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=False
    )


def _resolve(branch, repo):
    """A readable ref for ``branch``, or ``None``.

    A fresh fetch is preferred, and is what keeps the listing current: it runs
    at the end of the build, a minute or two before the deploy, rather than
    reusing whatever the checkout happened to bring down at the start. The
    fallbacks cover an offline build and a branch named by a local ref, which
    is how a rehearsal or a test names one that was never pushed.
    """
    if _git(["fetch", "--quiet", "--depth=1", "origin", branch], repo).returncode == 0:
        return "FETCH_HEAD"
    for candidate in (branch, f"origin/{branch}"):
        probe = ["rev-parse", "--verify", "--quiet", f"{candidate}^{{commit}}"]
        if _git(probe, repo).returncode == 0:
            return candidate
    return None


def published_versions(component, branch, repo="."):
    """Version directories under ``docs/<component>/`` on ``branch``.

    Returns ``[]`` when nothing is published there yet -- either the branch does
    not exist, which is a first deploy, or it exists without this component's
    directory. Raises when the branch could not be read but may well have
    content, because publishing a one-entry manifest over a populated site would
    empty the switcher, and doing that quietly is the failure this replaces.
    """
    ref = _resolve(branch, repo)

    if ref is None:
        # Nothing readable. Only the remote can say whether that is because the
        # branch does not exist yet or because we could not reach it.
        probe = _git(["ls-remote", "--exit-code", "--heads", "origin", branch], repo)
        if probe.returncode == 2:
            return []
        raise SystemExit(
            f"error: cannot read branch {branch!r}.\n"
            "       The manifest lists the versions published there, so carrying on\n"
            "       would publish a manifest naming only the version being built\n"
            "       and drop every other version out of the switcher."
        )

    listed = _git(["ls-tree", "-d", "--name-only", f"{ref}:docs/{component}/"], repo)
    if listed.returncode != 0:
        return []
    return [name for name in listed.stdout.split() if VERSION.match(name)]


def order(versions):
    """``unstable`` first, then semantic versions newest first."""
    releases = sorted(
        (v for v in versions if v != DEVELOPMENT),
        key=lambda v: tuple(int(part) for part in v.split(".")),
        reverse=True,
    )
    return ([DEVELOPMENT] if DEVELOPMENT in versions else []) + releases


def manifest(component, versions, site_url):
    """The switcher's entries: what to match on, and where to navigate."""
    base = f"{site_url.rstrip('/')}/{component}"
    return [{"version": v, "url": f"{base}/{v}/"} for v in versions]


def retarget_landing(component_root, component, site_url):
    """Point the landing redirect's canonical at the host serving this build.

    Inert markup, but a lone production URL inside a rehearsal artifact is
    exactly the confusion a rehearsal exists to avoid.
    """
    landing = pathlib.Path(component_root) / "index.html"
    if not landing.exists():
        return False
    base = f"{site_url.rstrip('/')}/{component}"
    landing.write_text(
        re.sub(
            r'(<link rel="canonical" href=")[^"]*(">)',
            rf"\g<1>{base}/{DEVELOPMENT}/\g<2>",
            landing.read_text(encoding="utf-8"),
        ),
        encoding="utf-8",
    )
    return True


def write(component_root, component, version, site_url, branch=None, repo="."):
    """Generate and write the manifest. Returns the versions it lists."""
    if not VERSION.match(version):
        raise SystemExit(
            f"error: {version!r} is not a publishable version.\n"
            "       Expected 'unstable' or an exact MAJOR.MINOR.PATCH release."
        )

    existing = published_versions(component, branch, repo) if branch else []
    versions = order(set(existing) | {version})

    path = pathlib.Path(component_root) / "nv-versions.json"
    path.write_text(
        json.dumps(manifest(component, versions, site_url), indent=2) + "\n",
        encoding="utf-8",
    )
    return versions


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--component", required=True, choices=("cpp", "python"))
    parser.add_argument("--version", required=True, help="the version being published")
    parser.add_argument(
        "--out", required=True, help="the component root in the artifact"
    )
    parser.add_argument(
        "--site-url", default=PRODUCTION, help="site root these URLs name"
    )
    parser.add_argument(
        "--from-branch", default="", help="branch to read published versions from"
    )
    parser.add_argument("--repo", default=".", help="repository to read the branch in")
    args = parser.parse_args(argv)

    branch = args.from_branch or None
    versions = write(
        args.out, args.component, args.version, args.site_url, branch, args.repo
    )

    source = f"derived from {branch}" if branch else "no branch read; single version"
    print(f"  nv-versions.json ({source}): {', '.join(versions)}")
    if retarget_landing(args.out, args.component, args.site_url):
        print(
            f"  landing canonical -> {args.site_url.rstrip('/')}/{args.component}/{DEVELOPMENT}/"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
