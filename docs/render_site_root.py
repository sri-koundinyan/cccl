#!/usr/bin/env python3
"""Render the two files shared by the whole documentation site.

``index.html``
    The landing page. The C++ and Python libraries version independently, so
    neither can own the site root; a reader picks one here.

``404.html``
    GitHub Pages allows a single 404 handler per site, so this one has to route
    misses for every component. It works out which component and version a
    reader was aiming for and hands off to that version's own helper, which
    fuzzy-matches against its page list.

Both are rendered from ``published_versions.json`` on every deploy, so a deploy
of any component produces the same correct files and one component's deploy
cannot leave the site root describing a stale layout.
"""

import argparse
import json
import sys
from pathlib import Path

from render_versions import default_version, discover_versions, resolve_latest_stable


def component_roots(extra_roots, path):
    """The same component's directory inside any additional site roots."""
    return [str(Path(r) / path) if path else str(r) for r in extra_roots]


def component_view(manifest, site_base, site_root, manifest_path, extra_roots=()):
    """The components, in the shape the templates and the 404 router need.

    Each carries the version a legacy unversioned URL beneath it should fall
    back to. That is discovered rather than assumed: hardcoding "latest" would
    send readers to an alias that does not exist for a component with no stable
    release yet.
    """
    view = []
    for component in manifest["components"]:
        path = component.get("path", "").strip("/")
        root = Path(site_root) / path if path else Path(site_root)

        published = discover_versions([str(root), *component_roots(extra_roots, path)])
        if published:
            latest_stable = resolve_latest_stable(component, published, manifest_path)
            fallback = default_version(sorted(published), latest_stable)
        else:
            # Nothing published for this component yet; the 404 handler can only
            # send readers to its index, which redirects onwards.
            fallback = None

        view.append(
            {
                "id": component["id"],
                "label": component.get("label", component["id"]),
                "description": component.get("description", ""),
                "path": path,
                "default": fallback,
                # Straight to the version. The component at the site root has no
                # redirect of its own -- this landing page occupies that file --
                # so linking to the component root would link here.
                "url": (
                    f"{site_base}/{path}/{fallback}/"
                    if path
                    else f"{site_base}/{fallback}/"
                )
                if fallback
                else (f"{site_base}/{path}/" if path else f"{site_base}/"),
            }
        )
    return view


def render_landing(components, template):
    """Fill in the landing page's list of components."""
    items = []
    for component in components:
        # Inside the anchor, so the whole card is one target rather than just
        # the label.
        description = (
            f'\n        <span class="description">{component["description"]}</span>'
            if component["description"]
            else ""
        )
        items.append(
            f"    <li>\n"
            f'      <a href="{component["url"]}">{component["label"]}{description}\n'
            f"      </a>\n"
            f"    </li>"
        )
    return template.replace("@COMPONENTS@", "\n".join(items))


def render_404(components, site_base, template):
    """Fill in the routing table the 404 handler needs.

    Longest path first, so that a nested component is matched before the one
    living at the site root, which would otherwise swallow everything.
    """
    routes = sorted(components, key=lambda c: len(c["path"]), reverse=True)
    table = [
        {"path": c["path"], "label": c["label"], "default": c["default"]}
        for c in routes
    ]
    return template.replace("@SITE_BASE@", site_base).replace(
        "@COMPONENT_ROUTES@", json.dumps(table)
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--site-root", required=True)
    parser.add_argument(
        "--site-base", required=True, help="site path, e.g. /cccl (may be empty)"
    )
    parser.add_argument(
        "--template-dir", required=True, help="where the html templates live"
    )
    parser.add_argument(
        "--discover-from",
        action="append",
        default=[],
        metavar="DIR",
        help="additional site root to discover versions in; repeatable",
    )
    args = parser.parse_args(argv)

    with open(args.manifest, encoding="utf-8") as f:
        manifest = json.load(f)

    site_base = args.site_base.rstrip("/")
    components = component_view(
        manifest, site_base, args.site_root, args.manifest, args.discover_from
    )
    if not components:
        raise SystemExit(f"{args.manifest}: no components to render a landing page for")

    template_dir = Path(args.template_dir)
    site_root = Path(args.site_root)
    site_root.mkdir(parents=True, exist_ok=True)

    landing = render_landing(
        components, (template_dir / "landing.html").read_text(encoding="utf-8")
    )
    (site_root / "index.html").write_text(landing, encoding="utf-8")

    handler = render_404(
        components, site_base, (template_dir / "404.html").read_text(encoding="utf-8")
    )
    (site_root / "404.html").write_text(handler, encoding="utf-8")

    print(f"  site root: landing page for {', '.join(c['label'] for c in components)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
