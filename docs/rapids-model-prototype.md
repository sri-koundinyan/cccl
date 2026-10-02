# A RAPIDS-shaped prototype for the CCCL documentation

*What was built, why it is shaped this way, and what it proves.*

**Status: live.** Publishing <https://sri-koundinyan.github.io/cccl/> from `main` on the fork as of 2 October 2026.

This describes a prototype on the branch `rapids-model`. It is a second, parallel
implementation of versioned documentation for CCCL, built from the structure
RAPIDS uses, so that the two approaches can be compared rather than argued about.
Nothing here is wired into what currently publishes the site.

It exists because of three things that came out of the review call: Jake's point
that collapsing the published branch to one commit was deliberate and that losing
it costs clone size; Georgii's and Jake's shared preference for a real landing
project rather than a hand-written chooser page; and the knowledge that
`cuda.compute` and `cuda.coop` will soon version separately, so a design that
handles exactly two products has a deadline on it.

---

## 1. A short glossary, because the rest depends on it

**Sphinx** is the tool that turns documentation sources into a website. A
**Sphinx project** is one run of it: one set of sources, one configuration, one
output directory.

A project's **source root** is the directory Sphinx reads from. Everything below
it is a candidate page. This matters more than it sounds: if one project's source
root contains another project's sources, the outer one will sweep the inner one's
pages into its own output unless told not to.

**`conf.py`** is a project's configuration — an ordinary Python file that Sphinx
executes at the start of a build. Because it is executed rather than parsed, it
can compute its settings instead of hard-coding them, which is the hinge the
whole prototype turns on.

A **cross-reference** is a link written by name rather than by URL — "link to the
page about CUDASTF", not "link to `https://…/cudax/stf.html`". Sphinx resolves
those names within one project.

**`objects.inv`**, the **inventory**, is a small compressed index every Sphinx
project publishes alongside its HTML. It maps every name the project documents to
the page that documents it. It exists so that *other* projects can resolve
cross-references into this one.

**intersphinx** is the Sphinx extension that reads another project's inventory and
makes its names referenceable. It is the mechanism by which two separate projects
can link to each other by name.

The **published branch** is `gh-pages` — an ordinary git branch whose contents
GitHub Pages serves as a website. Publishing documentation means committing HTML
to that branch.

An **orphan commit** is a commit with no parent. Recreating a branch as a single
orphan commit discards its history, which is why a branch published that way stays
small no matter how many times you publish.

---

## 2. The shape, in one picture

RAPIDS splits documentation into a root that *indexes* and products that are
*indexed*:

```
docs.rapids.ai/              a Sphinx project: landing index, install, maintainer docs
  cudf/25.08/                built in the cudf repository, composed in at publish time
  cuml/25.08/                built in the cuml repository
  …27 products
```

The root never builds the products. It knows they exist and where they go; each
product is built elsewhere and composed into the published site.

The prototype is the same shape, with one difference that falls out of CCCL
having one repository instead of twenty-seven:

```
/cccl/                       a Sphinx project: landing index, and anything unversioned
  cpp/unstable/              built by ./gen_docs.bash
  cpp/3.4.2/
  python/unstable/           built by ./gen_python_docs.bash
  python/1.1.1/
```

RAPIDS composes from S3 because its products live in separate repositories. We
compose from build scripts because ours live here. The separation — *root
indexes, products are built independently, something assembles* — is identical,
and it is the part that makes the model hold at three products or ten.

---

## 3. The registry: going from two products to N

**The problem.** The current implementation knows there are exactly two products,
and it knows it in four separate places: the tag grammar that routes a release,
the list of directories the C++ build must exclude, the cross-product links, and
the workflow's deploy steps. Adding `cuda.coop` means finding all four. Missing
one is a silent failure, because three of the four fail by producing a site that
builds and deploys and is merely wrong.

**What RAPIDS does.** One file, `_data/docs.yml`, names all 27 projects. Every
part of their site that needs the list reads it from there.

**What the prototype does.** `docs/registry.yml`:

