"""Tests for release identity, planning, and site assembly.

These run against stubbed Sphinx output -- no Doxygen, no Sphinx, well under a
second -- so the publication behaviour can be exercised without a fifteen-minute
build. That matters because every failure mode here is silent: a switcher that
never highlights the current page, a version listed but not published, a release
quietly replaced by an older one. None of them break a build, and several would
render perfectly while being wrong.

Run directly, or through the pre-commit hook that runs them on every PR:

    pytest docs/test_publish_site.py
"""

import json
import subprocess

import deploy_plan
import publish_site
import pytest
import release_version

# Note on naming: keep test function names off exactly 40 characters. Lob API
# test keys are literally "test_" followed by 35 characters, so the repository's
# secret scanner reports any 40-character test_* identifier as a verified
# credential.


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


def make_artifact(tmp_path, name, stamp, pages=()):
    """A stand-in for one component's built output."""
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    marker = f"version_match = '{stamp}';" if stamp is not None else ""
    (root / "index.html").write_text(
        f"<html><script>{marker}</script></html>", encoding="utf-8"
    )
    (root / "objects.inv").write_text("inv", encoding="utf-8")
    for page in pages:
        (root / page).write_text("<html>page</html>", encoding="utf-8")
    return root


def make_site(tmp_path, shell=True):
    """An empty but structurally valid published site."""
    root = tmp_path / "site"
    (root / "python").mkdir(parents=True, exist_ok=True)
    if shell:
        (root / ".nojekyll").write_text("", encoding="utf-8")
        (root / "index.html").write_text("<html>chooser</html>", encoding="utf-8")
        (root / "404.html").write_text("<html>404</html>", encoding="utf-8")
        (root / "python" / "index.html").write_text("<html>py</html>", encoding="utf-8")
    return root


def plan_file(tmp_path, **plan):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    return str(path)


def publish(site, plan_path, *extra):
    return publish_site.main([str(site), "--plan", plan_path, *extra])


def unstable_plan(tmp_path, site, cpp_stamp="unstable", py_stamp="unstable"):
    return plan_file(
        tmp_path,
        mode="unstable",
        version_dir="unstable",
        release=None,
        release_source_sha="abc123",
        publisher_sha="pub1",
        components=[
            {"id": "cpp", "artifact": str(make_artifact(tmp_path, "a-cpp", cpp_stamp))},
            {"id": "python", "artifact": str(make_artifact(tmp_path, "a-py", py_stamp))},
        ],
    )


# --------------------------------------------------------------------------
# Tag grammar and identity
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tag,expected",
    [
        ("v3.4.2", ("cpp", "3.4", "3.4.2")),
        ("v3.10.0", ("cpp", "3.10", "3.10.0")),
        ("python-1.1.1", ("python", "1.1", "1.1.1")),
    ],
)
def test_final_tags_name_a_destination(tag, expected):
    assert release_version.classify_tag(tag) == expected


@pytest.mark.parametrize(
    "tag",
    ["v3.5.0-rc0", "v3.6.0.dev", "3.4.2", "python-1.1", "refs/tags/v3.4.2", "main", ""],
)
def test_non_final_tags_rejected(tag):
    """A tag determines the component and destination, so it must be exact."""
    with pytest.raises(SystemExit):
        release_version.classify_tag(tag)


def test_annotated_tags_peel_recursively(tmp_path):
    """One annotated tag can point at another before reaching a commit."""
    run = lambda *a: subprocess.run(
        a, cwd=tmp_path, check=True, capture_output=True
    )
    run("git", "init", "-q", ".")
    run("git", "-c", "user.email=t@t", "-c", "user.name=t",
        "commit", "-q", "--allow-empty", "-m", "c")
    run("git", "-c", "user.email=t@t", "-c", "user.name=t",
        "tag", "-a", "inner", "-m", "inner")
    # An annotated tag whose target is another annotated tag.
    run("git", "-c", "user.email=t@t", "-c", "user.name=t",
        "tag", "-a", "v3.4.2", "-m", "outer", "inner")

    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True,
        text=True, check=True,
    ).stdout.strip()
    tag_object, source = release_version.peel_tag(tmp_path, "v3.4.2")

    assert source == commit
    assert tag_object != commit  # the tag object is its own thing


