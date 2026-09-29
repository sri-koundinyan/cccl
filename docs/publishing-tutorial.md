# How CCCL's documentation gets published

A tutorial on the design.

You merge a pull request. Fifteen minutes later, a page on the web has changed.
This document explains everything that happens in between, and why it happens
that way.

It is written for someone who has never looked at this pipeline. No Sphinx
experience is assumed. Every piece of jargon is defined where it first matters,
and nowhere else, so you can read straight through.

**Where this sits among the other documents.** There are four, and they are
deliberately different kinds of writing:

| Document | Answers |
| --- | --- |
| `publishing-overview.md` | "What changed, in two minutes?" |
| `PUBLISHING.md` | "I need to ship a release. What do I type?" |
| **this document** | "How does it work, and why is it built this way?" |
| `publishing-design.md` | "What exactly does clause X say?" (the reference) |

Read this one once. Reach for the design document when you need a specific
guarantee, a failure mode, or the file map.

---

## Contents

1. [The problem this solves](#1-the-problem-this-solves)
2. [What a documentation build actually is](#2-what-a-documentation-build-actually-is)
3. [Two projects, not one](#3-two-projects-not-one)
4. [The shape of the site](#4-the-shape-of-the-site)
5. [How a page knows which version it is](#5-how-a-page-knows-which-version-it-is)
6. [How the version dropdown works](#6-how-the-version-dropdown-works)
7. [The two ways to publish](#7-the-two-ways-to-publish)
8. [Deployment adds, it never removes](#8-deployment-adds-it-never-removes)
9. [The guards, and the silent failures they catch](#9-the-guards-and-the-silent-failures-they-catch)
10. [Worked example: a merge to `main`](#10-worked-example-a-merge-to-main)
11. [Worked example: releasing C++ 3.5.0](#11-worked-example-releasing-c-350)
12. [One page in both books](#12-one-page-in-both-books)
13. [Things to keep in mind](#13-things-to-keep-in-mind)
14. [The file map](#14-the-file-map)

---

## 1. The problem this solves

CCCL ships two products on two schedules. The C++ libraries (Thrust, CUB,
libcu++, CUDA Experimental) release as `3.4.2`, `3.5.0`, and so on. The Python
package `cuda-cccl` releases as `1.1.1`, `1.2.0`. They are versioned
independently and they always have been.

Their documentation was not. One build produced one tree, published at one URL,
with the Python pages nested inside the C++ pages:

```
/cccl/unstable/                 everything, built from main
/cccl/unstable/python/          Python docs, inside the C++ tree
```

Three consequences followed from that single shape.

**No release documentation existed at all.** Only `main` was ever published. If
you were using C++ 3.4.2, there was no page describing 3.4.2. There was only a
page describing whatever `main` looked like this morning, which might document
functions that do not exist in your release, and might omit behaviour that does.

**Neither product could be versioned without the other.** A directory can carry
one version number. With both products in one directory, publishing C++ 3.5.0
would have meant publishing the Python docs under `3.5.0` as well, a version the
Python package has never had.

**A Python documentation fix could not ship without a C++ rebuild**, because
there was only one build.

The redesign gives each product its own namespace, its own version list, and its
own publication trigger:

```
/cccl/                          a chooser: C++ or Python
/cccl/cpp/unstable/             C++, built from main
/cccl/cpp/3.4.2/                C++ release 3.4.2
/cccl/python/unstable/          Python, built from main
/cccl/python/1.1.1/             Python release 1.1.1
```

Everything in the rest of this document exists to make that shape work, keep it
honest, and stop it from failing quietly.

> The architecture is adapted from
> [cuda-python](https://github.com/NVIDIA/cuda-python), which has the same
> problem: several independently released components living in one repository.
> Section 8 of the design document lists exactly where CCCL follows it and where
> it deviates.

---

## 2. The build stage

The publishing design treats the build as a black box: it never inspects a page
and would work identically if the HTML were written by hand. So this section is
deliberately bounded. It tells you what goes in, what comes out, and the three
facts the rest of the document depends on. Everything past that is in the
appendix at the end of the section, and you only need it the day a page renders
wrong.

### What goes in

Four inputs, and only the first two look like "documentation":

**1. The committed source pages.** 480 `.rst` and `.md` files under `docs/`,
plus `conf.py`:

```
docs/libcudacxx/   332 pages     docs/cccl/            15
docs/thrust/        54           docs/python/          10
docs/cub/           17           docs/howto/            1
docs/infrastructure/ 16          docs/cudax/            7
```

**2. The library headers.** `cub/`, `thrust/`, `cudax/`, `libcudacxx/`. Easy to
forget, and it is why the build is slow: the docs build parses the actual C++ to
extract the API.

**3. `docs/requirements.txt`**, which pins the toolchain.

**4. Two values from the environment.** `SPHINX_CCCL_VER`, which is both the
version and the directory this build publishes into, and `CCCL_DOCS_SITE_URL`,
the host it will be served from. These are the only inputs the publishing system
supplies, and §5 follows the first of them all the way to the published page.

### The command

`docs/gen_docs.bash` resolves its own location and moves there before doing
anything, so every relative path below is relative to `docs/`, and the script
behaves the same from any working directory:

```bash
SCRIPT_PATH=$(cd "$(dirname "${0}")"; pwd -P)
cd "$SCRIPT_PATH"
```

Everything then funnels into one invocation:

```bash
python -m sphinx.cmd.build -b html -d "${BUILDDIR}/doctrees" -j auto \
    "."                         # source root:      docs/
    "${VERSIONED_HTML_DIR}"     # output directory: _build/artifacts/docs/cpp/<label>
```

Two positional arguments: read from here, write to there. That is the build.

**The source root** (Sphinx calls it the *source directory*) is that first
argument. Every internal link is resolved relative to it, which is why §3 and
§12 both turn on it.

### What comes out

One directory. For C++ that is **1,694 HTML pages, 180 MB**, and its top level
looks like this:

```
_build/artifacts/docs/cpp/unstable/
    index.html          60 KB   the landing page
    objects.inv        714 KB   the symbol inventory
    searchindex.js     6.7 MB   the client-side search database
    genindex.html      1.6 MB   generated alphabetical index
    search.html         60 KB
    _static/                    CSS, JS, fonts
    _sources/                   copies of the input, for "view page source"
    cub/  thrust/  cudax/  libcudacxx/  cccl/  infrastructure/  howto/  ...
```

`objects.inv` is a sibling of `index.html` at the root of the *output*. It is a
zlib-compressed index mapping every documented symbol to a relative URL:

```
cuda::experimental::stf::no_init  cpp:class  1  cudax/api/class...html#_CPPv4N4...E  -
```

48,835 entries for the C++ build. Other projects fetch it with Sphinx's
`intersphinx` extension, so they can write a symbol name and get a working link
without hardcoding a URL. Because the URIs are relative, the consumer supplies
the base.

### The three facts that matter downstream

**1. A build is `(source root + conf.py) -> one self-contained output
directory`, and that directory is laid out as the final website.** Not a build
product that gets rearranged later. Every path in it is already a real URL path:

```
_build/artifacts/docs/cpp/unstable/index.html    ->   /cccl/cpp/unstable/index.html
_build/artifacts/docs/cpp/nv-versions.json       ->   /cccl/cpp/nv-versions.json
```

Deployment copies the tree and computes nothing. The *build* chose the layout,
by writing into `.../cpp/${VERSION}/`. This is why §5's label chain is the heart
of the design: the label picks the output directory, and the output directory is
the URL.

**2. Most C++ pages do not exist in the repository.** Roughly 1,225 of those
1,694 are generated during the build from the C++ headers, and are gitignored.
Three consequences you will actually meet: the build takes about 15 minutes,
grepping the repo for a published API page finds nothing, and rebuilding
identical sources can produce slightly different output (§13).

**3. Warnings are errors.** The builds run with `-W`, so anything Sphinx
complains about fails the job. In particular, a page in no **toctree** is an
*orphan* and warns, and toctrees are also what draw the sidebar. That is why
`docs/conf.py` lists `PUBLISHING.md`, `publishing-design.md` and this file in
`exclude_patterns`: they sit beside the sources, belong in no reader-facing
sidebar, and would otherwise fail the build.

There is also a fourth fact that is about the build but belongs to operations:
**the toolchain is an unpinned surface that can break the build without any
change to CCCL.** §13 covers the day that happened.

### Appendix: the pipeline, for when something renders wrong

You do not need this to reason about versioning, routing or deployment. You need
it when a page comes out wrong and you have to work out which stage produced the
mistake. Traced through one real symbol:

**Stage 1, the C++ source.** `cudax/include/cuda/experimental/__stf/internal/constants.cuh`:

```cpp
/**
 * @brief A tag type used in combination with the reduce access mode to
 * indicate that we should not overwrite a logical data [...]
 */
class no_init
{};
```

**Stage 2, Doxygen 1.9.6** (built from source during the build, so it cannot
drift with the runner) parses the headers and writes XML. One file per
**compound**, meaning a thing that can contain other things: class, struct,
union, namespace, file, directory, group, page. Members live *inside* their
parent's file, not in files of their own. For `cudax` that is 474 compound files
holding 3,692 members.

```xml
<compounddef id="classcuda_1_1experimental_1_1stf_1_1no__init" kind="class">
  <compoundname>cuda::experimental::stf::no_init</compoundname>
  <briefdescription><para>A tag type used in combination with [...]</para></briefdescription>
  <location file="include/cuda/experimental/__stf/internal/constants.cuh" line="123"/>
</compounddef>
```

Structure and prose, no formatting. Doxygen knows nothing about Sphinx.

**Stage 3, `auto_api_generator`** (CCCL's own Sphinx extension, in
`docs/_ext/`) writes one stub page per entity. It is hooked to `config-inited`,
the first event Sphinx fires, so this happens *inside* the Sphinx run, not
before it:

```rst
.. AUTO-GENERATED by auto_api_generator.py - DO NOT EDIT

:orphan:

cuda::experimental::stf::no_init
================================

.. doxygenclass:: cuda::experimental::stf::no_init
   :project: cudax
   :members:
```

Note that the stub contains no documentation. It is a title and a pointer. Note
also the explicit `:orphan:`, which is how these pages opt out of the toctree
rule above: they are reached by search and cross-reference, not by the sidebar.

**Stage 4, Breathe.** Breathe is not a converter you run and it writes no files.
It is a Sphinx extension that supplies the `.. doxygenclass::` directive. When
Sphinx renders the stub and reaches that directive, Breathe reads the Doxygen
XML at that moment and returns an in-memory document tree, which Sphinx writes
out as HTML along with everything else.

So the shape is:

```
headers  --Doxygen-->  XML
                         |
                         v
      .rst stub  <--auto_api_generator--,  then  Sphinx + Breathe  -->  HTML + objects.inv
                                         '------- all one Sphinx run -------'
```

Only Doxygen runs as a separate step. Stages 3 and 4 are the same process.

**What `conf.py` does**, since "which files to exclude" is one line of a much
larger job. It registers the extensions (without which `.. doxygenclass::` is an
unknown directive), tells Breathe where the XML is, sets the theme and the
version switcher's `json_url` and `version_match`, sets `html_baseurl`,
suppresses known-noisy Breathe warning categories (which matters under `-W`),
and reads `SPHINX_CCCL_VER`. That last one is where the publishing system
reaches into the build, and §5 picks up the thread.

---

## 3. Two projects, not one

Here is the first design decision, and the one that shapes the most downstream
behaviour.

CCCL runs **two separate Sphinx projects** out of one repository.

```
C++      source root  docs/            config  docs/conf.py        (found by default)
Python   source root  docs/python/     config  docs/python/conf.py  (found by default)
```

The Python build is invoked like this, from `docs/gen_python_docs.bash`:

```bash
python -m sphinx.cmd.build -b html \
    "${SCRIPT_PATH}/python" \
    "${VERSIONED_HTML_DIR}"
```

`-c` is what separates the configuration directory from the source directory.
That separation is not decoration. It means a release's *own* sources can be
built with configuration that postdates the release, which is what makes it
possible to publish documentation for a tag that was cut before this system
existed.

The C++ build needs no `-c`, because its config sits in its source root already.
This asymmetry is worth holding onto. It is the reason §12 works the way it does.

**How the C++ build avoids swallowing the Python pages.** `docs/python/` is
inside `docs/`, which is the C++ source root, so by default Sphinx would pick it
up. One line in `docs/conf.py` prevents that:

```python
exclude_patterns = [
    "python",
    ...
]
```

Without it, a C++ release would publish Python pages at
`/cccl/cpp/3.5.0/python/`, labelled with a C++ version the Python package never
shipped under. That is not a hypothetical: it is what the old combined layout
did, and two independent checks exist solely to make sure it cannot come back
(§9).

**Why two projects rather than one with two halves?** Because a version number
is a property of a build. One project produces one output directory, and that
directory can carry exactly one version. Two independently versioned products
therefore need two builds. Everything else follows from that.

---

## 4. The shape of the site

```
/cccl/                     index.html, a chooser. Claims no version.
/cccl/cpp/                 the C++ component root
/cccl/cpp/unstable/        built from main
/cccl/cpp/3.4.2/           release 3.4.2
/cccl/cpp/nv-versions.json the switcher manifest (§6)
/cccl/cpp/objects.inv      convenience inventory, tracking unstable
/cccl/python/              the same five things, with 1.1.1
```

Three naming decisions are load-bearing.

**`unstable`, not `latest`.** This directory holds documentation built from
`main`. It describes code that is in no release yet. "Latest" reliably reads as
"the newest release", which is the opposite of the truth, and a reader who
misunderstands it gets confidently wrong answers about code they cannot use
yet. `unstable` cannot be misread that way. (cuda-python calls the same thing
`latest`; this is a deliberate deviation.)

**Exact versions, never rolling ones.** `3.4.2`, not `3.4`. A rolling `3.4`
directory would mean the content at a URL changes under a reader who bookmarked
it, and there would be no way to cite the documentation as it stood for a
specific release. The build enforces this: the version label must match
`^(unstable|[0-9]+\.[0-9]+\.[0-9]+)$` or the build stops.

**The site root is a chooser, not a redirect.** Landing on `/cccl/` asks which
product you want. It deliberately does not auto-forward, because there is no
correct default: a Python user sent to C++ docs has been actively misled.

---

## 5. How a page knows which version it is

This is the single most useful thread to trace end to end, because almost every
guard in the system exists to keep some part of it aligned.

A published page needs to know its version for three separate purposes, and all
three come from one value.

**Step 1. The workflow computes a label.**

For a development build, the label is fixed:

```yaml
if [[ "${IS_RELEASE}" != "true" ]]; then
  echo "label=unstable" >> "${GITHUB_OUTPUT}"
```

For a release, the label is derived from the tag by `docs/release_label.py`:

```
v3.4.2        ->  component cpp     label 3.4.2
python-1.1.1  ->  component python  label 1.1.1
```

The grammar is anchored and exact:

```python
GRAMMAR = {
    "cpp":    re.compile(r"^v([0-9]+\.[0-9]+\.[0-9]+)\Z"),
    "python": re.compile(r"^python-([0-9]+\.[0-9]+\.[0-9]+)\Z"),
}
```

A pre-release tag such as `v3.5.0-rc0` matches neither pattern and is rejected,
rather than being quietly mapped onto `3.5.0`, which would publish unreleased
documentation at a released version's URL.

> The `\Z` rather than `$` is not a stylistic choice. In Python, `$` also matches
> just before a trailing newline. These values are written to `$GITHUB_OUTPUT`
> as `key=value` lines, where an embedded newline would silently start a second
> key.

**Step 2. The label becomes the output directory.**

```bash
VERSION="${LABEL:-${SPHINX_CCCL_VER:-unstable}}"
VERSIONED_HTML_DIR="${BUILDDIR}/artifacts/docs/cpp/${VERSION}"
```

The artifact is built in the shape of the final site, so every path inside it is
already a real site path. Nothing rearranges it later.

**Step 3. The same label is exported to Sphinx.**

```bash
export SPHINX_CCCL_VER="${VERSION}"
```

**Step 4. `conf.py` reads it and uses it for two things.**

```python
_publication_label = release   # validated by the build script

html_baseurl = f"{_component_root}{_publication_label}/"

html_theme_options = {
    "switcher": {
        "json_url":      f"{_component_root}nv-versions.json",
        "version_match": _publication_label,
    },
}
```

`html_baseurl` becomes the **canonical link** on every page: a `<link
rel="canonical">` tag telling search engines which URL is the authoritative one
for this content. The label has to be part of it. If every version claimed the
same canonical URL, the archive would compete with itself for indexing.

`version_match` is the version the page *claims to be*, and §6 explains what
reads it.

**Step 5. The build verifies the claim matches the directory.**

```bash
if ! grep -q "version_match = '${VERSION}'" "${VERSIONED_HTML_DIR}/index.html"; then
    echo "Error: pages are not stamped '${VERSION}'." >&2
    exit 1
fi
```

Read that again, because it is the shape of nearly every check in this system.
The build is confirming that the directory a page is served from and the version
that page claims to be are the same string. If they drift, the site renders
perfectly and a reader notices nothing, while the dropdown quietly stops
highlighting the page they are on.

So the chain is:

```
tag or push  ->  label  ->  output directory
                       ->  canonical URL
                       ->  version_match stamp on every page
                            ^ checked against the directory before shipping
```

One value, three uses, one assertion that they agree.

---

## 6. How the version dropdown works

The version selector in the page header is not built at build time. It is
assembled **in the reader's browser, after the page loads**. Understanding this
explains an entire class of failure.

Each page ships two facts, both from §5:

- `json_url`, an absolute URL for a manifest listing every version
- `version_match`, the version this page claims to be

The theme's JavaScript fetches the manifest, and for each entry decides whether
it is the current one, roughly:

```js
entry.match = entry.version == DOCUMENTATION_OPTIONS.theme_switcher_version_match
entry.name  = entry.name || entry.version
```

The manifest, `docs/cpp_site/nv-versions.json`, is plain data:

```json
[
  { "version": "unstable", "url": "https://nvidia.github.io/cccl/cpp/unstable/" },
  { "version": "3.4.2",    "url": "https://nvidia.github.io/cccl/cpp/3.4.2/" }
]
```

Four consequences fall straight out of this design.

**The URLs are absolute and the browser follows them.** If a page is served from
one host but its manifest names another, the dropdown either fails to load or
navigates the reader off your site. This is exactly what happened on the fork
early on: pages built for `nvidia.github.io` were served from
`sri-koundinyan.github.io`, so every fetch 404'd and the dropdown came up empty,
on a site that otherwise looked completely healthy.

The fix is to derive the site URL from the repository rather than hardcoding it:

```bash
owner="${REPOSITORY%%/*}"
name="${REPOSITORY#*/}"
url="https://${owner,,}.github.io/${name}"
```

GitHub Pages serves a project site at `https://<owner>.github.io/<repo>` with the
owner lowercased, which for `NVIDIA/cccl` is exactly the production URL. One
rule covers production and every fork, and a fork does not have to remember to
pass anything. Only a custom domain needs the explicit `site-url` input.

**The manifest lives at the component root, not inside a version.** It has to
list every version, so it cannot live inside one of them. Hence
`json_url` is built from `_component_root`, deliberately not from `html_baseurl`.

**A version absent from the manifest is unreachable.** The documentation
deploys, renders, and is completely correct, and no reader can get to it,
because the dropdown is the only thing that links versions together. This is
why the manifests are **checked in and edited by hand during release
preparation**, not discovered by scanning the site. A reviewed file in the
release commit is a decision; a scan is a guess about what happens to be lying
around on a branch.

**There is one manifest per product.** cuda-python ships a second file,
`versions.json`, carrying the same list in a different shape. CCCL does not,
because nothing reads it — not the theme, not the switcher. An unread file
drifts: on cuda-python's live site `cuda_core/versions.json` stops at `0.3.2`
while its `nv-versions.json` reaches `1.2.0`, with no visible consequence.

---

## 7. The two ways to publish

There are exactly two, and they run **the same reusable workflow** so they
cannot drift apart.

```
push to main              ->  build both products from that commit  ->  both unstable/ trees
workflow_dispatch + tag   ->  build the tagged product              ->  that product's version/
```

In `.github/workflows/docs-deploy.yml`:

```yaml
jobs:
  development:
    if: ${{ github.event_name == 'push' }}
    uses: ./.github/workflows/build-docs.yml
    with:
      component: all
      is-release: false

  release:
    if: ${{ github.event_name == 'workflow_dispatch' }}
    uses: ./.github/workflows/build-docs.yml
    with:
      component: all
      git-tag: ${{ inputs.git-tag }}
      is-release: true
```

**Development publishes both products together.** One push advances both, so
building them from one commit means the two `unstable/` trees never describe
different states of the repository. Only *releases* are independent.

**A release publishes one product, and the tag alone decides which.** There is
no directory input, no component dropdown, nothing a person can fill in
incorrectly. `v3.5.0` can only ever become `/cccl/cpp/3.5.0/`. A Python release
cannot be routed into the C++ namespace, because nothing in the system accepts a
destination as an argument.

This is a general principle worth naming: **the routing is derived, not
supplied.** Wherever a human could type a wrong value, the system computes the
value instead.

---

## 8. Deployment adds, it never removes

Deployment uses `JamesIves/github-pages-deploy-action`, pinned by commit SHA,
with one setting that defines the entire model:

```yaml
- name: Deploy documentation
  uses: JamesIves/github-pages-deploy-action@fa24774553152dd7873cd16ebd8d959b010c5445  # v4.9.0
  with:
    branch: ${{ inputs.docs-branch }}
    folder: docs/_build/artifacts/docs/
    target-folder: docs/
    clean: false
```

`clean: false` means the deployment **copies in the paths the artifact
contains, and touches nothing else.** It is a copy, not a sync. It never
compares the artifact against the site, so it can never decide something is
missing and delete it.

That one setting is what makes the whole design work without a custom publisher:

- A Python release writes only under `python/1.2.0/`, so every C++ path is
  untouched by construction, not by policy.
- Publishing `3.5.0` leaves `3.4.2` alone. Versions accumulate safely.
- A re-run cannot damage anything it did not build.

**Now the flip side, which you have to understand or it will surprise you.**

Because deployment never removes, **a page dropped from a build is not dropped
from the site.**

Rename `foo.md` to `foo2.md` and push. The next deployment writes `foo2.html`
and everything that links to it: the sidebars, the search index and
`objects.inv` are all rebuilt without `foo`. But `foo.html` is still sitting on
the branch, so the URL still resolves and still serves the old content. Nothing
links to it. It is invisible to every reader who navigates or searches. It is
perfectly live to anyone holding the link.

Note carefully what this does and does not mean:

- **It is not link rot.** An old bookmark keeps working. That is usually the
  behaviour you want.
- **It only happens where a deployment writes into a directory that already has
  files**, which in practice is the two `unstable/` trees. A release directory
  is written once and never written again, so it never accumulates anything.
- **Cleanup is manual**, a `git rm` on the `gh-pages` branch. There is no
  automation, deliberately: an automatic remover is a script whose failure mode
  is deleting published documentation.

This was demonstrated live during development. A prototype page was renamed
twice, and each time the old HTML kept serving with nothing linking to it, until
it was removed by hand.

---

## 9. The guards, and the silent failures they catch

Every check in this system exists because of one specific way the site can be
broken while still looking perfect. That framing is the useful one: do not read
these as validation, read each as a named failure that would otherwise ship.

| The check | The failure it prevents | Why you would not notice |
| --- | --- | --- |
| Version stamp matches the directory (§5) | Pages claim a version they are not served from | Renders perfectly; the dropdown just never highlights the current page |
| Version is listed in `nv-versions.json` | Publishing docs nothing links to | The docs are correct and complete, and unreachable |
| Label matches `unstable` or `X.Y.Z` | A rolling `3.4` directory | Content silently changes under a bookmarked URL |
| Tag matches the exact release grammar | `v3.5.0-rc0` publishing as `3.5.0` | Unreleased docs at a released version's URL |
| No `python/` subtree in a C++ artifact | Python pages under a C++ version | The pages are fine; their version number is a lie |
| `index.html` and `objects.inv` exist | A build that produced nothing | A deployment can succeed with an empty artifact |
| `.nojekyll` is present | Jekyll dropping `_static/` | Every page returns 200, with no stylesheets and no dropdown |

That last one deserves a sentence, because it is the most counterintuitive.
GitHub Pages runs Jekyll unless a `.nojekyll` file is present, and Jekyll ignores
directories whose names begin with an underscore. Sphinx puts every stylesheet
and script in `_static/`. So without that empty file, every URL still resolves,
every page still has its text, and the site is unstyled and the switcher is
gone.

**Where these run.** Some are in the build scripts, some in the workflow's
"Check the artifact" step, and all of them fail before the deploy step. The
negative cases have been exercised in real CI: a pre-release tag and a
version missing from the manifest both stopped the run with `Deploy
documentation` skipped.

---

## 10. Worked example: a merge to `main`

A pull request merges. Follow it through.

**1. The trigger.** `docs-deploy.yml` matches `on: push: branches: [main]` and
starts the `development` job with `component: all`, `is-release: false`.

**2. Checkout.** `ref: ${{ inputs.git-tag || github.sha }}`. No tag was supplied,
so it checks out the merge commit.

**3. Label.** Not a release, so `label=unstable`, `components=all`.

**4. Site URL.** No `site-url` input, so it is derived: for `NVIDIA/cccl`,
`https://nvidia.github.io/cccl`.

**5. Build.** `./docs/gen_all_docs.bash`, which is short enough to read whole:

```bash
./gen_docs.bash unstable-only "$@"
./gen_python_docs.bash unstable-only "$@"
cp "${SCRIPT_PATH}/index.html" "${ARTIFACTS}/index.html"
touch "${ARTIFACTS}/.nojekyll"
```

Both products, then the two files that describe the site as a whole. Note that
the site shell is added *here* and not by either component build. A single
component build cannot know which versions exist or which product a reader
chose, so it deliberately writes no chooser, no manifest it did not copy, and no
`.nojekyll`.

**6. Artifact.** Laid out as final site paths:

```
docs/
  index.html  .nojekyll
  cpp/     index.html  nv-versions.json  objects.inv  unstable/
  python/  index.html  nv-versions.json  objects.inv  unstable/
```

**7. Checks.** Stamps, manifests, no `python/` inside `cpp/unstable/`,
`index.html` and `objects.inv` present, the shell present.

**8. Deploy.** Copied onto `gh-pages` under `docs/`, with `clean: false`. Both
`unstable/` trees are replaced. `cpp/3.4.2/` and `python/1.1.1/` are not in the
artifact, so they are not touched.

Elapsed: about 15 minutes, nearly all of it Doxygen and Sphinx.

---

## 11. Worked example: releasing C++ 3.5.0

**Step 1, and the one that is easy to forget: edit the manifests first.**

In the release-preparation commit, add the version to both files under
`docs/cpp_site/`:

```json
[
  { "version": "unstable", "url": "https://nvidia.github.io/cccl/cpp/unstable/" },
  { "version": "3.5.0",    "url": "https://nvidia.github.io/cccl/cpp/3.5.0/" },
  { "version": "3.4.2",    "url": "https://nvidia.github.io/cccl/cpp/3.4.2/" }
]
```

That is the only file to edit. It is reviewed like any other
change. If you skip it, the build stops and says so; it will not publish
documentation nothing links to.

**Step 2. Tag the release** as `v3.5.0`.

**Step 3. Run the workflow.** Actions, then *Deploy CCCL Documentation*, then
*Run workflow*, and give it the exact tag.

What happens:

| | |
| --- | --- |
| Checkout | `ref: v3.5.0`, with `fetch-depth: 0` so an annotated tag can be resolved through to its commit |
| Label | `release_label.py v3.5.0` returns `components=cpp`, `label=3.5.0` |
| Build | only `gen_docs.bash --label 3.5.0`. The Python step is skipped by `if:`, and no site shell is produced |
| Artifact | `docs/cpp/3.5.0/` plus `cpp/nv-versions.json` and `cpp/index.html` |
| Deploy | adds `cpp/3.5.0/`, replaces the two `cpp/` manifests, touches nothing else |

Note what is **not** in that artifact: no `python/` anything, and no
`objects.inv` at the component root. That inventory tracks the development docs,
so it is written only when the label is `unstable`:

```bash
if [[ "${VERSION}" == "unstable" && -f "${VERSIONED_HTML_DIR}/objects.inv" ]]; then
    cp "${VERSIONED_HTML_DIR}/objects.inv" "${HTML_DIR}/objects.inv"
fi
```

A release replaces the manifests (so the dropdown gains `3.5.0`) but must not
replace the convenience inventory, which would silently repoint every
intersphinx consumer from `main` to a release.

**Rehearsing.** The dispatch also takes `docs-branch` and `site-url`, so a
release can be published to a scratch branch on a fork and inspected before
anyone touches production.

---

## 12. One page in both books

Some content belongs to neither product and both: an explanation of iterators,
of memory resources, of how a concept maps across the two APIs. Duplicating it
means maintaining two copies that drift.

The two-project design allows one source file to be rendered into both, without
a shared build and without copying.

Write the page once under the C++ source root, and symlink it into the Python
source root:

```
docs/
├── howto/
│   └── howto1.md
└── python/
    └── howto/
        └── howto1.md -> ../../howto/howto1.md
```

The symlink is committed to git (mode `120000`); the repository already tracks
several. Both Sphinx projects now see a real file at a path inside their own
source root.

Then place it in each product's sidebar independently:

```rst
.. docs/cudax/index.rst
   /howto/howto1

.. docs/python/compute/index.rst
   /howto/howto1
```

The leading `/` means "from this project's source root", so the identical string
resolves correctly in both projects even though their roots differ. The page can
therefore sit under CUDA Experimental in the C++ docs and inside `cuda.compute`
in Python. Same source, different placement.

**Why this beats hosting the page once at the site root.** Each rendering
inherits the version of the build it appears in. The copy under `cpp/3.5.0/` is
that page as of C++ 3.5.0, and the copy under `python/1.2.0/` is that page as of
Python 1.2.0, automatically, because §5 stamps every page in a build with that
build's label. A page hosted once at the doc root would have to carry a single
version number, and would be wrong for whichever product did not match it.

The cost is that the same content is reachable at two URLs.

This is currently a working prototype rather than adopted practice: one
placeholder page, rendered into both products, verified live.

---

## 13. Things to keep in mind

**`unstable` is not the newest release.** It is `main`. It changes on every
merge and it documents code you may not be able to use yet.

**Versions accumulate forever.** Nothing retires automatically. A C++ release is
roughly 118 MB, the site is around 314 MB today, and GitHub Pages refuses a site
over 1 GB. That is room for about six more C++ releases before someone has to
make a decision. Python, at roughly 8 MB, is not a practical constraint.

**The two existing releases cannot be rebuilt by the workflow.** A release build
runs the build scripts found in the tag's own source, and `v3.4.2` and
`python-1.1.1` predate this system. `python-1.1.1` has no Python docs build at
all. Both were published once from one-off compatibility branches. Every tag
from now on republishes normally.

**Nothing automatically touches a published release.** Publishing is additive,
so no future deployment can alter or remove one. Correcting a bad release is a
deliberate act: move the tag and re-run, or tag a new patch. Removing one is a
manual `git rm` on `gh-pages`.

**The build is not byte-reproducible.** Rebuilding an identical source tree can
produce small differences in the C++ output. A rebuild during development
changed three HTML files and `objects.inv` by a few bytes, entirely in how
cross-references were written: one build emitted a same-page anchor, the other a
full path to the API page. Both resolved correctly, so nothing was broken, but
it means a republish is not guaranteed to be a no-op. The likely cause is
parallel-write ordering in Sphinx's C++ domain under `-j auto`; that has been
matched to the evidence rather than proven.

**Dependencies are only as pinned as you make them.** `docs/requirements.txt`
carried `breathe>=4.36.0` with no upper bound. Breathe 5.0.0 released on
2026-09-21 and broke the build the same day, and it broke it by *hanging*
rather than erroring: Sphinx hit an assertion mid-write and died, leaving its
`-j auto` workers orphaned, so the job ran until Actions killed it at the
six-hour limit. Three consecutive runs on `main` burned six hours each. The cap
is now `breathe>=4.36.0,<5`, to be lifted deliberately rather than by drift.

**To check a published site**, run:

```bash
python3 docs/smoke_site.py
```

It walks every route, follows each page's *declared* manifest URL rather than
the one it expects, and confirms stylesheets load. Following the declared URL is
the point: an earlier version checked the manifest at the path it assumed, and
passed cleanly against a site whose dropdown was completely dead.

---

## 14. The file map

| Path | What it is |
| --- | --- |
| `.github/workflows/docs-deploy.yml` | The two entry points: push and dispatch |
| `.github/workflows/build-docs.yml` | The reusable workflow both call |
| `docs/gen_all_docs.bash` | Development build: both products plus the site shell |
| `docs/gen_docs.bash` | The C++ build |
| `docs/gen_python_docs.bash` | The Python build |
| `docs/release_label.py` | Tag to (component, version) |
| `docs/check_manifests.py` | Manifest membership, agreement, and rehearsal retargeting |
| `docs/conf.py` | C++ Sphinx config |
| `docs/python/conf.py` | Python Sphinx config |
| `docs/cpp_site/`, `docs/python_site/` | Checked-in manifests and component landing redirects |
| `docs/index.html` | The site chooser |
| `docs/smoke_site.py` | Checks a published site |
| `docs/test_docs_build.py` | 53 tests over the publication logic |

**Where to go next.** `PUBLISHING.md` for the release procedure.
`publishing-design.md` for the full reference, including the clause-by-clause
comparison with cuda-python and the complete failure catalogue.
