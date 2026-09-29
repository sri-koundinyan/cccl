# Splitting the CCCL docs — deck and script

12 slides plus 4 backups. About 26 minutes. Audience: CCCL maintainers who know
the old documentation setup well, asked for the C++/Python split, and left the
approach to us.

The spine is a diagnosis followed by five numbered changes. The audience already
has a working mental model of the old system, so every slide updates that model
rather than building a new one: *this is what you had, this is what it is now,
this is why.*

Slide bodies are sparse. The argument is in the script.

---

## 1 — What you asked for, and what we built · 2 min

**The ask:** C++ and Python release on their own cadences. Split the docs so
they can be versioned independently.

```
/cccl/                    a chooser: C++ or Python
/cccl/cpp/unstable/       C++, built from main
/cccl/cpp/3.4.2/          C++ release
/cccl/python/unstable/    Python, built from main
/cccl/python/1.1.1/       Python release
```

**Unchanged:** Sphinx · the NVIDIA theme · Doxygen 1.9.6 · Breathe ·
`auto_api_generator` · `gh-pages` · Pages serving from `/docs` ·
**your pages and your navigation**

**Changed:** five things. The rest of this talk.

**Script**

You asked us to split the docs so C++ and Python could be versioned
independently, and you left the approach to us. So: here's the approach, and
why.

Top of the slide is what you get. A chooser at the root, then each product in
its own namespace with its own version list and its own dropdown. `unstable` is
built from `main`, and each release gets a directory named for its exact
version.

But the more useful block is the second one, because I want to set expectations
about how invasive this is. It isn't. Same Sphinx. Same theme. Same Doxygen,
same Breathe, same API generator. Still deploying to `gh-pages`, still served
out of `/docs`.

Your content is untouched. Every page is where it was — nothing moved, nothing
renamed, nothing reorganised, no sections shuffled.

The navigation is untouched too, with exactly one exception: the C++ table of
contents no longer lists the Python docs. That's one line, and it *is* the split
— it's how Python stops being part of the C++ book. There's no other structural
edit anywhere.

A handful of pages did change, and they're all consequences rather than
decisions: a few cross-references from Python into C++ that I'll come back to on
the next-but-one slide, and a prototype I'll show you at the end.

Five things changed and I'll take them one at a time. But first I want to show
you *why* those five — because the old setup was much closer to working than it
looks, and seeing exactly where it fell short makes the rest of this obvious.

---

## 2 — The old setup already had all the parts · 3 min

Version directories, a manifest, a switcher, and a release publication path —
all present, all wired up correctly.

Two things independently prevented a second version from existing.

**1. Every deploy replaced the site.** `force_orphan: true` rebuilds the branch
from the artifact each time. Pages deleted from the source in July are 404 on
production today:

```
/unstable/cub/index.html    200   │   /unstable/cub/api.html        404   deleted 2026-07-21
/unstable/thrust/index.html 200   │   /unstable/thrust/api.html     404   deleted 2026-07-21
/unstable/cccl/index.html   200   │   /unstable/python/coop.html    404   deleted 2026-07-24
```

**2. Every build regenerated the manifest**, with one entry — the version it had
just built:

```bash
cat > "${HTML_DIR}/nv-versions.json" <<EOF
[ { "version": "${VERSION}", "url": "${BASE_URL}${VERSION}/", ... } ]
EOF
```

Production: one directory · one manifest entry · one commit ·
**0 of the last 200 publications were release dispatches**

**Script**

Here's the thing I found most interesting while working on this.

The old setup wasn't missing the machinery. It had version directories — `main`
published to `unstable`, and you could dispatch from a release branch and get a
directory named after it. It had a manifest file. It had the switcher wired up
in the theme, correctly: the URL each page fetched the version list from was
exactly where the build wrote it, and the version each page claimed to be was
exactly the directory it landed in. If you'd reviewed that code on its own you'd
have approved it.

All the parts were there. They couldn't add up, for two separate reasons, and
the first one is the one that surprised me.

Every deploy replaced the whole site. The action ran with `force_orphan`, which
rebuilds the branch from scratch out of whatever the artifact contains. So the
site is never what you've published over time — it's only ever what the last
build produced.