```yaml
products:
  - key: cpp
    name: C++
    source_root: .
    tag_prefix: v
    build: ./gen_docs.bash --label {label}
    summary: >-
      Thrust, CUB, libcu++ and CUDA Experimental …

  - key: python
    name: Python
    source_root: python
    tag_prefix: python-
    build: ./gen_python_docs.bash --label {label}
    summary: >-
      cuda.compute and cuda.cccl …
```

Five facts per product: where it lives in the URL, what it is called, where its
sources are, what tag prefix selects it, and how to build it.

`docs/registry.py` reads that file and answers the questions that used to be
answered by hard-coded lists:

| Question | Who used to answer it | Now |
| --- | --- | --- |
| Which product does tag `v3.5.0` belong to? | a regex pair in `release_label.py` | `resolve_tag()` |
| Which directories must the C++ build ignore? | a literal list in `conf.py` | `exclude_patterns()` |
| Where does a Python page resolve a C++ name? | four URLs typed into prose | `intersphinx_mapping()` |
| Which products does the landing page list? | hand-written HTML | the index generator |

**The demonstration.** Adding a hypothetical third product — seven lines in
`registry.yml`, no code changed anywhere — produces:

```
products now:          ['cpp', 'python', 'coop']
coop-1.0.0 routes to:  ('coop', '1.0.0')
cpp now excludes:      ['coop', 'python', 'site']
cpp links to:          ['coop', 'python']
coop links to:         ['cpp', 'python']
landing index cards:   3 products
```

Every one of those four previously-separate facts updated from one edit.

**A detail worth noticing.** `exclude_patterns()` computes which source roots sit
*inside* which. The C++ sources are at `docs/`, so `docs/python/` and `docs/site/`
are within its tree and must be excluded, or Sphinx publishes Python pages under a
C++ version they never shipped under. The Python sources are at `docs/python/`,
which contains nothing else, so its exclusion list is empty — correctly, and
without anyone deciding that. A third product is excluded by being added.

---

## 4. The root project: somewhere for unversioned content

**The problem.** The site root is currently a hand-written HTML file with two
links. Georgii's objection in the call was that you land on it and have no idea
where you are — it falls outside the documentation's own styling and offers
nowhere to put anything. Jake's was structural: it precludes language-agnostic
content, and CCCL already has some. Contributor guides, infrastructure
documentation, installation instructions.

**Why those pages have nowhere to go today.** Every current page belongs to a
product, and every product's pages are stamped with that product's version. A
contributor guide has no version. It isn't 3.5.0 and it isn't 1.2.0; it describes
the repository as it is now. Putting it in the C++ project means claiming it is
part of the C++ release, and duplicating it into both means two copies that drift.

**What the prototype does.** `docs/site/` is a Sphinx project like any other,
except that it has no version:

```python
version = release = ""

html_theme_options = {
    "switcher": None,                      # no version dropdown
    "show_version_warning_banner": False,
}
```

It is built once, published at the site root, and carries the same NVIDIA theme
as everything else, so a reader does not fall out of the documentation on arrival.

Its index page is **generated from the registry** rather than written by hand, via
a `config-inited` hook — Sphinx's event for "configuration has been read, no
sources have been looked at yet". So the landing page and the product list cannot
disagree, and a new product appears on the landing page because it was added to
the registry.

```
generated index.md from registry.yml: 2 products
```

**One thing that needed solving.** Links from this page point at `cpp/` and
`python/`, which do not exist within this project — they appear only once the site
is assembled. MyST, the Markdown parser, tried to resolve them as pages in this
project, failed, and warned; and these builds treat warnings as errors. The fix is
one setting, `myst_all_links_external = True`, which is simply true of this page:
every link on it points out.

---

## 5. Intersphinx: links that break loudly

**The problem Georgii raised.** Splitting into two Sphinx projects meant a Python
page could no longer cross-reference a C++ page, because Sphinx resolves names
within one project. The workaround was to write the full URL by hand. Georgii's
objection: a URL cannot be checked. When the target moves — and the docs are being
actively moved right now — nothing fails. The link simply stops working, and you
find out when a reader does.

