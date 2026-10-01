"""Tests for documentation publication.

Focused deliberately. This design leans on cuda-python's build-and-deploy model
rather than a CCCL publication system, so there is no publisher, provenance or
Pages-state machinery to test. What remains is worth testing because each
failure is silent -- the site builds, deploys and renders while being wrong:

* a tag routed to the wrong component or version;
* pages stamped with a label the switcher manifest does not contain, so the
  version picker never highlights the page you are on;
* a component artifact carrying the other component's documentation.

Run directly, or through the pre-commit hook:

    pytest docs/test_docs_build.py
"""

import json
import pathlib
import subprocess

import make_manifest
import pytest
import release_label
import yaml

DOCS = pathlib.Path(__file__).resolve().parent
REPO = DOCS.parent
BUILD_WORKFLOW = REPO / ".github/workflows/build-docs.yml"
DEPLOY_WORKFLOW = REPO / ".github/workflows/docs-deploy.yml"

# Note on naming: keep test function names off exactly 40 characters. Lob API
# test keys are literally "test_" followed by 35 characters, so the repository's
# secret scanner flags any 40-character test_* identifier as a credential.


# --------------------------------------------------------------------------
# Tag -> component and version
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tag,expected",
    [
        ("v3.4.2", ("cpp", "3.4.2")),
        ("v3.10.0", ("cpp", "3.10.0")),
        ("v4.0.0", ("cpp", "4.0.0")),
        ("python-1.1.1", ("python", "1.1.1")),
        ("python-1.2.0", ("python", "1.2.0")),
    ],
)
def test_tag_names_component_and_version(tag, expected):
    assert release_label.resolve(tag) == expected


@pytest.mark.parametrize(
    "tag",
    [
        "v3.5.0-rc0",  # a pre-release must not take the release's URL
        "v3.6.0.dev",
        "v3.4",  # no rolling MAJOR.MINOR directory exists
        "python-1.1",
        "3.4.2",  # unprefixed: which component?
        "refs/tags/v3.4.2",
        "unstable",
        "main",
        "",
    ],
)
def test_non_release_tags_rejected(tag):
    with pytest.raises(SystemExit):
        release_label.resolve(tag)


def test_component_cannot_be_crossed():
    """A Python tag can never resolve into the C++ namespace, or vice versa."""
    assert release_label.resolve("python-1.1.1")[0] == "python"
    assert release_label.resolve("v1.1.1")[0] == "cpp"


def test_tag_output_cannot_forge_a_key(tmp_path, monkeypatch):
    """Workflow outputs are key=value lines; a newline would add a second key."""
    with pytest.raises(SystemExit):
        release_label.resolve("v3.4.2\nlabel=9.9.9")


# --------------------------------------------------------------------------
# Artifact layout
# --------------------------------------------------------------------------


def make_component(root, component, label, manifest_versions):
    """A stand-in for one component's built artifact."""
    comp = root / component
    version = comp / label
    version.mkdir(parents=True, exist_ok=True)
    (version / "index.html").write_text(
        f"<html><script>version_match = '{label}';</script></html>", encoding="utf-8"
    )
    (version / "objects.inv").write_text("inv", encoding="utf-8")
    (comp / "nv-versions.json").write_text(
        json.dumps(
            [
                {"version": v, "url": f"https://x/{component}/{v}/"}
                for v in manifest_versions
            ]
        ),
        encoding="utf-8",
    )
    (comp / "index.html").write_text("<html>redirect</html>", encoding="utf-8")
    return comp


def stamp_of(page):
    import re

    m = re.search(r"version_match = '([^']*)'", page.read_text(encoding="utf-8"))
    return m.group(1) if m else None


def manifest_versions(component_root):
    data = json.loads((component_root / "nv-versions.json").read_text(encoding="utf-8"))
    return [e["version"] for e in data]


def test_published_label_is_listed_in_the_manifest(tmp_path):
    """The reader reaches a version through the switcher; if the manifest does
    not list it, the documentation exists but cannot be found."""
    comp = make_component(tmp_path, "cpp", "3.4.2", ["unstable", "3.4.2"])
    assert stamp_of(comp / "3.4.2" / "index.html") in manifest_versions(comp)