That's the middle block, and it's a real test rather than a reading of the
config. `cub/api.rst` and `thrust/api.rst` were deleted from the source in July.
`python/coop.rst` a few days later. Production has redeployed hundreds of times
since. If anything survived a deploy, those pages would still be sitting there.
All three are 404 today, while their neighbours that still exist in the source
are 200.

Now follow that through for a release. You publish 3.4.8, and the next person
who merges a PR to `main` triggers a build whose artifact contains `unstable`
and nothing else — and `/cccl/3.4.8/` is gone. Not delisted. Deleted.

That alone makes release documentation impossible. But there's a second,
independent reason, which is the manifest. Every build wrote `nv-versions.json`
from scratch with exactly one entry: whatever had just been built. So even
inside the window where two directories existed, the dropdown could only ever
name one of them.

And then the bottom line. One directory on the branch, one entry in the
manifest, one commit, and of the last two hundred publications, zero were
release dispatches. The release path was never used. Not once.

Which, given everything I just described, is completely rational. The feature
existed and could not work, so nobody used it.

I want to be clear none of this is a criticism of whoever built it. The manifest
is the *only* file in that system that has to know about versions other than the
one being built, and a single build cannot know that. It's a genuine design
problem, solved the natural way — generate it — which happens to be the one way
that can't work. The deploy setting is a two-line YAML choice whose consequence
only shows up if you ever publish a second thing, and nobody ever did.

So, five changes. The first two make a version an explicit thing rather than an
accident. The third fixes the manifest. The last two make publishing
predictable.

---

## 3 — Change 1 of 5: two builds, not one · 2 min

```
BEFORE   one Sphinx project, rooted at docs/
         docs/python/ swept in, published at /cccl/unstable/python/

NOW      C++      source root docs/          config docs/conf.py
         Python   source root docs/python/   config docs/python_conf/  (via -c)
```

The enabling line, in `docs/conf.py`:

```python
exclude_patterns = ["python", ...]
```

**A version number is a property of a build.** One build writes one directory,
and a directory carries one version.

**The cost:** a Sphinx cross-reference can't cross a project boundary.

```rst
BEFORE   :ref:`C++ CUDASTF documentation <stf>`
NOW      `C++ CUDASTF documentation <https://…/cccl/cpp/unstable/cudax/stf.html>`_
```

3 pages, 4 links, all Python → C++. None in the other direction.

**Script**

Change one. There are now two Sphinx projects where there was one.

This is the structural reason the old setup couldn't do what you asked, and it's
one sentence: a version number is a property of a build. One build writes one
output directory, and that directory carries exactly one version. So if you want
two products versioned independently, you need two builds. There's no way
around it.

Before, there was one project rooted at `docs/`, and since `docs/python/` sits
inside `docs/`, Sphinx simply walked into it and published the Python pages at
`/cccl/unstable/python/`. That's why they were nested — nobody decided it, it's
just what Sphinx does by default.

Now `docs/conf.py` has one line telling the C++ build to skip that directory,
and a second Sphinx project claims it as its own source root.

Two details worth thirty seconds. The Python config lives outside its own source
root and gets passed in with `-c`. That's what let us build documentation for
tags cut before any of this existed — today's configuration, yesterday's
sources.

And because "Python pages published under a C++ version" is precisely the
failure we just removed, there are two independent checks that it hasn't come
back: one in the build script, one in the workflow.

Now the cost, because there is one and it's the one Georgii spotted.

Sphinx cross-references are resolved within a project. `:ref:` and `:doc:` look
up a target in the same build. Once these are two builds, a Python page can no
longer say `:ref:` and reach a C++ page — there's nothing to resolve against.

So those links became absolute URLs. It's three pages and four links, all of
them Python pointing at C++, none in the other direction — I checked every
version of both trees. The cost is that an absolute URL names a version, so
those four now point at `unstable` and won't follow a reader who's on a release.

There's a proper fix for this and it's called intersphinx — you publish an
inventory, the other project consumes it, and links resolve by symbol name. Both
products already publish that inventory. We haven't wired up the consuming side,
deliberately, because it means one build depending on the other's published
output and I didn't want that in the first version. Four links didn't justify
it. If it becomes forty, it will.

Two builds, two directories. So how does a directory know which version it is?

---

## 4 — Change 2 of 5: the version becomes a destination · 3 min

```
BEFORE   SPHINX_CCCL_VER   any string, whatever the workflow put there
         html_baseurl      https://nvidia.github.io/cccl/    ← no version in it
         version_match     whatever release happened to be

