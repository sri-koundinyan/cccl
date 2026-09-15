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

### 1. Add the version to the component's manifests, before tagging

The switcher reads a checked-in manifest, so the release that introduces a
version must also introduce its entry. This is the same ownership model
cuda-python uses: the version list travels with the release.

Each component has **two** manifest files, and both need the new version. For
a C++ release edit `docs/cpp_site/`; for Python, `docs/python_site/`.

`nv-versions.json` is the one the theme reads. Newest first, after `latest`:

```json
[
  { "version": "latest", "url": "https://nvidia.github.io/cccl/cpp/latest/" },
  { "version": "3.5.0",  "url": "https://nvidia.github.io/cccl/cpp/3.5.0/" },
  { "version": "3.4.2",  "url": "https://nvidia.github.io/cccl/cpp/3.4.2/" }
]
```

`versions.json` is the cuda-python-style compatibility file. Same versions:

```json
{
    "latest" : "latest",
    "3.5.0"  : "3.5.0",
    "3.4.2"  : "3.4.2"
}
```

Forgetting either does not publish a broken site — the build stops and says so.
That guard exists because nothing reads `versions.json` today, so a
disagreement between the two is invisible until something does. cuda-python
shows exactly that: its `cuda_core` ships a `versions.json` stopping at `0.3.2`
next to an `nv-versions.json` reaching `1.2.0`, because each file is whatever
the last build happened to copy.

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

Look at the affected URLs. For a rehearsal, or if anything looks off, run the
full check:

```bash
python3 docs/smoke_site.py
```

It checks every route, that each page's version stamp is one its switcher
manifest actually lists, and that `_static` loads. That last one matters
because without `.nojekyll` GitHub Pages drops underscore-prefixed directories:
every page still returns 200, with no styling and no version switcher.

---

## Rehearsing without touching production

The workflow takes a `docs-branch` input. Point it at a branch other than
`gh-pages` to publish a full artifact somewhere harmless.

**A fork needs nothing extra.** The build derives its own site URL from the
repository: Pages serves `https://<owner>.github.io/<repo>` with the owner
lowercased, which for `NVIDIA/cccl` is the production URL and for a fork is the
fork's. One rule, no flag to remember.

This matters because the version switcher is fetched by the reader's browser at
the URL the page names. Pages built for production name production, so a fork
build that did not do this would look completely correct and have an empty
version dropdown — the browser fetching a manifest from a host that does not
serve this layout.

Set `site-url` explicitly only for a **custom domain**, which cannot be derived
from the repository name:

```
site-url:  https://docs.example.com/cccl
```

`docs/smoke_site.py` follows the URL each page declares, rather than assuming
it, so it catches this class of failure rather than passing through it.

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

**Exact versions accumulate.** Nothing is retired automatically, and GitHub
Pages refuses a site over 1 GB. Measured at launch:

| | size |
|---|---|
| `cpp/latest` | 180 MB |
| `cpp/3.4.2` | 118 MB |
| `python/latest` | 8 MB |
| `python/1.1.1` | 8 MB |
| **total** | **314 MB**, leaving 710 MB |

C++ is what consumes the budget: about 118 MB per release against 8 MB for
Python. That headroom is roughly **six more C++ releases**. Python is not a
practical constraint at this ratio.

When the ceiling approaches, retiring old versions is a deliberate decision —
delete the directory and its manifest entry from both manifest files. Because
deployment is additive, deleting a hosted directory is a manual operation on
the Pages branch, not something a build can do.

**The old URL scheme is gone.** `/cccl/unstable/...` and
`/cccl/unstable/python/...` are not preserved or redirected. Readers arrive
through the chooser or the component entry points.

**`latest` carries a banner** saying it is development documentation, so it
cannot be mistaken for a release.