def test_stamp_missing_from_manifest_is_detectable(tmp_path):
    """The failure the build guard exists to catch."""
    comp = make_component(tmp_path, "cpp", "3.4.3", ["unstable", "3.4.2"])
    assert stamp_of(comp / "3.4.3" / "index.html") not in manifest_versions(comp)


def test_stamp_equals_the_served_directory(tmp_path):
    """cuda-python stamps unstable/ with the source version, so its switcher can
    never highlight the current page. Ours must match the directory."""
    for label in ("unstable", "3.4.2"):
        comp = make_component(tmp_path / label, "cpp", label, ["unstable", "3.4.2"])
        assert stamp_of(comp / label / "index.html") == label


def test_component_artifacts_stay_separate(tmp_path):
    """A release artifact must contain only its own component."""
    root = tmp_path / "artifacts"
    make_component(root, "cpp", "3.4.2", ["unstable", "3.4.2"])
    assert (root / "cpp").is_dir()
    assert not (root / "python").exists()


def test_manifests_list_only_their_own_component(tmp_path):
    root = tmp_path / "artifacts"
    cpp = make_component(root, "cpp", "unstable", ["unstable", "3.4.2"])
    py = make_component(root, "python", "unstable", ["unstable", "1.1.1"])
    assert manifest_versions(cpp) == ["unstable", "3.4.2"]
    assert manifest_versions(py) == ["unstable", "1.1.1"]
    assert not set(manifest_versions(cpp)) & {"1.1.1"}


# -- the generated manifest ---------------------------------------------------
#
# The manifest is derived from the documentation branch rather than maintained
# by hand, so the tests that matter are about what the derivation can and cannot
# produce: it cannot omit a published version, and it cannot invent one.


def pages_repo(tmp_path, tree, name="repo"):
    """A git repository whose gh-pages branch is shaped like the real one."""
    repo = tmp_path / name
    repo.mkdir()

    def run(*args):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

    run("init", "-q", "-b", "gh-pages")
    run("config", "user.email", "test@example.invalid")
    run("config", "user.name", "test")
    for component, versions in tree.items():
        root = repo / "docs" / component
        root.mkdir(parents=True, exist_ok=True)
        for version in versions:
            (root / version).mkdir()
            (root / version / "index.html").write_text("page", encoding="utf-8")
        # Files beside the version directories, which must not be mistaken for
        # versions: this is the whole reason the listing asks git for trees.
        (root / "objects.inv").write_text("inv", encoding="utf-8")
        (root / "index.html").write_text("redirect", encoding="utf-8")
    run("add", "-A")
    run("commit", "-qm", "pages")
    return repo


def test_listing_sees_versions_and_only_versions(tmp_path):
    repo = pages_repo(tmp_path, {"cpp": ["unstable", "3.4.2", "scratch"]})
    found = make_manifest.published_versions("cpp", "gh-pages", repo)
    assert sorted(found) == ["3.4.2", "unstable"]
    assert "scratch" not in found


def test_published_versions_survive_a_new_release(tmp_path):
    """The failure a hand-edited manifest allowed: 3.4.2 still has a directory,
    so no edit and no mistake can drop it out of the switcher."""
    repo = pages_repo(tmp_path, {"cpp": ["unstable", "3.4.2"]})
    out = tmp_path / "artifact"
    out.mkdir()

    listed = make_manifest.write(
        out, "cpp", "3.5.0", "https://x/cccl", "gh-pages", repo
    )

    assert listed == ["unstable", "3.5.0", "3.4.2"]
    entries = json.loads((out / "nv-versions.json").read_text(encoding="utf-8"))
    assert [e["version"] for e in entries] == listed
    assert [e["url"] for e in entries] == [
        "https://x/cccl/cpp/unstable/",
        "https://x/cccl/cpp/3.5.0/",
        "https://x/cccl/cpp/3.4.2/",
    ]