NOW      SPHINX_CCCL_VER   ^(unstable|[0-9]+\.[0-9]+\.[0-9]+)$    validated
         html_baseurl      <component root>/<version>/
         version_match     the same value
```

### Still one variable. It now has to be a legal place.

```
SPHINX_CCCL_VER = 3.5.0
     │
     ├── gen_docs.bash   creates   docs/cpp/3.5.0/        ← bash makes the directory
     └── conf.py         html_baseurl  = …/cpp/3.5.0/     ← Sphinx writes the canonical
                         version_match = 3.5.0            ← Sphinx writes the stamp
```

Rejected before the build starts:

| | | |
| --- | --- | --- |
| `3.4` | a rolling directory | content would change under a bookmark |
| `3.5.0-rc0` | a pre-release | unreleased docs at a released version's URL |
| `3.6` | `VERSION.md`'s value | not a release; two components, not three |

**Script**

Change two, and this is the one to remember.

Still one variable. `SPHINX_CCCL_VER` is the same variable you already know, and
it still means the version. What changed is that it's now also the *place*, and
a place has rules.

That's the whole idea. Before, it was a free string that the workflow happened to
set to a directory name. Now it's validated before the build starts: it's
`unstable`, or it's exactly three numbers. Nothing else.

Look at what's rejected, because each row is a URL we've decided not to create.

`3.4` is a rolling directory. Publish there and the content behind that URL
changes every patch release, which breaks the one thing a documentation link is
supposed to do.

`3.5.0-rc0` is a release candidate. That's a perfectly accurate description of
the software, and it's still refused, because publishing it puts unreleased
documentation one URL away from a released version.

And `3.6` is the value sitting in `VERSION.md` right now — what `main` is. Also
refused, because `main` isn't a release. It publishes to `unstable`.

Now the middle block. That one value goes three places. Bash creates the
directory — and since the artifact is laid out exactly like the site, that
directory *is* the URL. Sphinx writes the canonical link, which has to include
the version or every release claims to be the authoritative one. And Sphinx
writes the stamp the dropdown matches on.

Two programs, three places, so the build confirms the value actually arrived —
it greps a page it just wrote for the stamp and stops if it isn't there. Three
lines of bash. It's the first row of the guards table later, and I'll leave it
until then.

That stamp is what the dropdown matches against. And the dropdown reads the
manifest — which brings us back to the thing that was actually broken.

---

## 5 — Change 3 of 5: the manifest becomes checked-in data · 2½ min

```
BEFORE   generated by every build · one entry · at the site root
NOW      checked in · one per product · lists every version
```

**One file per product:**

```
docs/cpp_site/nv-versions.json      →  /cccl/cpp/nv-versions.json
docs/python_site/nv-versions.json   →  /cccl/python/nv-versions.json
```

Edited in the release-prep commit, reviewed like any other change.

One guard: the version being published **must** be listed, or the docs deploy
and no reader can reach them.

**Script**

Change three, and this is the direct fix for slide two.

The manifest isn't generated any more. It's checked in, and it lists every
version of that product. You edit it during release prep and it gets reviewed
like anything else.

One file per product: `nv-versions.json`, which is what the theme fetches to
draw the dropdown. cuda-python ships a second one beside it called
`versions.json` and we deliberately don't, because nothing reads it — I'll come
back to that.

That sounds almost too simple, so let me say why it's the right answer and not
just a different one.

The manifest is the only file in the system that has to know about versions
other than the one being built. A build can't know that — it has one source tree
and one version. So there are three options. Generate it from the build, which
is what we had, and you get one entry. Scan the published site and regenerate,
which makes your version list whatever happens to be lying around on a branch,
and means any half-failed deploy silently rewrites your version history. Or
check it in, and make it something a person decided and a person reviewed.

We went with the third. The version list is release metadata. It should live
with the release, in the commit, in the diff.

One guard on it. The build refuses to publish a version that isn't listed,
because if it isn't there nothing links to it and you've published documentation
that renders perfectly and no reader can reach.

Now the second file, since you'll see it in cuda-python and wonder why we don't
have it. `versions.json` is the same list in a different shape, and nothing
fetches it — not the theme, not the switcher, nothing in either codebase. We
dropped it. The evidence that it's dead weight is on cuda-python's own site:
their `versions.json` stopped at 0.3.2 while their `nv-versions.json` reached
1.2.0, and nobody noticed for nine minor versions, because nothing was reading
it. Carrying it would have meant a file to maintain, a copy step, and a guard
whose whole job was keeping a dead file in sync with a live one.

One detail if you read the config later: the manifest sits at the *component*
root, not inside a version directory. It lists every version, so it can't live
inside one of them.

That's the reader-facing half fixed. Now the publishing half.

---

## 6 — Change 4 of 5: publishing is tag-driven · 2 min

```
BEFORE   push to main                        →  unstable/       the only path ever run
         dispatch from a release branch      →  named for the branch   ┐  specified,
         dispatch + destination_override     →  any directory typed    ┘  never used

