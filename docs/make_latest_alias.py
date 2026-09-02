#!/usr/bin/env python3
"""Build the /latest/ alias as redirect stubs rather than a copy.

A full copy of the stable documentation is the obvious way to provide a
"latest" URL, but it is also the most expensive thing on the site: a CCCL
version is roughly 150 MB, and GitHub Pages refuses to publish a site larger
than 1 GB. Duplicating the stable build spends a sixth of that budget on
content that already exists one directory over.

Instead, mirror the stable version's page tree with small HTML redirects. The
result is a few hundred kilobytes, readers still get a stable URL they can
bookmark, and following one lands them on a pinned, version-scoped address
rather than on a page whose meaning changes at the next release.

A few files are copied rather than redirected, because redirecting them would
break the thing that uses them:

``404_helper.html`` and ``pagelist.txt``
    The site's 404 handler fetches these from within whichever version subtree
    the reader was in. A redirect would drop the query string that carries the
    path being searched for.

``objects.inv``
    Intersphinx consumers fetch it directly and do not follow HTML redirects.
"""

import argparse
import posixpath
import shutil
import sys
from pathlib import Path

# Served from the alias directly instead of redirecting.
COPY_VERBATIM = ("404_helper.html", "pagelist.txt", "objects.inv")

STUB = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta http-equiv="refresh" content="0; url={target}">
  <link rel="canonical" href="{target}">
  <title>Redirecting to the latest documentation</title>
</head>
<body>
  <a href="{target}">Continue to the latest documentation</a>
</body>
</html>
"""


def build_alias(site_root, version, alias="latest", source_root=None):
    """Create ``<site_root>/<alias>`` mirroring ``<source_root>/<version>``.

    ``source_root`` defaults to ``site_root``, which is the case when the stable
    version is the one being deployed. It is given separately when regenerating
    the alias during a deploy of some *other* version: the pages to mirror then
    live in a checkout of the already-published site rather than in this build.
    The stubs are relative, so they resolve correctly either way.
    """
    site_root = Path(site_root)
    source = Path(source_root if source_root is not None else site_root) / version
    target = site_root / alias

    if not source.is_dir():
        raise SystemExit(f"error: no build to alias at {source}")

    if target.exists():
        shutil.rmtree(target)

    stubs = 0
    copied = 0

    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)

        if path.name in COPY_VERBATIM:
            shutil.copy2(path, destination)
            copied += 1
        elif path.suffix == ".html":
            # Relative so the alias works on forks and local servers alike.
            href = posixpath.relpath(
                posixpath.join(version, relative.as_posix()),
                start=posixpath.join(alias, relative.parent.as_posix()),
            )
            destination.write_text(STUB.format(target=href), encoding="utf-8")
            stubs += 1

    if not stubs:
        raise SystemExit(f"error: {source} contained no HTML pages to alias")

    return stubs, copied


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-root", required=True, help="the published site root")
    parser.add_argument("--version", required=True, help="version directory to alias")
    parser.add_argument("--alias", default="latest", help="alias directory name")
    parser.add_argument(
        "--source-root",
        help="where to read the aliased version's pages from (default: --site-root)",
    )
    args = parser.parse_args(argv)

    stubs, copied = build_alias(
        args.site_root, args.version, args.alias, args.source_root
    )
    print(
        f"  {args.alias}/: {stubs} redirect(s) to {args.version}/, "
        f"{copied} file(s) copied verbatim"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