def test_the_version_being_published_is_always_listed(tmp_path):
    """It cannot be forgotten, because nobody adds it."""
    repo = pages_repo(tmp_path, {"cpp": ["unstable"]})
    out = tmp_path / "artifact"
    out.mkdir()
    assert "3.5.0" in make_manifest.write(
        out, "cpp", "3.5.0", "https://x/cccl", "gh-pages", repo
    )


def test_each_component_sees_only_its_own_versions(tmp_path):
    repo = pages_repo(
        tmp_path, {"cpp": ["unstable", "3.4.2"], "python": ["unstable", "1.1.1"]}
    )
    assert "1.1.1" not in make_manifest.published_versions("cpp", "gh-pages", repo)
    assert "3.4.2" not in make_manifest.published_versions("python", "gh-pages", repo)


def test_order_is_unstable_then_newest_first():
    """Lexical order would put 3.10.0 before 3.4.2 and unstable last."""
    assert make_manifest.order({"3.4.2", "3.10.0", "3.4.10", "4.0.0", "unstable"}) == [
        "unstable",
        "4.0.0",
        "3.10.0",
        "3.4.10",
        "3.4.2",
    ]


def test_a_component_with_nothing_published_yet(tmp_path):
    """A first publish: the branch exists, this component does not."""
    repo = pages_repo(tmp_path, {"cpp": ["unstable"]})
    assert make_manifest.published_versions("python", "gh-pages", repo) == []