NOW      push to main                        →  both unstable/ trees
         dispatch + an exact tag             →  that product, that version
```

Both paths call **one reusable workflow**, so they cannot drift apart.

**The tag is the only router.** No directory field, no product dropdown.

**Script**

Change four. How a publication gets aimed.

I want to be accurate about the before column, because two of those three lines
are things the workflow *offered* and nobody ever did. Every publication that has
ever happened is the first line: push to `main`, get `unstable`. Zero dispatches,
as we saw earlier.

So this isn't me telling you we removed a hazard you were exposed to. The release
path was specified and never worked, and the point of this slide is that there's
now one that does.

Still, the shape of what was offered is worth thirty seconds, because it's the
design contrast. `destination_override` was a free-text box whose value became
the directory your documentation overwrote, with nothing validating it. If
someone had used it, a typo would have published a build somewhere nobody
expected, and a plausible-looking value would have landed C++ docs on top of
something else.

Now there are two paths and neither takes a destination. Push to `main` and both
products rebuild into their `unstable` trees. Or dispatch with a tag, and the
tag decides everything — `v3.5.0` can only become `/cccl/cpp/3.5.0/`, and
`python-1.2.0` can only become `/cccl/python/1.2.0/`. There's no field where a
human can put a wrong value, because the value is computed.

That's the general principle, and it's most of why this is safer than what it
replaces: wherever someone could type something wrong, the system derives it
instead.

One more thing about the development path. Both products build from the same
commit, deliberately. One push advances both, so if we built them separately
their `unstable` trees could end up describing different states of the repo.
Only releases are genuinely independent.

And both paths go through the same reusable workflow underneath, so the release
path can't quietly drift away from the one we exercise on every merge.

---

## 7 — Change 5 of 5: deployment adds, never removes · 2½ min

```
BEFORE   peaceiris/actions-gh-pages    force_orphan: true
                                       the site = the last build's artifact, nothing else

NOW      JamesIves/…-deploy-action     clean: false
                                       the site = everything ever published
```

Same branch, same `/docs` path, same Pages config. A reader cannot tell.

**What `clean: false` buys** — this is the change that makes versioning possible
- Publishing 3.5.0 leaves 3.4.2 alone. Versions coexist.
- A Python release cannot touch a C++ path — those files aren't in the artifact.
- Ordinary commits on `gh-pages`, so a bad deploy can be reverted.

**What it costs — and this is new**
- A page dropped from a build is no longer dropped from the site.
- Before, renaming `foo.md` removed `foo.html`. Now it lingers.

**Script**

Change five, the last one. Two lines of YAML, and it's the change that makes all
the others possible.

Same branch, same `/docs` path, same Pages settings — a reader can't tell the
difference. What's different is the model.

Before, the site was defined as "whatever the last build produced." That's slide
two: `force_orphan` rebuilds the branch from the artifact every time, so
anything not in that artifact ceases to exist.

Now the site is defined as "everything we've ever published." `clean: false`
only writes the paths the artifact contains. It's a copy, not a sync — it never
compares, so it can never decide something's missing and delete it.

That's what lets two versions exist at the same time, which is the thing you
asked for. It also means a Python release physically cannot touch a C++ path,
not because we told it not to, but because those files aren't in the artifact.
And because we're not recreating the branch, `gh-pages` now keeps ordinary
commits — you can see what shipped when, and you can revert one bad deploy.

Now the cost, and I want to be straight about this because it's a genuine
regression and you'll notice it.

Under the old setup, if you renamed `foo.md` to `foo2.md`, `foo.html` disappeared
from the site at the next deploy. It got wiped along with everything else.
Under this one it doesn't. The sidebars, the search index and the inventory all
rebuild without it, but the old HTML file stays.

So: we traded "the site is always exactly the current build" for "the site
accumulates." You can't have versions without the second one, but the first one
had a real property that we've given up.

Four things that make it liveable. It isn't link rot — an old bookmark keeps
working, which is usually what you want. It's invisible to anyone navigating or
searching, because nothing links to it. It only happens where we write into a
directory that already has files, which in practice is the two `unstable` trees;
release directories get written once and never touched again. And cleanup is a
deliberate `git rm` on `gh-pages`. We didn't automate that on purpose — an
automatic remover is a script whose failure mode is deleting published
documentation.

That's all five changes. Let me show you what it looks like to actually use.

---

## 8 — Putting it together: releasing C++ 3.5.0 · 2 min

**1. In the release-prep commit, add the version to that product's manifest**

```json
docs/cpp_site/nv-versions.json
  { "version": "3.5.0", "url": "https://nvidia.github.io/cccl/cpp/3.5.0/" }
