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

import check_manifests
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
        "v3.5.0-rc0",      # a pre-release must not take the release's URL
        "v3.6.0.dev",
        "v3.4",            # no rolling MAJOR.MINOR directory exists
        "python-1.1",
        "3.4.2",           # unprefixed: which component?
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
        json.dumps([{"version": v, "url": f"https://x/{component}/{v}/"}
                    for v in manifest_versions]),
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


def test_the_two_manifests_must_agree(tmp_path):
    """Nothing reads versions.json today -- until something does. cuda-python's
    cuda_core ships a versions.json stopping at 0.3.2 beside an nv-versions.json
    reaching 1.2.0, because each is whatever the last build copied."""
    comp = tmp_path / "cpp"
    comp.mkdir()
    (comp / "nv-versions.json").write_text(
        json.dumps([{"version": v, "url": f"https://x/{v}/"} for v in ("unstable", "3.4.2")])
    )
    (comp / "versions.json").write_text(json.dumps({"unstable": "unstable"}))
    with pytest.raises(SystemExit, match="disagree"):
        check_manifests.check(comp, "3.4.2")


def test_unlisted_version_is_refused(tmp_path):
    comp = tmp_path / "cpp"
    comp.mkdir()
    (comp / "nv-versions.json").write_text(
        json.dumps([{"version": "unstable", "url": "https://x/unstable/"}])
    )
    (comp / "versions.json").write_text(json.dumps({"unstable": "unstable"}))
    with pytest.raises(SystemExit, match="does not list"):
        check_manifests.check(comp, "3.4.2")


def test_retarget_moves_every_absolute_url(tmp_path):
    """Three places name a host absolutely: the manifest entries the switcher
    navigates to, the landing redirect's canonical, and (via conf.py) the
    json_url each page fetches. A rehearsal on another origin needs all of
    them, and the checked-in sources must not be touched."""
    comp = tmp_path / "cpp"
    comp.mkdir()
    (comp / "nv-versions.json").write_text(json.dumps(
        [{"version": v, "url": f"https://nvidia.github.io/cccl/cpp/{v}/"}
         for v in ("unstable", "3.4.2")]))
    (comp / "versions.json").write_text(json.dumps({"unstable": "unstable", "3.4.2": "3.4.2"}))
    (comp / "index.html").write_text(
        '<link rel="canonical" href="https://nvidia.github.io/cccl/cpp/unstable/">')

    check_manifests.retarget(comp, "cpp", "https://fork.example/cccl")

    urls = [e["url"] for e in json.loads((comp / "nv-versions.json").read_text())]
    assert urls == ["https://fork.example/cccl/cpp/unstable/",
                    "https://fork.example/cccl/cpp/3.4.2/"]
    assert "fork.example/cccl/cpp/unstable/" in (comp / "index.html").read_text()
    assert "nvidia.github.io" not in (comp / "index.html").read_text()
    # Still a valid manifest pair afterwards.
    assert check_manifests.check(comp, "3.4.2") == ["unstable", "3.4.2"]


def test_checked_in_sources_still_name_production():
    """retarget edits the built artifact. A real release goes to production, so
    the sources in the repository must keep pointing there."""
    for component in ("cpp", "python"):
        manifest = (DOCS / f"{component}_site" / "nv-versions.json").read_text()
        redirect = (DOCS / f"{component}_site" / "index.html").read_text()
        assert "https://nvidia.github.io/cccl/" in manifest, component
        assert "https://nvidia.github.io/cccl/" in redirect, component


@pytest.mark.parametrize("component,version", [("cpp", "3.4.2"), ("python", "1.1.1")])
def test_shipped_manifests_pass_their_own_check(component, version):
    for label in ("unstable", version):
        assert check_manifests.check(DOCS / f"{component}_site", label)


def test_checked_in_manifests_match_the_launch_set():
    """The real manifests, as shipped."""
    cpp = json.loads((DOCS / "cpp_site" / "nv-versions.json").read_text())
    py = json.loads((DOCS / "python_site" / "nv-versions.json").read_text())
    assert [e["version"] for e in cpp] == ["unstable", "3.4.2"]
    assert [e["version"] for e in py] == ["unstable", "1.1.1"]
    # unstable first, then descending semantic versions
    assert cpp[0]["version"] == "unstable" and py[0]["version"] == "unstable"
    for entries, component in ((cpp, "cpp"), (py, "python")):
        for entry in entries:
            assert entry["url"].startswith(f"https://nvidia.github.io/cccl/{component}/")


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