def test_a_branch_that_does_not_exist_yet(tmp_path):
    """A first rehearsal deploys to a branch nobody has pushed. Nothing is
    published there, which is different from being unable to tell."""
    origin = pages_repo(tmp_path, {"cpp": ["unstable"]}, name="origin")
    repo = pages_repo(tmp_path, {"cpp": ["unstable"]}, name="clone")
    subprocess.run(
        ["git", "remote", "add", "origin", str(origin)],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    assert make_manifest.published_versions("cpp", "rehearse-1", repo) == []


def test_an_unreadable_branch_is_an_error_not_an_empty_list(tmp_path):
    """Carrying on would publish a manifest naming one version and silently
    empty the switcher -- the exact failure this replaces."""
    repo = pages_repo(tmp_path, {"cpp": ["unstable", "3.4.2"]})
    with pytest.raises(SystemExit, match="cannot read branch"):
        make_manifest.published_versions("cpp", "gh-pages-unreachable", repo)


def test_a_local_build_lists_only_what_it_built(tmp_path):
    out = tmp_path / "artifact"
    out.mkdir()
    assert make_manifest.write(out, "cpp", "unstable", "https://x/cccl") == ["unstable"]


def test_a_rolling_version_is_refused(tmp_path):
    """3.4 would be a directory whose content changes with every patch."""
    out = tmp_path / "artifact"
    out.mkdir()
    with pytest.raises(SystemExit, match="not a publishable version"):
        make_manifest.write(out, "cpp", "3.4", "https://x/cccl")


def test_urls_name_the_site_being_published_to(tmp_path):
    """A rehearsal on a fork must not hand readers a dropdown whose every
    option navigates to production."""
    out = tmp_path / "artifact"
    out.mkdir()
    (out / "index.html").write_text(
        '<link rel="canonical" href="https://nvidia.github.io/cccl/cpp/unstable/">',
        encoding="utf-8",
    )
    make_manifest.write(out, "cpp", "unstable", "https://fork.example/cccl")
    make_manifest.retarget_landing(out, "cpp", "https://fork.example/cccl")

    body = (out / "nv-versions.json").read_text(encoding="utf-8")
    landing = (out / "index.html").read_text(encoding="utf-8")
    assert "https://fork.example/cccl/cpp/unstable/" in body
    assert "nvidia.github.io" not in body
    assert "https://fork.example/cccl/cpp/unstable/" in landing
    assert "nvidia.github.io" not in landing


def test_checked_in_redirects_still_name_production():
    """The landing redirect is edited in the artifact, never in the repository:
    a real release goes to production, so the source must keep pointing there."""
    for component in ("cpp", "python"):
        redirect = (DOCS / f"{component}_site" / "index.html").read_text()
        assert "https://nvidia.github.io/cccl/" in redirect, component


def test_no_manifest_is_checked_in():
    """It is generated. A checked-in copy would be a second source of truth,
    and the one that is wrong whenever a release has shipped since it was
    edited."""
    for component in ("cpp", "python"):
        assert not (DOCS / f"{component}_site" / "nv-versions.json").exists(), component


# --------------------------------------------------------------------------
# Build scripts
# --------------------------------------------------------------------------


@pytest.mark.parametrize("label", ["unstable", "3.4.2", "1.1.1", "3.10.0"])
def test_build_scripts_accept_valid_labels(label):
    for script in ("gen_docs.bash", "gen_python_docs.bash"):
        assert _label_accepted(DOCS / script, label), f"{script} rejected {label}"


@pytest.mark.parametrize("label", ["latest", "3.4", "unstable; rm -rf /", "v3.4.2", ""])
def test_build_scripts_reject_bad_labels(label):
    """No rolling MAJOR.MINOR directory, and no shell injection."""
    if label == "":
        return  # empty falls back to the default, covered elsewhere
    for script in ("gen_docs.bash", "gen_python_docs.bash"):
        assert not _label_accepted(DOCS / script, label), f"{script} accepted {label}"


def _label_accepted(script, label):
    """Run only the script's label validation, without building anything."""
    check = subprocess.run(
        [
            "bash",
            "-c",
            (
                'VERSION="$1"; '
                'if [[ ! "${VERSION}" =~ ^(unstable|[0-9]+\\.[0-9]+\\.[0-9]+)$ ]]; '
                "then exit 1; fi"
            ),
            "_",
            label,
        ],
        capture_output=True,
        check=False,
    )
    return check.returncode == 0


def test_loose_markdown_is_excluded_by_name():
    """MyST treats any .md sitting in docs/ as a document, and a document in no
    toctree is a warning -- which these builds treat as an error. So a file
    dropped in beside the sources has to be excluded by name, or it fails the
    build in a way that reads as unrelated to the file that caused it."""
    config = (DOCS / "conf.py").read_text(encoding="utf-8")
    for md in sorted(DOCS.glob("*.md")):
        assert md.name in config, (
            f"{md.name} sits in docs/ and is not in exclude_patterns; MyST will "
            "treat it as a document in no toctree and fail the C++ build"
        )


def test_build_scripts_generate_the_manifest():
    """A generator that is written but not wired in produces nothing, and the
    artifact would ship without the file the switcher fetches."""
    for script in ("gen_docs.bash", "gen_python_docs.bash"):
        body = (DOCS / script).read_text(encoding="utf-8")
        assert "make_manifest.py" in body, script
        assert "--from-branch" in body, script
        # And no longer copied from the repository, which would reintroduce a
        # second source of truth the generated one would fight with.
        copied = [
            ln
            for ln in body.splitlines()
            if ln.strip().startswith("cp ") and "nv-versions.json" in ln
        ]
        assert not copied, (script, copied)


def test_the_workflow_tells_the_build_which_branch_to_read():
    """Without it every build would fall back to listing only itself, which is
    correct locally and empties the switcher in CI."""
    body = BUILD_WORKFLOW.read_text(encoding="utf-8")
    assert body.count("CCCL_DOCS_BRANCH: ${{ inputs.docs-branch }}") == 3, (
        "every build step must pass the branch the run deploys to"
    )


def test_build_scripts_are_syntactically_valid():
    for script in ("gen_docs.bash", "gen_python_docs.bash", "gen_all_docs.bash"):
        result = subprocess.run(
            ["bash", "-n", str(DOCS / script)], capture_output=True, check=False
        )
        assert result.returncode == 0, f"{script}: {result.stderr.decode()}"


# --------------------------------------------------------------------------
# Workflow shape
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def build_workflow():
    return yaml.safe_load(BUILD_WORKFLOW.read_text(encoding="utf-8"))


def _deploy_steps(workflow):
    return [
        s
        for s in workflow["jobs"]["build"]["steps"]
        if "actions-gh-pages" in str(s.get("uses", ""))
    ]


def _deploy_step(workflow):
    return _deploy_steps(workflow)[0]


def test_deployment_is_additive(build_workflow):
    """One step writes to the site root, and it must never remove: its
    destination covers every other version and the other language's tree."""
    additive = [
        s for s in _deploy_steps(build_workflow) if s["with"]["keep_files"] is True
    ]
    assert len(additive) == 1
    assert additive[0]["with"]["destination_dir"] == "docs"
    # And it is the one step with no condition beyond deploying at all, so
    # every publication path goes through it.
    assert additive[0]["if"].strip() == "${{ inputs.deploy-docs }}"


def test_each_version_directory_is_replaced(build_workflow):
    """A directory equals its build: a page deleted from the source stops being
    served. Scoped to the version just built -- pointed any wider it would
    delete other published versions."""
    replacing = [
        s for s in _deploy_steps(build_workflow) if s["with"]["keep_files"] is False
    ]
    assert [s["with"]["destination_dir"] for s in replacing] == [
        "docs/cpp/${{ steps.label.outputs.label }}",
        "docs/python/${{ steps.label.outputs.label }}",
    ]
    for step in replacing:
        # Keyed on the resolved label, so unstable and a release take the same
        # path and the release path cannot go untested.
        assert "steps.label.outputs.label" in step["with"]["destination_dir"]
        # Source and destination must name the same version directory, or a
        # build would replace a directory it did not produce.
        assert (
            step["with"]["publish_dir"]
            .rstrip("/")
            .endswith(step["with"]["destination_dir"])
        )


def test_replacing_never_reaches_a_sibling_version(build_workflow):
    """The destination always carries a label, so no step can target a
    component root and take every version of it with the clean."""
    for step in _deploy_steps(build_workflow):
        dest = step["with"]["destination_dir"]
        if step["with"]["keep_files"] is False:
            assert dest.count("/") == 2, dest


def test_an_unexpected_label_stops_the_build(build_workflow):
    """The label is interpolated into the destination the deploy replaces, so
    an empty one would aim it at the component root and delete every version
    published under it. That has to fail before any deploy step runs."""
    steps = build_workflow["jobs"]["build"]["steps"]
    check = next(s for s in steps if s.get("name") == "Check the artifact")
    assert "unstable|[0-9]+\\.[0-9]+\\.[0-9]+" in check["run"]

    names = [s.get("name") for s in steps]
    deploys = [s.get("name") for s in _deploy_steps(build_workflow)]
    assert names.index("Check the artifact") < min(names.index(d) for d in deploys)


def test_a_near_empty_build_cannot_empty_a_tree(build_workflow):
    """The risk clean: true introduces: a build that succeeds while producing
    almost nothing would delete the pages it fails to replace."""
    check = next(
        s
        for s in build_workflow["jobs"]["build"]["steps"]
        if s.get("name") == "Check the artifact"
    )
    assert "FLOOR" in check["run"]
    assert "[cpp]=" in check["run"] and "[python]=" in check["run"]


def test_deploy_action_is_pinned_to_a_sha(build_workflow):
    deploy = _deploy_step(build_workflow)
    ref = deploy["uses"].split("@")[1]
    assert len(ref) == 40 and all(c in "0123456789abcdef" for c in ref), ref


def test_branch_is_not_recreated_as_an_orphan(build_workflow):
    """force_orphan rebuilds the branch from the artifact, so the site becomes
    exactly the last build and no earlier version survives. It is the setting
    that made versioning impossible, and it must be false on every step."""
    steps = _deploy_steps(build_workflow)
    assert steps, "no deploy steps found"
    for step in steps:
        assert step["with"]["force_orphan"] is False, step["name"]


def test_every_build_path_builds_something(build_workflow):
    """A release passes component=all and lets the tag decide, so gating the
    build steps on the caller's input silently produced an empty artifact."""
    steps = {
        s["name"]: s.get("if", "") for s in build_workflow["jobs"]["build"]["steps"]
    }
    for name in ("Build both components", "Build C++", "Build Python"):
        assert name in steps
    # The single-component steps must key off the resolved component, not the input.
    assert "steps.label.outputs.components == 'cpp'" in steps["Build C++"]
    assert "steps.label.outputs.components == 'python'" in steps["Build Python"]


def test_smoke_matrix_covers_every_launch_route():
    """The §7.3 matrix. A route that is not listed is never checked."""
    import smoke_site

    assert dict(smoke_site.COMPONENTS) == {"cpp": "3.4.2", "python": "1.1.1"}
    assert smoke_site.DEFAULT_BASE == "https://nvidia.github.io/cccl"


@pytest.mark.parametrize(
    "repository,expected",
    [
        ("NVIDIA/cccl", "https://nvidia.github.io/cccl"),
        ("sri-koundinyan/cccl", "https://sri-koundinyan.github.io/cccl"),
        ("Some-Org/cccl", "https://some-org.github.io/cccl"),
    ],
)
def test_site_url_derives_from_the_repository(repository, expected):
    """Pages serves <owner>.github.io/<repo> with the owner lowercased, which
    for NVIDIA/cccl is exactly the production URL -- so one rule covers
    production and every fork, and a fork need not pass anything.

    Runs the workflow's own expression rather than a restatement of it."""
    script = (
        'owner="${REPOSITORY%%/*}"; name="${REPOSITORY#*/}"; '
        'echo "https://${owner,,}.github.io/${name}"'
    )
    out = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        check=True,
        env={"REPOSITORY": repository, "PATH": "/usr/bin:/bin"},
    )
    assert out.stdout.decode().strip() == expected