```

**2. Tag** `v3.5.0`

**3. Actions → Deploy CCCL Documentation → Run workflow →** give it the tag

Skip step 1 and the build **stops and names the file to edit.**

```
BEFORE   there was no procedure — no release documentation was ever published
```

**Script**

This is the one you'll actually have to remember, so let me go slowly.

Step one, and it's the new one: before you tag, add the version to that
product's manifest. One entry, one file. It goes in the release-prep commit and
gets reviewed.

Step two, tag it. Step three, run the workflow and hand it the tag. Done — the
tag decides both which product and which directory.

Forget step one and the build stops and tells you which file to edit. It won't
publish documentation that nothing links to.

There's no before to compare this against, which is the point. No release
documentation has ever been published, so this is the first procedure that
exists rather than a replacement for one. Had anyone tried the old path, the
build would have written a manifest naming only that version and the next merge
to `main` would have deleted the directory — so "there was no procedure" is the
accurate way to say it, not a slight.

One extra thing worth knowing: you can rehearse the whole release. The dispatch
takes an optional branch and site URL, so you can publish to a scratch branch on
your own fork and click around before anything touches production. That's how
everything in this talk was tested.

---

## 9 — The guards, and watching them fire · 2½ min

### Every one of these fails by looking completely fine.

| Check | Without it... |
| --- | --- |
| Stamp matches the directory | dropdown never highlights the current page |
| Version listed in the manifest | publish docs nothing links to |
| Label is `unstable` or `X.Y.Z` | a rolling `3.4` whose content changes under a bookmark |
| Tag matches the exact grammar | `v3.5.0-rc0` published as `3.5.0` |
| No `python/` inside a C++ artifact | Python pages under a C++ version |
| `index.html` + `objects.inv` exist | deploy an empty build |
| `.nojekyll` present | every page 200s, no CSS, no dropdown |

**Exercised in real CI:** both publication paths · pre-release tag **rejected** ·
missing manifest entry **rejected** — both stopped with `Deploy documentation`
skipped · release trees byte-identical across every deploy · 53 tests

**Script**

I'm not going to read the table. What matters is the heading, and it's the one
idea I'd like you to leave with about this whole system.

Every row is a way this site breaks while looking completely fine. Not one of
these produces an error page, a 500, or a broken link. The documentation renders,
the URLs resolve, the search works — and something is wrong that nobody will
report, because nobody is quite sure what correct looks like.

That's why there are eight checks rather than three. It isn't belt and braces.
It's that this particular system has almost no failure modes you'd notice.

Let me do one, because it's my favourite. Bottom row. GitHub Pages runs Jekyll
unless you drop an empty file called `.nojekyll` at the root, and Jekyll ignores
any directory whose name starts with an underscore. Sphinx puts every
stylesheet, every script, and the version switcher in `_static`.

So without that one empty file: every URL resolves, every page has all its text,
and the whole site is unstyled with no navigation. Nothing fails. Nothing 404s.
It just looks like someone turned CSS off.

All of these run before the deploy step, so a failure means nothing got
published.

Then the bottom line, which is the part I'd actually like you to weigh. Guards
you've never seen fail aren't guards. So I fed it a pre-release tag and watched
the run stop with the deploy step skipped. I pulled a version out of a manifest
and watched the same thing. Both publication paths have been run end to end, for
both products.

The one I'd point at specifically is "byte-identical." Those release directories
have been through every deploy since they were published and their tree hashes
haven't moved. That's the concrete evidence for what I claimed two slides ago —
additive deployment really does leave existing releases alone, and it's
checkable by hash rather than by squinting at the site.

---

## 10 — Things to keep in mind · 2 min

**`unstable` is `main`, not the newest release.** Renamed from `latest`, because
"latest" reads as "the current release" and means the opposite.

**The old URLs are gone,** not redirected. `/cccl/unstable/` and
`/cccl/unstable/python/` stop resolving.

**Versions accumulate forever.** ~118 MB per C++ release, 314 MB today,
GitHub Pages refuses over 1 GB. Room for roughly six more.

**The two existing releases can't be rebuilt** by the workflow — they predate it.

**The build is not byte-reproducible.** Identical sources can produce small
differences in C++ cross-reference output.

**Script**

Five things that are true, and a couple are uncomfortable.

Naming. `unstable` means `main`. It is not the newest release. We moved away
from `latest` deliberately, because `latest` reads as "the current release," and
anyone who believes that gets confidently wrong answers about code they can't
use yet.

Second one needs your agreement, so I'll flag it hardest. The old URLs go away.
We're not redirecting `/cccl/unstable/` — it stops resolving. That's a
deliberate call: keeping two URL schemes alive means maintaining both forever,
and the old one was only ever `main`, so nobody's citing it in a paper. But it
is a call, and if you'd rather redirect, that's a conversation we should have
now rather than after it ships.

Capacity. Nothing retires automatically. A C++ release is about 118 meg, the
site's at 314 today, and Pages refuses anything over a gig. Room for roughly six
more C++ releases — call it a year. We don't need a policy today, but somebody
will need one before we hit the ceiling, and I'd rather that was a decision than
an emergency.

The two releases already published can't be rebuilt by the workflow, because a
release build runs the build scripts from that tag's own source and both of
these predate all of this. They were published once from one-off branches.
Everything tagged from now on republishes normally.

And last, something I found a couple of weeks ago: the build isn't
byte-reproducible. Rebuilding identical sources changed three HTML files by a
few bytes — entirely in how cross-references got written, one build emitting a
same-page anchor and the other a full path. Both worked. Nothing broke. But
republishing isn't guaranteed to be a no-op, and you should hear that from me
rather than find it in a diff.

---

## 11 — Shared pages — a prototype, not a proposal · 1½ min

One source file, rendered into both products:

```
docs/howto/howto1.md
docs/python/howto/howto1.md  →  ../../howto/howto1.md      (committed symlink)
```

Placed independently in each sidebar — CUDA Experimental in C++, `cuda.compute`
in Python.

**Each copy inherits the version of the build it is in.**

**Script**

One thing I want to show you that wasn't part of the ask.

Georgii raised it: if we've got a page that's genuinely language-agnostic, do we
now have to write it twice, given there are two builds?

Turns out no, and it's cheap. You write the page once under the C++ tree and
symlink it into the Python tree. Both Sphinx projects see a real file inside
their own source root, so both render it. One file, two renderings, nothing
copied. It's live on the fork — you can go and look at it.

And because a toctree entry names a document rather than a location, each
product puts it wherever it belongs. Right now that page sits under CUDA
Experimental in the C++ docs and inside `cuda.compute` in Python.

The part I like is that versioning just works. The copy under C++ 3.5.0 is that
page as of 3.5.0, and under Python 1.2.0 it's as of 1.2.0 — automatically,
because every page in a build gets stamped with that build's label. If you
hosted it once at the doc root instead, you'd have to pick a single version
number for it, and it'd be wrong for whichever product didn't match.

The cost is the same content at two URLs.

I'm not asking you to adopt it. I'm showing you it's available.

---

## 12 — What I need from you · 1½ min

**Decide**

- Merge as-is, or with changes?
- Old URLs: remove, as built — or redirect?
- Shared pages: adopt, or leave the prototype on the branch?
- Who owns the manifest edit in the release checklist?

**Not built yet**

- `timeout-minutes` on the build step
- Link checking · PR doc previews · a first-class dry-run mode

**Script**

Four things I'd like decided.

Does this merge as-is, or are there changes you want first. Do we remove the old
URLs the way it's built, or would you rather redirect them. Do we adopt the
shared-page thing or leave it on the branch. And who owns the manifest edit in
the release checklist — that's the step most likely to get forgotten, and I'd
rather it had a name on it than a hope.

Then a short list of what I haven't built.

The first one is small and I'd like it soon. There's no timeout on the docs build
step. We found that out when Breathe 5.0.0 shipped and broke the build by
*hanging* rather than erroring — three runs on `main` burned six hours each
before Actions killed them. A timeout makes that a ten-minute failure instead of
an afternoon.

The rest are nice to have and none of them block anything.

Questions?

---

# Backup slides

---

## B1 — The old system and the new one, side by side

```
                        BEFORE                          NOW