def test_pre_split_source_rejected(tmp_path):
    """Rejected in seconds, not after a fifteen-minute Doxygen build."""
    with pytest.raises(SystemExit) as excinfo:
        release_version.require_split_build_contract(tmp_path)
    assert "python_conf" in str(excinfo.value)

    (tmp_path / "docs" / "python_conf").mkdir(parents=True)
    (tmp_path / "docs" / "python_conf" / "conf.py").write_text("x", encoding="utf-8")
    release_version.require_split_build_contract(tmp_path)


# --------------------------------------------------------------------------
# Downgrade and target state
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "existing,incoming,expected",
    [
        ("3.4.2", "3.4.1", True),    # a delayed or re-run older release
        ("3.4.2", "3.4.3", False),   # ordinary patch
        ("3.4.2", "3.4.2", False),   # same release
        ("3.4.2", None, False),      # publishing the tip; nothing to compare
        ("", "3.4.1", None),         # something is there, but unidentifiable
    ],
)
def test_downgrade_is_three_valued(existing, incoming, expected):
    """"Cannot tell" is not "safe": reading it as safe is a fail-open."""
    assert release_version.is_downgrade(existing, incoming) is expected


def test_absent_directory_is_a_new_line(tmp_path):
    """The first /3.5/ has no prior release to authenticate against."""
    action, existing = release_version.classify_target(tmp_path / "3.5", "3.5.0")
    assert action == "create" and existing is None