def test_explicit_site_url_wins(build_workflow):
    """A custom domain is not derivable from the repository name."""
    step = next(
        s for s in build_workflow["jobs"]["build"]["steps"] if s.get("id") == "site"
    )
    body = step["run"]
    assert 'if [[ -n "${SITE_URL}" ]]' in body
    assert body.index('SITE_URL}"') < body.index("github.io")


def test_rehearsal_can_name_its_own_origin(build_workflow):
    """A rehearsal on a fork is a different origin. The switcher is fetched by
    the browser, so pages built for production point it at production and the
    dropdown comes up empty -- a failure that renders perfectly."""
    # YAML 1.1 reads a bare `on:` key as the boolean true, so the trigger block
    # is keyed by True rather than "on".
    triggers = build_workflow.get("on") or build_workflow[True]
    assert "site-url" in triggers["workflow_call"]["inputs"]
    for name in ("Build both components", "Build C++", "Build Python"):
        step = next(
            s for s in build_workflow["jobs"]["build"]["steps"] if s.get("name") == name
        )
        env = step.get("env", {})
        assert "CCCL_DOCS_SITE_URL" in env, name
        # The derived value, not the raw input: the input is usually empty.
        assert "steps.site.outputs.url" in env["CCCL_DOCS_SITE_URL"], name