**What RAPIDS does.** Every project consumes its siblings' inventories:

```python
intersphinx_mapping = {
    "cudf": (f"https://docs.nvidia.com/cudf/{intersphinx_version}/", None),
    "rmm":  (f"https://docs.nvidia.com/rmm/{intersphinx_version}/",  None),
}
```

`None` means "fetch `objects.inv` from that URL at build time". `intersphinx_version`
is `latest` on a development build and the project's own version on a release — so
a release of cuml links to the matching release of cudf.

**What the prototype does.** The same, built from the registry so each product maps
onto its siblings automatically. The four hand-written URLs became references:

```rst
before   `C++ CUDASTF documentation <https://…/cccl/cpp/unstable/cudax/stf.html>`_
after    :doc:`C++ CUDASTF documentation <cpp:cudax/stf>`
```

`cpp:` names the inventory to look in; `cudax/stf` is the page's name within it.
At build time Sphinx fetches the C++ inventory, finds that name, and writes the
URL into the HTML.

**The proof.** Building Python against the live C++ inventory resolves all four:

```
index.html     -> https://…/cccl/cpp/unstable/index.html
stf.html       -> https://…/cccl/cpp/unstable/cudax/stf.html
stf_api.html   -> https://…/cccl/cpp/unstable/cudax/stf.html
```

And simulating the C++ page being renamed:

```
stf.rst:441: WARNING: unknown document: 'cpp:cudax/stf_RENAMED' [ref.doc]
exit=1
```

The build fails, naming the file and the line. That is the entire point: the
failure moved from a reader's click to a developer's build.

**One constraint that does not transfer, and matters.** RAPIDS can point a release
at the *matching* release of its siblings because all RAPIDS projects ship 26.08
together. CCCL's products version independently — that independence is the whole
reason for splitting them — so when C++ 3.5.0 wants to link to Python
documentation, there is no matching Python version to link to. The prototype
therefore targets the development line, which always exists. That is a policy
choice expressed as a single argument in `intersphinx_mapping()`, and it is the
one place where RAPIDS's answer cannot simply be copied.

---

## 6. The single-commit branch: versions and clone size, at the same time

**The problem Jake raised.** `force_orphan: true` in the old setup was not an
accident. It recreates the published branch as one commit each time, which is why
a clone of CCCL stayed small. He had traced clone-size complaints to that branch's
history and fixed them this way.

Removing it — which the current implementation does, in order to keep more than
one version — gives the history back. Measured on the fork:

```
one snapshot of the site        10.1 MB
after 56 incremental deploys    89.8 MB
history alone                   79.7 MB        ~1.4 MB per deploy
```

At CCCL's merge rate that is multiple gigabytes a year, against a branch that was
previously a constant size forever.

**The observation the prototype is built on.** `force_orphan` was never the
problem. A *partial artifact* was.

Recreating a branch from an artifact only loses things if the artifact is missing
them. The old artifact contained one build, so recreating the branch from it
destroyed every other version — which is exactly why versioning was impossible.
But if the artifact is the **complete site**, recreating the branch from it loses
nothing at all.

**What the prototype does.** The assembly starts by seeding itself from what is
already published:

```
seeded from gh-pages: cpp, python
placed python/ -- unstable: 14 pages
assembled: root project + 1 product at unstable
```

It reads the current published tree off the branch, overlays the product it just
built, and hands the deploy a complete site. The published branch becomes a
function of *(what was published, what was just built)* — which is also why no
part of this has to reason about replacing one directory while preserving another.
It rebuilds the lot.

At that point `force_orphan: true` is correct again, and both properties hold
together:

```
one orphan publish of the complete site    14.5 MB    and constant
56 incremental deploys (current main)      89.8 MB    and growing
```

**A side effect worth noting.** This also removes the failure mode we spent
yesterday guarding against. There is no scoped deletion, no page-count floor
protecting against a near-empty build wiping a directory, and no interpolated
label that could aim a deletion at the wrong place — because nothing deletes
anything. The site is rebuilt and republished whole.

---

## 7. What is proven, and how

**This is live.** It publishes <https://sri-koundinyan.github.io/cccl/> from
`main` on the fork, after two CI rehearsals against a scratch branch.

| Claim | Evidence |
| --- | --- |
| A third product is a registry edit | added one; routing, exclusions, links and the index all updated, no code changed |
| The root project builds clean | `sphinx-build -W` exits 0; index generated from the registry |
| Cross-references resolve | Python built against the live C++ inventory; all four links correct |
| A moved page fails the build | renamed the target; build exits 1 naming file and line |
| The assembly produces a complete site | published site carries `cpp/3.4.2` and `python/1.1.1` byte-identical to the pre-publish backup, alongside 1,694 freshly built C++ pages |
| One commit is enough | a real clone of the published branch: **15.3 MiB, one commit**, against 89.8 MiB for 56 incremental deploys |
| The switcher offers every version | `['unstable', '3.4.2']` and `['unstable', '1.1.1']` as served |
| The site works | 11 of 11 routes 200; `smoke_site.py` passes, including the switcher-agreement and `_static` checks |
| Nothing regressed | the existing 64-test suite still passes; `ruff` clean |

---

## 7a. What the rehearsals caught

Three defects surfaced in CI that local testing could not have found. They are
worth recording, because each was invisible to a passing local build.

**`docs/site/` was not excluded from the C++ source root.** The root project sits
inside the C++ sources, so the C++ build would have swept the landing index into
its own output and published it as a C++ page. Caught by the existing test suite
once the file existed — and the fix is the registry-derived exclusion list, which
means the next product excludes itself.

**Sphinx was missing on a clean runner.** The root project is built *before* any
product, and the product scripts are what create `docs/env`. Locally that
environment already existed and was active, so the root build always found
Sphinx. On a fresh runner there was nothing, and the first rehearsal failed in
ninety seconds. `build_site.py` now creates that environment itself.

**The published site and its switcher disagreed.** The most instructive one. The
first rehearsal published a structurally perfect site — one commit, all four
versions, releases byte-identical — with manifests naming a single version each:

```
cpp:    ['unstable']        should have been ['unstable', '3.4.2']
python: ['unstable']        should have been ['unstable', '1.1.1']
```

Two things read the published branch: the assembly, which seeds from it, and each
product's manifest generator. Both were handed `FETCH_HEAD`. But the generator
*fetches* the name it is given before reading it, so its own fetch overwrote the
ref in between. Seeding ran first and worked; the manifests ran after and found
an empty tree.

Every page returned 200. Every page rendered. The dropdown simply did not offer
versions whose pages were sitting right there. Nothing short of comparing the
published directories against the manifest would have found it — so that
comparison is now a check the assembly runs, and it fails the build.

---

## 8. What this prototype deliberately does not do

It is an MVP, and these are knowingly absent:

**The C++ sources have not moved.** They remain at `docs/`, so the C++ source root
contains the other projects and needs them excluded. A fully RAPIDS-faithful
layout would move them to `docs/cpp/` and leave `docs/` holding only the root
project. That is a large mechanical change and it would have buried everything
else in this diff.

**No unversioned content has been written yet.** `docs/site/` holds the generated
index and nothing else. Moving the contributor and infrastructure documentation
into it is the obvious next step and is the thing Jake and Georgii actually asked
for.

**The previous model is parked, not deleted.** `docs-deploy.yml` lost its push
trigger — both workflows publish to the same branch, and leaving both armed would
race them on every merge. It keeps its dispatch, so the old model stays runnable
against a scratch branch for comparison.

**The previous published branch is backed up** at `gh-pages-before-rapids`
(`946b18506a`). This is the first `force_orphan` publish against the real branch;
`git push --force fork gh-pages-before-rapids:gh-pages` restores it.

**Cross-product links target the development line**, for the reason in §5. If
version-tracking links are wanted, that needs a policy decision about what a C++
release should point at, since there is no matching Python version.
