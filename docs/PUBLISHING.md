# Publishing CCCL documentation

CCCL publishes two independently released documentation products:

```
https://nvidia.github.io/cccl/                 chooser
https://nvidia.github.io/cccl/cpp/latest/      C++ development docs
https://nvidia.github.io/cccl/cpp/3.4.2/       a C++ release
https://nvidia.github.io/cccl/python/latest/   Python development docs
https://nvidia.github.io/cccl/python/1.1.1/    a Python release
```

`latest` means **built from `main`**, not "the newest release". This follows
[cuda-python](https://nvidia.github.io/cuda-python/), whose `latest` has the
same meaning. Releases live under their exact version and are reached through
the version switcher.

The two components version independently. A C++ release changes only C++ paths;
a Python release changes only Python paths. They need no matching numbers and no
matching dates.

---

## Everyday: merging to `main`

Nothing to do. A push to `main` builds both components and replaces both
`latest/` trees from that one commit. Releases are untouched.

---

## Publishing a release

### 1. Add the version to the component's manifest, before tagging

The switcher reads a checked-in manifest, so the release that introduces a
version must also introduce its entry. This is the same ownership model
cuda-python uses: the version list travels with the release.

For a C++ release, edit `docs/cpp_site/nv-versions.json`; for Python,
`docs/python_site/nv-versions.json`. Newest first, after `latest`:

```json
[
  { "version": "latest", "url": "https://nvidia.github.io/cccl/cpp/latest/" },
  { "version": "3.5.0",  "url": "https://nvidia.github.io/cccl/cpp/3.5.0/" },
  { "version": "3.4.2",  "url": "https://nvidia.github.io/cccl/cpp/3.4.2/" }
]
```

Forgetting this does not publish a broken site — the build stops and says so.
That guard exists because cuda-python's own site currently serves one component
manifest listing 7 versions beside another listing 19: each is whatever the
last build happened to copy, and nothing compares them to reality.

### 2. Run the documentation workflow with the tag

*Actions → Deploy CCCL Documentation → Run workflow*, and give it the exact
final tag:

```
v3.5.0           ->  /cccl/cpp/3.5.0/
python-1.2.0     ->  /cccl/python/1.2.0/
```

The tag alone decides the component and the directory. There is no destination
input, so a Python release cannot land in the C++ namespace, and no version can
be published under another version's name.

Pre-release tags such as `v3.5.0-rc0` are rejected rather than mapped onto the
release they precede.

### 3. Check the result

The affected URLs, plus one `_static` asset — without `.nojekyll`, Pages drops
underscore-prefixed directories and every page returns 200 with no styling.

---

## Rehearsing without touching production

The workflow takes a `docs-branch` input. Point it at a branch other than
`gh-pages` to publish a full artifact somewhere harmless.

---

## When a publication fails

Rerun the workflow. Deployment is additive — `clean: false` means an artifact
only adds or replaces the paths it contains — so a rerun cannot damage another
component or an earlier version. Re-running the same tag republishes that one
version directory.

If a release published wrong content, the repair is a corrective publication:
fix the source, tag a new patch, publish that. There is no rollback button,
deliberately; the deployment history on `gh-pages` is ordinary commits and a
maintainer can revert one if it comes to that.

---

## Things worth knowing

**Exact versions accumulate.** Nothing is retired automatically. A C++ release
is roughly 110 MB and GitHub Pages refuses a site over 1 GB, so with both
`latest` trees at ~190 MB the ceiling arrives at roughly eight releases of each
component. When it approaches, retiring old versions is a deliberate decision —
delete the directory and its manifest entry.

**The old URL scheme is gone.** `/cccl/unstable/...` and
`/cccl/unstable/python/...` are not preserved or redirected. Readers arrive
through the chooser or the component entry points.

**`latest` carries a banner** saying it is development documentation, so it
cannot be mistaken for a release.