def test_release_and_development_share_one_workflow():
    """Two publication paths, one implementation, so they cannot drift."""
    deploy = yaml.safe_load(DEPLOY_WORKFLOW.read_text(encoding="utf-8"))
    uses = {j["uses"] for j in deploy["jobs"].values()}
    assert uses == {"./.github/workflows/build-docs.yml"}


def test_no_legacy_combined_paths_remain():
    """The old combined scheme is retired; nothing should still point at it.

    This can no longer match on the bare word. The development directory is
    itself called `unstable` now, so `/cccl/python/unstable/` is current while
    `/cccl/unstable/python/` is the retired one. Position is what distinguishes
    them: the old scheme put the label directly under /cccl/."""
    text = (DOCS / "index.html").read_text(encoding="utf-8")
    assert "/cccl/unstable/" not in text, "links at the retired combined tree"
    assert "unstable/python" not in text, "links at Python nested inside C++"
    assert 'href="cpp/unstable/"' in text
    assert 'href="python/unstable/"' in text


def test_no_custom_404_is_shipped():
    """A missing URL gets an ordinary 404. Fuzzy routing is out of scope, and
    Pages serves one 404.html per site, so a component cannot own one anyway."""
    assert not (DOCS / "404.html").exists()
    for script in ("gen_docs.bash", "gen_python_docs.bash", "gen_all_docs.bash"):
        body = (DOCS / script).read_text(encoding="utf-8")
        assert 'cp "./404.html"' not in body, script
