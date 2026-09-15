# CCCL documentation versioning

CCCL's C++ and Python libraries release on their own schedules, but their
documentation was published as one combined tree with no release versions at
all. Now each is its own versioned site.

**Before**

```
/cccl/unstable/                 everything, built from main
/cccl/unstable/python/          Python docs nested inside the C++ tree
```

**Now**

```
/cccl/                          a chooser: C++ or Python
/cccl/cpp/latest/               C++, built from main
/cccl/cpp/3.4.2/                C++ release 3.4.2
/cccl/python/latest/            Python, built from main
/cccl/python/1.1.1/             Python release 1.1.1
```

Readers pick a version from a dropdown in the page header.

**Every patch release gets its own directory**, named for the full version
(e.g. `3.4.3`, `3.5.0`, `1.1.2`, `1.2.0`).

---

## `latest` updates automatically

**Merging to `main` republishes both `latest/` trees.** Both products are
rebuilt from that one commit, so their development docs never describe
different commits. Released versions are not touched.

---

## Publishing a tagged release

**1. Before tagging, add the version to that product's two manifest files.**

For C++ that is `docs/cpp_site/nv-versions.json` and
`docs/cpp_site/versions.json`; for Python, the same two under
`docs/python_site/`. This belongs in the release-preparation commit, reviewed
like any other change.

**2. Tag the release**, e.g. `v3.5.0` or `python-1.2.0`.

**3. Run the workflow.** *Actions → Deploy CCCL Documentation → Run workflow*,
and give it the exact tag.

The tag alone decides everything: which product, and which directory. If you
skip step 1, the build **stops and tells you**. It does not publish
documentation that nothing links to.

---

## Things to keep in mind

**`latest` means "built from `main`". It is not the newest release.** It
documents code that is not in any release yet, and it changes every time `main`
changes.

**Publishing never deletes.** A deployment copies in the files it carries and
touches nothing else. It is a copy, not a sync, so it never compares and never
removes. That is what lets a Python release leave every C++ path alone, and lets
old versions accumulate safely.

The flip side: **a page dropped from a build is not dropped from the site.**
Rename `foo.html` to `foo2.html` and both stay live. Nothing links to
`foo.html` any more, because the sidebars, the search index and `objects.inv`
were all rebuilt without it, but the URL still works and still serves the old
content.

This only happens where a deployment writes into a directory that already has
files (in practice, the two `latest/` trees). People usually pin to and cite
specific releases, and those do not accumulate stale content.

**Versions accumulate forever.** Nothing retires automatically. A C++ release is
about 118 MB and GitHub Pages refuses a site over 1 GB. The site is at 314 MB
today, so there is room for roughly six more C++ releases. Python is tiny by
comparison (~8 MB) and is not a practical constraint.

**The two existing releases cannot be rebuilt by the workflow.** A release build
runs the build scripts found in the tag's own source, and `v3.4.2` and
`python-1.1.1` predate this system. `python-1.1.1` has no Python docs build at
all. Both `3.4.2` and `1.1.1` were published once, from one-off compatibility
branches. Any release tagged from now on re-publishes normally.

---

## If something goes wrong

**Re-run the workflow.** Deployment is additive, so a re-run cannot damage
another product or an earlier version.

**If a release published wrong content**, the fix is a corrective release: fix
the source, tag a new patch, publish that. There is no rollback button, but the
`gh-pages` history is ordinary commits, so a maintainer can revert one if it
comes to that.

**To check a published site**, run:

```bash
python3 docs/smoke_site.py
```

It checks every route, that each page's version stamp matches the dropdown it
actually fetches, and that stylesheets load.

---

## Where this came from

The model is lifted from [cuda-python](https://github.com/NVIDIA/cuda-python),
which solves the same problem: several independently released components in one
repository. CCCL follows its architecture: the same reusable workflow shape and
the same deploy action at the same pinned commit (with a small number of
differences).
