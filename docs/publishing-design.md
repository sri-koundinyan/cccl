# Publishing CCCL's Documentation

*How the documentation site is built, versioned, and published — and why it is
built that way.*

This document explains the system in full, including the reasoning behind each
decision. Two shorter documents cover narrower needs:

- **New to this change?** [publishing-overview.md](publishing-overview.md) — what
  changed, what happens automatically, and what to keep in mind.
- **Cutting a release?** [PUBLISHING.md](PUBLISHING.md) — the procedure.

---

## Contents

1. [The problem](#1-the-problem)
2. [A tour of the machinery](#2-a-tour-of-the-machinery)
3. [What a reader sees](#3-what-a-reader-sees)
4. [How a publication happens](#4-how-a-publication-happens)
5. [The two manifests](#5-the-two-manifests)
6. [The three URLs that must agree](#6-the-three-urls-that-must-agree)
7. [Failures that look like success](#7-failures-that-look-like-success)
8. [Where this departs from cuda-python](#8-where-this-departs-from-cuda-python)
9. [Operating it](#9-operating-it)
10. [What this deliberately is not](#10-what-this-deliberately-is-not)
11. [Appendix: the file map](#11-appendix-the-file-map)

---

## 1. The problem

CCCL ships **two products that release on their own schedules**:

- the **C++ libraries** — Thrust, CUB, libcu++, cudax — released as `v3.4.2`;
- the **Python packages** — `cuda.compute`, `cuda.coop` — released as
  `python-1.1.1`.

They live in one repository but they are not versioned together. C++ 3.4.2 and
Python 1.1.1 have no particular relationship; neither number predicts the other.

The old site did not reflect this. It published a single combined tree:

```
/cccl/unstable/                 ← everything, from the development branch
/cccl/unstable/python/          ← Python docs nested inside the C++ tree
```

Two things are wrong here, in increasing order of seriousness.

**Nesting Python inside C++ makes the Python docs a subdirectory of a C++
artifact.** Publishing C++ documentation therefore republishes the Python
documentation, whether or not Python changed.

**There were no release versions at all.** A reader on CCCL 3.4.2 had nowhere to
go for documentation matching the version they had installed. The site described
the development branch and nothing else.

The goal is a site where each product has its own namespace, its own version
history, and its own publication events that leave the other product alone.

Rather than invent a scheme, CCCL adopts the one **cuda-python** already uses for
exactly this situation — several independently released components in one
repository. The reference implementation reviewed for this design is
[`db53e1438e`](https://github.com/NVIDIA/cuda-python/tree/db53e1438e86289bc83a8814597c12e51b45c352).
Section 8 records every place CCCL departs from it, and why.

### The whole system on one page

Everything that follows is detail on this picture. It is worth a minute now, so
the details have somewhere to attach.

```
   SOURCE                    BUILD                      PUBLISHED SITE
   ──────                    ─────                      ──────────────

   push to main   ─────►  build both  ──────────►  cpp/unstable/      replaced
                          products                 python/unstable/   replaced
                                                   everything else  untouched

   tag v3.5.0     ─────►  build C++   ──────────►  cpp/3.5.0/       added
   (dispatched              only                   python/**        untouched
    by hand)                                       cpp/unstable/      untouched
                                                   cpp/3.4.2/       untouched
```

Three ideas carry the whole design, and each maps to one column:

1. **Two products, two namespaces.** `/cccl/cpp/` and `/cccl/python/` are
   siblings. Nothing is nested inside anything else.
2. **A build emits only what it owns.** A C++ release artifact physically
   contains no Python files, so it cannot disturb them.
3. **Deployment adds and replaces; it never deletes.** Whatever an artifact
   does not mention survives.

Put together: *independent versioning falls out of what each artifact contains,
rather than from a system that decides what may overwrite what.* There is no
publisher, no lock, no plan. That is the point.

---

## 2. A tour of the machinery

Terms you will meet throughout. Skip ahead if they are familiar; each is also
re-explained at the point it matters.

**GitHub Pages** is GitHub's static web host. It is configured to serve a
particular *branch* and *directory* of the repository. For CCCL that is the
branch `gh-pages`, directory `docs/`. So the file at `gh-pages:docs/cpp/unstable/index.html`
is served at `https://nvidia.github.io/cccl/cpp/unstable/`.

Note the consequence: **`gh-pages` is not source code.** It is a branch whose
contents *are* the website. Publishing means committing files to it.

**Sphinx** is the documentation generator. It reads `.rst` and `.md` sources
plus a configuration file (`conf.py`) and emits a directory of HTML.

**Doxygen** extracts documentation comments from C++ headers into XML.
**Breathe** is the bridge that lets Sphinx render that XML. This is why the C++
build is slow and the Python build is fast: the C++ build compiles Doxygen from
source, runs it across every header, and generates over a thousand API pages.

**Jekyll** is a blog engine GitHub Pages runs over your files by default. It has
one behaviour that matters here: **it deletes directories whose names begin with
an underscore.** Sphinx puts every stylesheet and script in `_static/`. So a
Jekyll-processed Sphinx site serves every page successfully, with no styling and
no working version menu.

**`.nojekyll`** is an empty file that switches Jekyll off. Section 7 returns to
why its absence is such a nasty failure.

**The version switcher** is the version dropdown in the page header, provided by
the NVIDIA Sphinx theme. It is **not** generated at build time. Each page
carries only a *URL*; the reader's browser fetches that URL at page load and
builds the menu from what comes back. The file it fetches is
`nv-versions.json`, called the **manifest**.

**`objects.inv`** is a Sphinx **inventory**: a compressed index of every
documented symbol and the page it lives on. Its purpose is **intersphinx**, the
mechanism by which one Sphinx project links into another's API by symbol name
rather than by hand-written URL.

**The canonical URL** is a `<link rel="canonical">` tag naming the preferred
address of a page. When the same content exists at several URLs — as it does
when you publish many versions — it tells search engines which one to index.

**A reusable workflow** is a GitHub Actions workflow that other workflows call,
like a function. **`workflow_dispatch`** means a workflow can be started by hand
from the Actions tab, optionally with inputs.

**A note on vocabulary.** This document says **product** for "the C++ libraries"
or "the Python packages", because that is what they are to a reader. The code
and the workflow inputs call the same thing a **component** — `component: cpp`,
`components=python` — following cuda-python, where the word arrived from its
`cuda-core` and `cuda-bindings` packages. They mean the same thing.

---

## 3. What a reader sees

The public contract. Everything in later sections exists to produce and preserve
this.

```
https://nvidia.github.io/cccl/                  the chooser
                              cpp/              → redirects to cpp/unstable/
                              cpp/unstable/       C++, built from main
                              cpp/3.4.2/        C++ release 3.4.2
                              python/           → redirects to python/unstable/
                              python/unstable/    Python, built from main
                              python/1.1.1/     Python release 1.1.1
```

**The root is a chooser, not a redirect.** It presents two links and picks
neither. C++ and Python are peers, and the site should not assume which one a
visitor wants.

### `unstable` means "built from `main`"

This is the single most important definition in the document, because the word
naturally reads the other way.

> **`unstable` is the development branch, not the newest release.**

The name is kept from the old site deliberately: it is the one piece of
vocabulary readers already know, and it says plainly that this is not a release.
It moves every time `main` moves. It is *ahead* of every released version, and it
documents code that is not in any release.

This is cuda-python's meaning of the word, and
[its own `unstable`](https://nvidia.github.io/cuda-python/latest/) behaves the same
way. To reduce the chance of a reader misreading it, every page under `unstable/`
carries a banner saying it documents the development branch.

A reader who wants "the docs for the version I installed" wants `cpp/3.4.2/`,
and reaches it through the version dropdown.

### Release directories are exact and permanent

Each release gets a directory named for its **full** version:

```
tag v3.4.2         →  /cccl/cpp/3.4.2/
tag python-1.1.1   →  /cccl/python/1.1.1/
```

There is deliberately **no `3.4/` directory** meaning "the newest 3.4.x". A
rolling directory is a URL whose content changes underneath the reader, which
makes it useless for citing and confusing to land on from a search result.

Publishing 3.4.3 creates `/cccl/cpp/3.4.3/` and changes nothing else. 3.4.2
stays exactly as it was published.

### The two products never touch each other

The C++ dropdown lists only C++ versions; the Python dropdown lists only Python
versions. A C++ release modifies only paths under `/cccl/cpp/`. A Python release
modifies only paths under `/cccl/python/`. Neither touches the chooser.

### The old URLs are gone

`/cccl/unstable/...` and `/cccl/unstable/python/...` return 404. They are not
redirected. Preserving them would mean maintaining a routing layer forever for
URLs whose replacements are not one-to-one — the old tree had no release
versions at all, so much of it has no successor to redirect *to*.

---

## 4. How a publication happens

### Two paths, one implementation

There are exactly two ways documentation is published, and they share a single
reusable workflow so they cannot drift apart:

| | trigger | builds | publishes to |
|---|---|---|---|
| **Development** | push to `main` | both products | `cpp/unstable/`, `python/unstable/` |
| **Release** | manual dispatch with a tag | the tagged product only | that product's exact version |

Development publication is automatic — merge to `main` and the site updates.
Release publication is deliberately manual: you dispatch it with a tag.

### The build produces an artifact shaped like the site

Each build writes a directory whose layout *is* the site layout:

```
docs/_build/artifacts/docs/
├── index.html            ← the chooser        ┐
├── .nojekyll                                  │ only the combined build
├── cpp/                                       │ emits these
│   ├── index.html        ← redirect to unstable/
│   ├── unstable/           ← the documentation
│   ├── nv-versions.json  ← the manifest
│   ├── versions.json
│   └── objects.inv
└── python/               ← same shape
```

A release build emits **only its own product's subtree** — no chooser, no
`.nojekyll`, no other product. This is not enforced by a rule applied afterwards;
it falls out of each build script writing only under `artifacts/docs/cpp/` or
`artifacts/docs/python/`.

### Deployment is additive

The artifact is copied onto `gh-pages` under `docs/` by
[`JamesIves/github-pages-deploy-action`](https://github.com/JamesIves/github-pages-deploy-action),
pinned to a full commit SHA, with one setting that carries the whole design:

```yaml
clean: false
```

**`clean: false` means "add and replace the paths I brought; delete nothing
else."** Everything the artifact does not mention survives untouched.

This one line is what makes independent versioning work without a publishing
system to arbitrate it:

- a Python release carries only `python/1.2.0/` and the Python manifests, so
  every C++ path and every earlier Python version is *physically not mentioned*
  and therefore cannot be disturbed;
- a development build carries both `unstable/` trees, so releases are untouched;
- exact versions accumulate because nothing ever removes them.

The corollary is worth stating plainly, because it is the cost of the model:
**a file that disappears from a build does not disappear from the site.** If a
page is renamed, the old page stays served until someone deletes it by hand.
Deliberate cleanup is a manual operation on the `gh-pages` branch.

### The tag is the only thing that chooses a destination

For a release, the workflow takes a tag and nothing else. A small script,
[`release_label.py`](release_label.py), maps it:

```
v3.4.2        →  component "cpp",     version "3.4.2"
python-1.1.1  →  component "python",  version "1.1.1"
```

There is no "publish to" input. That absence is the safety property: a Python
release **cannot** be routed into the C++ namespace, and no version can be
published under another version's name, because no human types a destination.

Anything that is not an exact final release is rejected rather than
approximated:

```
v3.5.0-rc0     rejected — a pre-release must not occupy the release's URL
v3.4           rejected — no rolling MAJOR.MINOR directory exists
3.4.2          rejected — which product?
```

### Worked example: a pull request merges

Someone fixes a docstring in `cub/` and merges to `main`.

1. The push triggers **Deploy CCCL Documentation**.
2. The workflow resolves the label: this is not a release, so it is `unstable`,
   for `component: all`.
3. It resolves the site URL from the repository: `https://nvidia.github.io/cccl`.
4. `gen_all_docs.bash` builds **both** products from that one commit — C++ into
   `artifacts/docs/cpp/unstable/`, Python into `artifacts/docs/python/unstable/` —
   then adds the chooser and `.nojekyll`.
5. Checks run: does each product's `index.html` and `objects.inv` exist, do the
   manifests parse and agree, does the C++ tree wrongly contain a `python/`
   subtree, does the full artifact carry `.nojekyll`.
6. The artifact is copied onto `gh-pages:docs/` with `clean: false`.

**Result:** both `unstable/` trees are replaced. `cpp/3.4.2/` and `python/1.1.1/`
are not in the artifact, so they are not touched. The Python docs were rebuilt
even though only C++ changed — both `unstable` trees always come from the same
commit, which is what keeps them consistent with each other.

### Worked example: releasing C++ 3.5.0

1. **Before tagging**, a pull request adds `3.5.0` to
   `docs/cpp_site/nv-versions.json` *and* `docs/cpp_site/versions.json`. This is
   ordinary reviewable source, in the release-preparation commit.
2. The tag `v3.5.0` is created.
3. A maintainer dispatches the workflow with `git-tag: v3.5.0`.
4. `release_label.py` maps the tag to `("cpp", "3.5.0")`. **Nothing else is
   consulted** — no destination input exists.
5. The workflow checks out **the tag**, and runs `gen_docs.bash --label 3.5.0`.
   Only the C++ build step runs; the Python step's condition is false.
6. The build refuses to finish unless the pages it produced are stamped `3.5.0`
   *and* `3.5.0` appears in the manifest it is shipping. (Step 1 is what
   satisfies the second condition. Skip it and the release stops here rather
   than publishing something unreachable.)
7. The artifact — containing only `cpp/3.5.0/` and the two C++ manifests — is
   deployed with `clean: false`.

**Result:** `/cccl/cpp/3.5.0/` appears. `cpp/3.4.2/` is untouched. `cpp/unstable/`
is untouched. Every path under `python/` is untouched. The chooser is untouched,
because a release artifact does not contain one.

The only file the release *modifies* rather than adds is the pair of C++
manifests — which is exactly the change that makes the new version appear in the
dropdown.

### Only tags newer than this change can be rebuilt

A release build checks out **the tag's own source**, and runs the build scripts
found there. So the release path works only for tags cut *after* this system
landed. The two launch tags cannot be rebuilt by it:

- `python-1.1.1` contains no `gen_python_docs.bash` and no `python_conf/` at
  all — the Python build did not exist as a separate thing yet;
- `v3.4.2` has a `gen_docs.bash`, but one that does not understand `--label`.

This is not a defect; it is what "the documentation build travels with the
source" means. It is also why the initial site could not simply be produced by
running the workflow twice.

### The one-time conversion

The permanent workflow assumes the two product namespaces already exist, and
`clean: false` means it can only add and replace — never remove. So the move
from the old combined layout to this one could not be performed by it.

That conversion was a separate, deliberately disposable operation: build the
four initial trees, assemble them, replace `gh-pages:docs/` wholesale, and
delete the machinery afterwards. The two historical releases were built from
small **compatibility overlay** branches — one per tag, each a recorded commit
on top of the tag that adapts only its documentation configuration to the new
layout. An overlay changes where the documentation is served and what it claims
as canonical; it does not change which release source the documentation
describes.

Those overlays and the assembly scripts are not part of the ongoing system, and
were not kept in the repository.

---

## 5. The two manifests

Each product directory carries **its own** pair of files listing **only its own**
versions. There are four manifests on the site and no site-root manifest —
`/cccl/nv-versions.json` is deliberately a 404, because the root is a chooser
and belongs to neither product.

**`nv-versions.json`** is the real one — the file the theme fetches to build the
dropdown. The C++ copy, at `/cccl/cpp/nv-versions.json`:

```json
[
  { "version": "unstable", "url": "https://nvidia.github.io/cccl/cpp/unstable/" },
  { "version": "3.4.2",  "url": "https://nvidia.github.io/cccl/cpp/3.4.2/" }
]
```

and the Python copy, at `/cccl/python/nv-versions.json`, listing entirely
different versions:

```json
[
  { "version": "unstable", "url": "https://nvidia.github.io/cccl/python/unstable/" },
  { "version": "1.1.1",  "url": "https://nvidia.github.io/cccl/python/1.1.1/" }
]
```

**`versions.json`** is a simpler compatibility file that cuda-python also ships.
Again one per product — C++ on the left, Python on the right:

```json
{ "unstable": "unstable", "3.4.2": "3.4.2" }      { "unstable": "unstable", "1.1.1": "1.1.1" }
```

Nothing reads `versions.json` today. It is carried to stay aligned with the
reference implementation, and because something may read it later.

This separation is what makes the two dropdowns independent. The C++ switcher
cannot offer `1.1.1` because the file it fetches has never heard of it.

### The manifests are checked in, not discovered

They live in the repository at `docs/cpp_site/` and `docs/python_site/`, and the
build copies them into the artifact. They are **release data**: the release that
introduces a version also introduces its manifest entry, in the same commit,
before the tag.

The alternative — generating the list by inspecting what is currently on
`gh-pages` — would make the site's contents depend on the site's contents, so a
bad publication becomes self-perpetuating. Checked-in manifests make the version
list reviewable in a pull request like any other change.

The cost: **forgetting to add the entry is possible**, and the result would be a
version that publishes correctly and that nothing links to. Section 7 covers the
guard.

---

## 6. The three URLs that must agree

For the version dropdown to work on a page, three separate values have to line
up. They are set in different places, and nothing about a rendered page reveals
a mismatch.

**1. `version_match` — what this page calls itself.** The theme compares it
against each manifest entry, with literally this line of JavaScript:

```js
e.match = e.version == DOCUMENTATION_OPTIONS.theme_switcher_version_match
```

So the page's stamp must **exactly equal** the `version` field of its own entry.
CCCL stamps each page with the directory it is served from — `unstable/` is
stamped `unstable`, `3.4.2/` is stamped `3.4.2`.

**2. `json_url` — where the browser fetches the manifest.** This is an absolute
URL baked into every page. It must name the host actually serving the page.

**3. The canonical URL** — the page's preferred address, which must include the
version, or every version of a page claims to be the same page.

### Why the site URL is derived, not configured

Because `json_url` is absolute, a build must know what host it will be served
from. Hard-coding production would mean every fork's documentation tells the
reader's browser to fetch *NVIDIA's* manifest — which, for a fork, is a file
that does not describe the fork's site.

GitHub Pages serves a project site at `https://<owner>.github.io/<repo>`, owner
lowercased. For `NVIDIA/cccl` that is exactly the production URL. So one rule
covers production and every fork, and a fork has nothing to remember:

```
NVIDIA/cccl          →  https://nvidia.github.io/cccl
someuser/cccl        →  https://someuser.github.io/cccl
```

An explicit `site-url` input overrides it, which is needed only for a custom
domain — not derivable from a repository name.

---

## 7. Failures that look like success

Every guard in this system exists because of a specific failure that **produces
a complete, renderable, correctly-deploying site that is wrong**. That is the
common thread: none of these show up as a red build. Several were found the
expensive way, while building this.

### The switcher points at a host that does not serve this site

**Symptom:** every page loads perfectly. The version dropdown is empty.

**Why invisible:** the page is fine. The manifest is fine. They simply are not
the same site. An HTTP check of "is the manifest reachable?" passes, because a
manifest *is* reachable — at the path you assumed, not the one the page names.

**Guard:** the site URL is derived from the repository (§6), and
[`smoke_site.py`](smoke_site.py) fetches **the URL each page actually declares**
rather than the one it expects to find.

### A published version is missing from the manifest

**Symptom:** `/cccl/cpp/3.5.0/` is complete and serves correctly. No dropdown
anywhere offers it. It is unreachable except by typing the URL.

**Guard:** the build refuses to finish if the manifest does not list the version
being published.

### The two manifests disagree

**Symptom:** nothing, today — because nothing reads `versions.json`. It becomes
a symptom the moment something does.

This is not hypothetical. At the reference revision, cuda-python's `cuda_core`
ships a `versions.json` stopping at **0.3.2** beside an `nv-versions.json`
reaching **1.2.0**, because each file is whatever some build last copied and
nothing compares them.

**Guard:** [`check_manifests.py`](check_manifests.py) fails the build if the two
disagree.

### `.nojekyll` is missing

**Symptom:** every URL returns 200. Every page is unstyled, and the version
dropdown is gone — because `_static/` was deleted by Jekyll (§2).

**Why invisible:** a smoke test that checks HTTP status codes passes completely.
The failure is only visible if you fetch an asset or look at the page.

**Guard:** the combined build emits `.nojekyll` and the artifact check requires
it; `smoke_site.py` fetches a real stylesheet, not just the HTML.

Worth noting: cuda-python's `.nojekyll` exists **only on its deployment branch**,
not in its source tree. Nothing would regenerate it if it were ever lost —
`clean: false` is the only reason it persists. CCCL puts it in the artifact so
every combined build re-asserts it.

### A stale directory is swept into a rebuild

**Symptom:** a release directory contains a complete second copy of itself at
`3.4.2/3.4.2/`, carrying whatever URLs an earlier build used.

This one was real: a rebuild produced **2,879 pages where 1,439 were expected**,
because the build script moved its output directory aside and copied it back
under the version name, sweeping up the previous run's output on the way.

**Guard:** build scripts clear their output directory first; the launch assembler
refuses any tree containing a version directory of its own name.

### A release builds nothing

**Symptom:** the workflow is green and the deployment succeeds, having published
an empty artifact.

Found by tracing the conditions rather than by running them: the build steps
were gated on the *caller's* `component` input, but a release passes
`component: all` and lets the tag decide. Every path was traced; one produced
nothing.

**Guard:** steps key off the *resolved* product, and a test asserts every
publication path builds something.

### A C++ artifact contains the Python tree

**Symptom:** Python pages served at `/cccl/cpp/3.4.2/python/...`, labelled with a
C++ version they never shipped under.

**Guard:** the C++ build fails if its output contains a top-level `python/`
directory — which is the signature of a source predating the split.

### How the guards are checked

A guard that does not actually fire is worse than no guard, because it is
believed. Three levels:

**The tests** (`docs/test_docs_build.py`) cover tag mapping, manifest membership
and agreement, stamp-versus-directory, product isolation, and the shape of the
workflow — including that the workflow *calls* each guard, since one written but
not wired in protects nothing.

**Mutation testing.** Each guard was deliberately broken to confirm the
corresponding test fails: flipping `clean: false` to `true`, unpinning the deploy
action, accepting pre-release tags, and regressing the build gating. All four
were caught, and the suite passed again once restored.

**Negative tests in CI**, which is the only level that proves a guard stops a
*real* publication. Dispatching a pre-release tag fails at label resolution with
every later step skipped — including the deploy — rather than publishing
anything.

The suite deliberately does not test Sphinx, the theme, or the deploy action.
Those are other people's software, and testing them here would mostly detect
their upgrades.

---

## 8. Where this departs from cuda-python

The instruction was to follow cuda-python's model rather than invent one. This
section records the differences in **both** directions, so the comparison is not
flattering by omission:

- eight places CCCL is stricter, each fixing something demonstrably wrong in the
  reference;
- one place the two diverge on policy rather than correctness;
- four things cuda-python has that CCCL does not.

Everything not listed here follows the reference implementation.

At a glance — note that every one of the eight is a *correctness* fix or a small
robustness addition. None changes the architecture:

| # | Deviation | Why |
|---|---|---|
| 1 | Stamp pages with the served directory | otherwise the dropdown never highlights the current page |
| 2 | Check the two manifests agree | they have silently drifted in the reference |
| 3 | Derive the site URL from the repository | otherwise a fork's switcher is empty |
| 4 | Refuse to publish a version the manifest omits | otherwise it publishes unreachable |
| 5 | Two build modes, not build-then-delete | a release never creates a `unstable/` it must remember to remove |
| 6 | Root `objects.inv` only from a `unstable` build | otherwise a release downgrades it |
| 7 | Reject pre-release tags explicitly | not left to convention |
| 8 | Emit `.nojekyll` from the build | otherwise nothing can restore it |

### Deviations

**1. Pages are stamped with the directory they are served from.**

cuda-python stamps `unstable/` with the *source* version. Its live
`cuda-core/unstable/` carries:

```
theme_switcher_version_match = '1.2.1.dev72'
```

while its manifest lists `unstable`. Those never match, so the dropdown on that
page can never highlight the page you are on. CCCL passes the *publication
label* to Sphinx separately from the source version, so `unstable/` is stamped
`unstable` and matches.

**2. The manifests are checked for agreement before publication.**

cuda-python does not, and its two manifests have drifted (§7). Four lines of
check.

**3. The site URL is derived from the repository.**

cuda-python hard-codes production, so its forks cannot produce a working
switcher. CCCL derives it, which yields the production URL for `NVIDIA/cccl`
unchanged (§6).

**4. The build refuses to publish a version its manifest omits.**

cuda-python has no such check. Without it, forgetting the manifest entry is
silent.

**5. Two explicit build modes instead of build-then-delete.**

cuda-python's component build always produces a `unstable/` copy, and its release
workflow deletes that copy afterwards. CCCL expresses the same contract as two
modes — `unstable-only` and `--label <version>` — so a release job never creates a
`unstable/` it must remember to remove. The observable output is identical.

**6. The component-root `objects.inv` is written only by a `unstable` build.**

cuda-python's script copies it unconditionally, so a release overwrites the
root inventory with an older release's — contradicting the stated intent of that
line in its own script ("ensure that the Sphinx reference uses the latest docs").

**7. Pre-release tags are rejected explicitly** rather than left to convention.

**8. `.nojekyll` is emitted by the build** rather than existing only on the
deployment branch (§7).

### One divergence of policy, not correctness: the old scheme is removed

cuda-python still serves its previous URL scheme. Its `gh-pages` carries 25
CUDA-Toolkit-versioned directories from before it moved to per-component
namespaces, and they are live today:

```
/cuda-python/12.6.1/   200
/cuda-python/13.4.1/   200
```

That is not a decision so much as the default behaviour of the model:
`clean: false` never deletes, so a retired layout persists indefinitely unless
somebody removes it by hand.

CCCL chose the other way. `/cccl/unstable/` and its Python subtree return 404,
because the one-time conversion deleted them. Neither choice is wrong. The
trade-off is:

| | keeps old URLs alive | cost |
|---|---|---|
| cuda-python | yes | the site carries two schemes indefinitely; old paths document versions under a naming convention that no longer applies |
| CCCL | no | existing links break; there is no redirect, by design (§3) |

CCCL's old tree had no release versions in it at all, so most of it had no
successor to redirect *to* — preserving it would have meant serving a permanent
copy of one moment of the development branch under a name (`unstable`) the
project no longer uses.

### What cuda-python has that CCCL does not

Recording these so the comparison is not one-sided. None of them touch the
versioning model; all are CI facilities built around it.

**Rendered-link checking.** cuda-python runs `lycheeverse/lychee-action` over
the built HTML with `--include-fragments=full`, failing the build on a broken
link or a dangling anchor. CCCL has no equivalent. This is the most substantive
gap.

**Per-pull-request documentation previews.** Their site has a `pr-preview/`
tree, so a reviewer can read a branch's rendered documentation before it merges.

**Release-workflow integration.** Their `build-docs.yml` is called from
`release.yml`, gated on release-notes checks, with a first-class dry-run mode
that redirects the deployment to a named branch. CCCL's release publication is a
standalone manual dispatch — the same capability, not wired into a release
process, because CCCL's release process has a different shape.

**Coverage reporting** is published to the same site (`/coverage/`).

They also carry a `run-id` input, used to fetch wheel artifacts built earlier in
their pipeline. That is package plumbing rather than part of the versioning
model, and was deliberately not copied.

### Followed exactly

The architecture, and its consequences, are inherited as-is:

- one reusable workflow serving both publication paths;
- `clean: false` additive deployment, with the same deploy action at the same
  pinned SHA;
- checked-in per-product manifests owned by the release;
- `unstable` meaning the development branch;
- exact `MAJOR.MINOR.PATCH` directories with no rolling alias;
- no automatic retirement of old versions;
- repair by re-running the workflow, not by a rollback system.

That last group includes real trade-offs — files removed from a build are not
removed from the site, versions accumulate until someone intervenes, and two
publications can in principle overlap. These are accepted deliberately, as the
price of following a system that is known to work rather than building a new
one.

---

## 9. Operating it

### Merging to `main`

Nothing to do. Both `unstable/` trees rebuild from that commit. Releases are
untouched.

### Publishing a release

1. **Before tagging**, add the version to both manifest files for that product
   (`docs/cpp_site/` or `docs/python_site/`). The build stops if you forget.
2. **Actions → Deploy CCCL Documentation → Run workflow**, and give it the exact
   tag. The tag alone decides product and destination.
3. **Check** the affected URLs, or run `python3 docs/smoke_site.py`.

### Rehearsing

The workflow takes a `docs-branch` input. Point it at any branch other than
`gh-pages` to publish a complete artifact somewhere harmless.

A rehearsal on a fork needs nothing extra — the site URL derives from the
repository (§6).

### When a publication fails

Re-run it. Deployment is additive, so a re-run cannot damage another product or
an earlier version.

If a release published *wrong content*, the repair is a corrective publication:
fix the source, tag a new patch, publish that. There is no rollback button,
deliberately. The deployment history on `gh-pages` is ordinary commits, and a
maintainer can revert one.

### Expect a little churn between builds

The documentation build is not byte-reproducible across machines, and that is
normal rather than a symptom. Rebuilding the same commit on a different machine
changed **6 pages out of 1,439**.

The cause is benign. When a class inherits a documented member, that member is
rendered on more than one page, and a cross-reference to it may legitimately
resolve to either. Which one Breathe picks depends on the order Sphinx processed
the documents, which depends on how the parallel build was scheduled. Both
targets contain the anchor, so both links work.

Worth knowing only so that a deployment diff touching a handful of unrelated API
pages does not look like a problem.

### Capacity

GitHub Pages refuses a site over **1 GB**. Measured at launch:

| tree | size |
|---|---|
| `cpp/unstable` | 180 MB |
| `cpp/3.4.2` | 118 MB |
| `python/unstable` | 8 MB |
| `python/1.1.1` | 8 MB |
| **total** | **314 MB** |

C++ consumes the budget: ~118 MB per release against ~8 MB for Python. The
remaining 710 MB is roughly **six more C++ releases**. Python is not a practical
constraint at this ratio.

This is the one place the inherited model has a finite runway. When it
approaches, retiring a version is a deliberate decision: delete the directory
from `gh-pages` and remove its entry from both manifests.

---

## 10. What this deliberately is not

The design was scoped by deciding what *not* to build. Each of these was
considered and rejected:

- **a publication system** — no custom publisher, no deployment planner, no
  transaction protocol around Pages;
- **generated manifests** — the version list is not discovered from the live
  site;
- **provenance files** — no per-directory record of what produced it;
- **rollback machinery** — repair is a re-run or a corrective release;
- **fuzzy 404 routing** — a missing URL gets an ordinary 404;
- **legacy URL preservation** — the old scheme is retired, not redirected;
- **automatic retirement** — nothing deletes an old version on its own;
- **a release compatibility matrix** — no database claiming which C++ release
  "goes with" which Python release. Cross-product links are ordinary links.

### How this list compares to cuda-python

Seven of the eight are equally absent from the reference implementation, which
is the main reason to be comfortable leaving them out: this is not a stripped-
down version of a richer system, it is the same system.

The exception is **legacy URL preservation**. cuda-python retains its previous
scheme — 25 CUDA-Toolkit-versioned directories still served — while CCCL removed
its old layout during the conversion. Section 8 covers the trade-off.

A note on how firmly each is established, since "the reference does not do this
either" is load-bearing. The absence of 404 routing, automatic retirement, and
the retained legacy scheme were confirmed against the **live site**: stock
GitHub 404s, `cuda-core/0.1.0` still returning 200 beside a 19-entry manifest,
and the old directories serving. Checked-in rather than generated manifests, and
the lack of rollback machinery, were confirmed by reading the repository and its
workflows. The absence of provenance files and of a compatibility matrix rests
on searching the source tree and the rendered site — reasonable, but a search
rather than a proof.

The test suite is scoped the same way. It does not test Sphinx, the theme, or
the deploy action. It tests the things that fail *silently*: tag mapping, stamp
and manifest agreement, product isolation, and the shape of the workflow.

---

## 11. Appendix: the file map

**Configuration**

| file | role |
|---|---|
| `docs/conf.py` | Sphinx configuration for C++; excludes the Python sources |
| `docs/python_conf/conf.py` | Sphinx configuration for Python |

**Build scripts**

| file | role |
|---|---|
| `docs/gen_docs.bash` | builds C++, into `unstable/` or an exact version |
| `docs/gen_python_docs.bash` | builds Python, same two modes |
| `docs/gen_all_docs.bash` | both products plus the chooser — the development build |

**Site assets** (checked in, copied into artifacts)

| file | role |
|---|---|
| `docs/index.html` | the chooser |
| `docs/cpp_site/`, `docs/python_site/` | each product's redirect and two manifests |

**Supporting scripts**

| file | role |
|---|---|
| `docs/release_label.py` | tag → (component, version) |
| `docs/check_manifests.py` | manifest membership and agreement; URL retargeting |
| `docs/smoke_site.py` | checks a published site over HTTP |

**Workflows**

| file | role |
|---|---|
| `.github/workflows/build-docs.yml` | the reusable build-and-deploy workflow |
| `.github/workflows/docs-deploy.yml` | the two callers: push to `main`, and dispatch |

**Tests and documentation**

| file | role |
|---|---|
| `docs/test_docs_build.py` | the silent-failure guards |
| `docs/publishing-overview.md` | short orientation for newcomers |
| `docs/PUBLISHING.md` | the maintainer procedure |
| `docs/publishing-design.md` | this document |
