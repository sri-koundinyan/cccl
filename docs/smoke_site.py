#!/usr/bin/env python3
"""Check a published CCCL documentation site over HTTP.

    python3 docs/smoke_site.py
    python3 docs/smoke_site.py --base-url https://sri-koundinyan.github.io/cccl

Run this after the launch conversion and after a release rehearsal. Routine
releases do not need it; workflow success plus a look at the affected pages is
enough. There is no full-site verifier, deliberately.

Every check here covers a failure that is invisible from the build logs,
because the build succeeded and the deployment succeeded:

*   A route 404s because a version directory did not survive deployment.
*   A page is stamped with a label its switcher manifest does not list, so the
    version picker renders perfectly and never highlights the current page.
*   `_static` is missing. GitHub Pages runs Jekyll unless `.nojekyll` is
    present, and Jekyll drops underscore-prefixed directories. Every page still
    returns 200 -- with no stylesheet and no working version switcher. This is
    the reason to check an asset rather than just the HTML routes.
"""

import argparse
import json
import re
import sys
import urllib.error
import urllib.request

DEFAULT_BASE = "https://nvidia.github.io/cccl"

# (component, the one release the component shipped at launch)
COMPONENTS = [("cpp", "3.4.2"), ("python", "1.1.1")]

TIMEOUT = 30


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "cccl-docs-smoke"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.status, response.read()


class Report:
    def __init__(self):
        self.failures = []

    def check(self, label, ok, detail=""):
        print(f"  [{'ok  ' if ok else 'FAIL'}] {label}" + (f"  {detail}" if detail and not ok else ""))
        if not ok:
            self.failures.append(f"{label}: {detail}" if detail else label)
        return ok

    def route(self, url):
        try:
            status, body = fetch(url)
        except urllib.error.HTTPError as exc:
            self.check(url, False, f"HTTP {exc.code}")
            return None
        except OSError as exc:
            self.check(url, False, str(exc))
            return None
        self.check(url, status == 200 and bool(body), f"HTTP {status}")
        return body


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base-url", default=DEFAULT_BASE,
                        help=f"site root, without a trailing slash (default: {DEFAULT_BASE})")
    args = parser.parse_args(argv)
    base = args.base_url.rstrip("/")
    report = Report()

    print(f"checking {base}\n")

    print("routes")
    report.route(f"{base}/")
    for component, version in COMPONENTS:
        for path in ("", "latest/", f"{version}/", "nv-versions.json", "versions.json"):
            report.route(f"{base}/{component}/{path}")

    print("\nswitcher agrees with the page it is on")
    for component, version in COMPONENTS:
        manifest = report.route(f"{base}/{component}/nv-versions.json")
        if manifest is None:
            continue
        try:
            listed = [entry["version"] for entry in json.loads(manifest)]
        except (ValueError, KeyError, TypeError) as exc:
            report.check(f"/{component}/nv-versions.json parses", False, str(exc))
            continue
        report.check(f"/{component}/ manifest lists latest and {version}",
                     set(listed) >= {"latest", version}, f"lists {listed}")

        for label in ("latest", version):
            body = report.route(f"{base}/{component}/{label}/")
            if body is None:
                continue
            text = body.decode("utf-8", "replace")
            found = re.search(r"theme_switcher_version_match = '([^']*)'", text)
            stamp = found.group(1) if found else None
            report.check(f"/{component}/{label}/ is stamped '{label}'",
                         stamp == label, f"stamped {stamp!r}")

            # Follow the URL the page itself declares, not the one we expect.
            # The switcher is client-side: the browser fetches whatever this
            # says. A page served from one host while pointing at another --
            # a fork, a rename, a stale CCCL_DOCS_BASE_URL -- renders perfectly
            # with an empty dropdown, and checking our own manifest instead
            # would not notice.
            declared = re.search(r"theme_switcher_json_url = '([^']*)'", text) \
                or re.search(r"json_url = '([^']*)'", text)
            url = declared.group(1) if declared else None
            if not report.check(f"/{component}/{label}/ declares a switcher URL", bool(url)):
                continue
            if not url.startswith("http"):
                url = f"{base}/{component}/{label}/".rstrip("/") + "/" + url.lstrip("/")
            served = report.route(url)
            if served is None:
                report.check(f"  ^ the switcher on /{component}/{label}/ will be empty",
                             False, f"page points at {url}")
                continue
            try:
                reachable = [entry["version"] for entry in json.loads(served)]
            except (ValueError, KeyError, TypeError) as exc:
                report.check(f"{url} parses", False, str(exc))
                continue
            report.check(f"/{component}/{label}/ stamp is in the manifest it fetches",
                         stamp in reachable, f"{stamp!r} not in {reachable}")

    print("\nstatic assets (what .nojekyll protects)")
    for component, version in COMPONENTS:
        for label in ("latest", version):
            page = f"{base}/{component}/{label}/"
            body = report.route(page)
            if body is None:
                continue
            assets = re.findall(r'(?:href|src)="([^"]*_static/[^"]+)"',
                                body.decode("utf-8", "replace"))
            if not report.check(f"{page} references _static", bool(assets)):
                continue
            asset = assets[0].split("?")[0]
            report.route(asset if asset.startswith("http") else page + asset.lstrip("/"))

    print()
    if report.failures:
        print(f"{len(report.failures)} failed:")
        for failure in report.failures:
            print(f"  - {failure}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