def test_unprovenanced_directory_refused(tmp_path):
    """Absence of a directory is a new line; absence of provenance inside is not."""
    target = tmp_path / "3.4"
    target.mkdir()
    (target / "index.html").write_text("<html></html>", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        release_version.classify_target(target, "3.4.1")
    assert "no valid provenance" in str(excinfo.value)


def test_older_patch_refused(tmp_path):
    target = tmp_path / "3.4"
    target.mkdir()
    (target / release_version.PROVENANCE_FILE).write_text(
        json.dumps(release_version.build_provenance("cpp", "3.4", release="3.4.2")),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit) as excinfo:
        release_version.classify_target(target, "3.4.1")
    assert "refusing to publish" in str(excinfo.value)


def test_newer_patch_replaces(tmp_path):
    target = tmp_path / "3.4"
    target.mkdir()
    (target / release_version.PROVENANCE_FILE).write_text(
        json.dumps(release_version.build_provenance("cpp", "3.4", release="3.4.2")),
        encoding="utf-8",
    )
    action, _ = release_version.classify_target(target, "3.4.3")
    assert action == "replace"


def test_publisher_identity_is_audit_only():
    """A later publisher verifying an existing identity changes nothing.

    Including publisher_sha in the comparison would turn routine re-dispatch
    into a failure without preventing any content replacement, because an equal
    identity writes nothing either way.
    """
    a = release_version.build_provenance(
        "cpp", "3.4", release="3.4.2", release_source_sha="s", publisher_sha="p1"
    )
    b = release_version.build_provenance(
        "cpp", "3.4", release="3.4.2", release_source_sha="s", publisher_sha="p2"
    )
    assert release_version.same_content_identity(a, b)

    c = release_version.build_provenance(
        "cpp", "3.4", release="3.4.2", release_source_sha="other", publisher_sha="p1"
    )
    assert not release_version.same_content_identity(a, c)


# --------------------------------------------------------------------------
# Planning
# --------------------------------------------------------------------------


def test_main_push_publishes_both(tmp_path):
    """One push advances both components, so one publication covers both."""
    result = deploy_plan.plan("push", source_sha="abc")
    assert result["components"] == ["cpp", "python"]
    assert result["version_dir"] == "unstable"
    assert result["release"] is None


def test_release_publishes_one_component(tmp_path):
    repo = _post_split_repo(tmp_path)
    result = deploy_plan.plan("workflow_dispatch", release_tag="v3.5.0", checkout=repo)
    assert result["components"] == ["cpp"]
    assert result["version_dir"] == "3.5"
    assert result["checkout_ref"] == "refs/tags/v3.5.0"


def test_refs_are_qualified(tmp_path):
    """actions/checkout resolves a bare name as a branch first."""
    repo = _post_split_repo(tmp_path)
    result = deploy_plan.plan("workflow_dispatch", release_tag="v3.5.0", checkout=repo)
    assert result["checkout_ref"].startswith("refs/tags/")


def test_dispatch_needs_a_tag():
    with pytest.raises(SystemExit):
        deploy_plan.plan("workflow_dispatch")


def test_no_other_trigger_publishes():
    with pytest.raises(SystemExit):
        deploy_plan.plan("release", release_tag="v3.5.0")


def test_output_cannot_forge_a_second_key():
    with pytest.raises(SystemExit) as excinfo:
        deploy_plan.emittable("version_dir", "3.4\nmode=release")
    assert "workflow output" in str(excinfo.value)


def _post_split_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "docs" / "python_conf").mkdir(parents=True)
    (repo / "docs" / "python_conf" / "conf.py").write_text("x", encoding="utf-8")
    run = lambda *a: subprocess.run(
        a, cwd=repo, check=True, capture_output=True
    )
    run("git", "init", "-q", ".")
    run("git", "add", "-A")
    run("git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "c")
    run("git", "-c", "user.email=t@t", "-c", "user.name=t",
        "tag", "-a", "v3.5.0", "-m", "r")
    return str(repo)


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------


def test_unstable_publishes_both_components(tmp_path):
    site = make_site(tmp_path)
    publish(site, unstable_plan(tmp_path, site))

    assert (site / "unstable" / "index.html").is_file()
    assert (site / "python" / "unstable" / "index.html").is_file()
    cpp = json.loads((site / "nv-versions.json").read_text())
    assert [e["version"] for e in cpp] == ["unstable"]
    py = json.loads((site / "python" / "nv-versions.json").read_text())
    assert [e["version"] for e in py] == ["unstable"]


def test_versions_sort_with_the_tip_first(tmp_path):
    """Lexicographically "3.9" sorts after "3.10" and "4.0" lands wrong."""
    site = make_site(tmp_path)
    for name in ("unstable", "3.9", "3.10", "4.0"):
        d = site / name
        d.mkdir(parents=True)
        (d / "index.html").write_text("<html></html>", encoding="utf-8")
    assert publish_site.discover_versions(site) == ["unstable", "4.0", "3.10", "3.9"]


def test_partial_upload_is_not_advertised(tmp_path):
    """A directory joins the switcher by containing an index, not by existing."""
    site = make_site(tmp_path)
    (site / "3.4").mkdir()
    assert publish_site.discover_versions(site) == []


def test_missing_stamp_is_rejected(tmp_path):
    """A stamp that cannot be read is not a reason to skip the check."""
    site = make_site(tmp_path)
    with pytest.raises(SystemExit):
        publish(site, unstable_plan(tmp_path, site, cpp_stamp=None))


def test_patch_valued_stamp_is_rejected(tmp_path):
    """/cccl/3.4/ means "the 3.4 line"; stamping 3.4.2 breaks the switcher."""
    site = make_site(tmp_path)
    plan = plan_file(
        tmp_path,
        mode="release",
        version_dir="3.4",
        release="3.4.2",
        release_tag="v3.4.2",
        release_source_sha="s",
        publisher_sha="p",
        components=[{"id": "cpp", "artifact": str(make_artifact(tmp_path, "a", "3.4.2"))}],
    )
    with pytest.raises(SystemExit):
        publish(site, plan)

    # And specifically for the stamp, not incidentally for some other reason.
    problems = []
    publish_site.check_stamps(site, publish_site.COMPONENTS[0], ["3.4"], problems)
    assert problems and "stamped '3.4.2'" in problems[0]


def test_missing_nojekyll_is_rejected(tmp_path):
    """Every route still returns 200 without it; only this check sees the loss."""
    site = make_site(tmp_path, shell=True)
    (site / ".nojekyll").unlink()
    with pytest.raises(SystemExit):
        publish(site, unstable_plan(tmp_path, site))


def test_cpp_release_leaves_python_untouched(tmp_path):
    """A C++ release may not write a single byte of Python content."""
    site = make_site(tmp_path)
    publish(site, unstable_plan(tmp_path, site))
    before = publish_site.snapshot(site / "python")

    plan = plan_file(
        tmp_path,
        mode="release",
        version_dir="3.4",
        release="3.4.2",
        release_tag="v3.4.2",
        release_source_sha="s",
        publisher_sha="p",
        components=[{"id": "cpp", "artifact": str(make_artifact(tmp_path, "a34", "3.4"))}],
    )
    publish(site, plan)

    assert publish_site.snapshot(site / "python") == before
    assert (site / "3.4" / release_version.RELEASE_FILE).read_text().strip() == "3.4.2"


def test_out_of_scope_change_is_rejected(tmp_path):
    """The write set is a checked property, not an intention."""
    site = make_site(tmp_path)
    publish(site, unstable_plan(tmp_path, site))

    before = publish_site.snapshot(site)
    after = dict(before)
    after["3.4/index.html"] = "deadbeef"
    problems = []
    publish_site.check_write_set(
        before, after,
        publish_site.allowed_write_set("unstable", publish_site.COMPONENTS, "unstable"),
        problems,
    )
    assert problems and "3.4/index.html" in problems[0]


def test_shell_files_are_not_in_any_write_set(tmp_path):
    """An ordinary publication may never change what every reader first sees."""
    allowed = publish_site.allowed_write_set(
        "unstable", publish_site.COMPONENTS, "unstable"
    )
    for shell in publish_site.SHELL_FILES:
        assert not any(
            shell == rule or shell.startswith(rule) for rule in allowed
        ), shell


def test_inventory_aliases_are_component_owned(tmp_path):
    """The root inventory carries C++ targets; Python owns its own."""
    site = make_site(tmp_path)
    publish(site, unstable_plan(tmp_path, site))
    assert (site / "objects.inv").is_file()
    assert (site / "python" / "objects.inv").is_file()


def test_no_latest_alias_is_created(tmp_path):
    """A deliberately negative check: the MVP has no latest."""
    site = make_site(tmp_path)
    publish(site, unstable_plan(tmp_path, site))
    assert not (site / "latest").exists()
    assert not (site / "python" / "latest").exists()


def test_nothing_is_deleted_automatically(tmp_path):
    """No retention: an old release survives an unrelated publication."""
    site = make_site(tmp_path)
    old = site / "3.4"
    old.mkdir()
    (old / "index.html").write_text("<html><script>version_match = '3.4';</script></html>", encoding="utf-8")
    (old / release_version.PROVENANCE_FILE).write_text(
        json.dumps(release_version.build_provenance("cpp", "3.4", release="3.4.2")),
        encoding="utf-8",
    )
    publish(site, unstable_plan(tmp_path, site))
    assert (old / "index.html").is_file()


def test_missing_seed_stops_publication(tmp_path):
    """A failed read of the live site is never an empty site."""
    with pytest.raises(SystemExit):
        publish(tmp_path / "nonexistent", unstable_plan(tmp_path, tmp_path / "site"))


# --------------------------------------------------------------------------
# Tree identity
# --------------------------------------------------------------------------


def test_identical_trees_share_an_identity(tmp_path):
    """The identity approved on staging is what production must reproduce."""
    ids = []
    for name in ("one", "two"):
        site = tmp_path / name
        (site / "python").mkdir(parents=True)
        (site / ".nojekyll").write_text("", encoding="utf-8")
        (site / "index.html").write_text("<html>x</html>", encoding="utf-8")
        ids.append(publish_site.subtree_identity(site))
    assert ids[0] is not None and ids[0] == ids[1]


def test_executable_file_makes_identity_ambiguous(tmp_path):
    """File modes are part of a Git tree; ZIP artifacts do not preserve them."""
    site = tmp_path / "site"
    site.mkdir()
    page = site / "index.html"
    page.write_text("<html>x</html>", encoding="utf-8")
    page.chmod(0o755)
    with pytest.raises(SystemExit) as excinfo:
        publish_site.subtree_identity(site)
    assert "executable" in str(excinfo.value)


def test_git_control_file_makes_identity_ambiguous(tmp_path):
    """.gitignore could silently omit published files from the identity."""
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("<html>x</html>", encoding="utf-8")
    (site / ".gitattributes").write_text("* text=auto\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        publish_site.subtree_identity(site)