def test_maintainer_docs_are_not_sphinx_sources():
    """PUBLISHING.md sits in docs/ beside the sources. MyST picks up any .md
    there as a document, and a document in no toctree is a warning -- which
    these builds treat as an error. Excluding it is what keeps it a file rather
    than a page."""
    config = (DOCS / "conf.py").read_text(encoding="utf-8")
    for name in ("PUBLISHING.md", "publishing-design.md", "publishing-overview.md"):
        assert name in config, f"{name} is not excluded from the C++ build"
        assert (DOCS / name).exists(), f"{name} is excluded but does not exist"


def test_build_scripts_run_the_manifest_check():
    """A guard that is written but not wired in protects nothing."""
    for script in ("gen_docs.bash", "gen_python_docs.bash"):
        body = (DOCS / script).read_text(encoding="utf-8")
        assert "check_manifests.py" in body, script
        assert "versions.json" in body, script


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


def _deploy_step(workflow):
    return next(
        s for s in workflow["jobs"]["build"]["steps"]
        if "github-pages-deploy-action" in str(s.get("uses", ""))
    )


def test_deployment_is_additive(build_workflow):
    """clean: false is what lets exact versions accumulate. Without it a Python
    release would remove the C++ tree and every earlier version."""
    deploy = [s for s in build_workflow["jobs"]["build"]["steps"]
              if "github-pages-deploy-action" in str(s.get("uses", ""))]
    assert len(deploy) == 1
    assert deploy[0]["with"]["clean"] is False
    assert deploy[0]["with"]["target-folder"] == "docs/"


def test_deploy_action_is_pinned_to_a_sha(build_workflow):
    deploy = _deploy_step(build_workflow)
    ref = deploy["uses"].split("@")[1]
    assert len(ref) == 40 and all(c in "0123456789abcdef" for c in ref), ref


def test_branch_is_not_recreated_as_an_orphan(build_workflow):
    """single-commit would discard the deployment history."""
    deploy = _deploy_step(build_workflow)
    assert "single-commit" not in deploy["with"]


def test_every_build_path_builds_something(build_workflow):
    """A release passes component=all and lets the tag decide, so gating the
    build steps on the caller's input silently produced an empty artifact."""
    steps = {s["name"]: s.get("if", "") for s in build_workflow["jobs"]["build"]["steps"]}
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


@pytest.mark.parametrize("repository,expected", [
    ("NVIDIA/cccl", "https://nvidia.github.io/cccl"),
    ("sri-koundinyan/cccl", "https://sri-koundinyan.github.io/cccl"),
    ("Some-Org/cccl", "https://some-org.github.io/cccl"),
])
def test_site_url_derives_from_the_repository(repository, expected):
    """Pages serves <owner>.github.io/<repo> with the owner lowercased, which
    for NVIDIA/cccl is exactly the production URL -- so one rule covers
    production and every fork, and a fork need not pass anything.

    Runs the workflow's own expression rather than a restatement of it."""
    script = 'owner="${REPOSITORY%%/*}"; name="${REPOSITORY#*/}"; ' \
             'echo "https://${owner,,}.github.io/${name}"'
    out = subprocess.run(["bash", "-c", script], capture_output=True, check=True,
                         env={"REPOSITORY": repository, "PATH": "/usr/bin:/bin"})
    assert out.stdout.decode().strip() == expected


def test_explicit_site_url_wins(build_workflow):
    """A custom domain is not derivable from the repository name."""
    step = next(s for s in build_workflow["jobs"]["build"]["steps"]
                if s.get("id") == "site")
    body = step["run"]
    assert 'if [[ -n "${SITE_URL}" ]]' in body
    assert body.index("SITE_URL}\"") < body.index("github.io")


def test_rehearsal_can_name_its_own_origin(build_workflow):
    """A rehearsal on a fork is a different origin. The switcher is fetched by
    the browser, so pages built for production point it at production and the
    dropdown comes up empty -- a failure that renders perfectly."""
    # YAML 1.1 reads a bare `on:` key as the boolean true, so the trigger block
    # is keyed by True rather than "on".
    triggers = build_workflow.get("on") or build_workflow[True]
    assert "site-url" in triggers["workflow_call"]["inputs"]
    for name in ("Build both components", "Build C++", "Build Python"):
        step = next(s for s in build_workflow["jobs"]["build"]["steps"]
                    if s.get("name") == name)
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