Sphinx projects         1, rooted at docs/              2
Python docs             /cccl/unstable/python/          /cccl/python/<version>/
Version input           SPHINX_CCCL_VER, unvalidated    SPHINX_CCCL_VER, validated
Stamp checked           no                              yes
Manifest                generated, 1 entry, site root   checked in, per product, all versions
versions.json           shipped, unread                 dropped
Release trigger         dispatch from a release branch  dispatch with an exact tag
Releases ever shipped   none (0 dispatch runs)          2, plus every future tag
Destination             free-text override              derived from the tag
Deploy action           peaceiris, force_orphan         JamesIves, clean: false
Deploy semantics        replaces the whole site         adds and replaces paths
gh-pages history        1 commit, rewritten each time   ordinary commits
Removed pages           vanish at the next deploy       linger until a manual git rm
Site root               redirect + 404.html             a chooser, no 404 handler
Workflow                one job                         reusable workflow, two entry points
Tests                   none                            53
```

**Script**

The complete before-and-after, if anyone wants to check a specific claim.

Three rows people ask about. `404.html` is gone because the site root is now a
chooser rather than a redirect, and there's nothing sensible to say to someone
who lands on a URL naming no product.

"Replaces the whole site" is measured, not inferred — pages whose sources were
deleted in July return 404 on production today, while their surviving
neighbours return 200. That's what `force_orphan` does, and it's why no release
could ever have survived the next merge to `main`.

And the "removed pages" row is the one genuine regression in the whole change.
We gave up "the site is always exactly the current build" to get versions. It's
the same setting doing both.

---

## B2 — Where this departs from cuda-python

**Followed exactly:** reusable workflow shape, component namespaces, the same
deploy action at the same pinned commit, `clean: false`.

| | cuda-python | CCCL |
| --- | --- | --- |
| Development directory | `latest/` | `unstable/` |
| Version stamp | source version (`1.2.1.dev72`) | the publication label |
| Second manifest (`versions.json`) | shipped, unread, drifted in production | dropped |
| Old URL scheme | preserved | removed outright |

**Script**

We follow their workflow shape and namespace layout, and pin the same deploy
action at the same commit. Four deviations; the second row is the substantive
one, and it's the reason the stamp check exists.

---

## B3 — What actually produces the HTML

```
headers  --Doxygen-->  XML  --auto_api_generator-->  .rst stubs
                                                           |
                                              Sphinx + Breathe
                                                           v
                                              1,694 pages, 180 MB
```

1,225 of those pages are generated at build time and gitignored. Python is
different: `autodoc` imports the package. 14 pages, 7.7 MB.

**Script**

Unchanged — none of this was touched. The only number that matters elsewhere is
180 meg per C++ build, which is the capacity constraint on slide ten.

---

## B4 — File map

| Path | What it is |
| --- | --- |
| `.github/workflows/docs-deploy.yml` | the two entry points |
| `.github/workflows/build-docs.yml` | the reusable workflow both call |
| `docs/gen_all_docs.bash` | development build: both products plus the shell |
| `docs/gen_docs.bash` / `gen_python_docs.bash` | the two component builds |
| `docs/release_label.py` | tag → (component, version) |
| `docs/check_manifests.py` | membership, agreement, rehearsal retargeting |
| `docs/cpp_site/`, `docs/python_site/` | checked-in manifests and landing redirects |
| `docs/smoke_site.py` | checks a published site |
| `docs/test_docs_build.py` | 53 tests |

Full reference: `docs/publishing-design.md`. Tutorial: `docs/publishing-tutorial.md`.
