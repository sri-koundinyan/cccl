"""Tests for the documentation site assembly.

These run against stubbed Sphinx output -- no Doxygen, no Sphinx, about a second
-- so the versioning behaviour can be exercised without a 19-minute build. That
matters because the failure modes here are all silent: a switcher that never
highlights the current page, an alias that serves the previous release, a
version listed but not published. None of them break a build.

Run directly, or via the pre-commit hook that runs them on every PR:

    pytest docs/test_publish_site.py
"""

import json
import os
import subprocess

import deploy_plan
import publish_site
import pytest
import release_version

# Note on naming: keep test function names off exactly 40 characters. Lob API
# test keys are literally "test_" followed by 35 characters, so the repo's
# trufflehog hook reports any 40-character test_* identifier as a verified
# secret. Four names in this file tripped it before this was understood.

# --------------------------------------------------------------------------
# Fixtures: synthetic published sites
# --------------------------------------------------------------------------


def make_version(root, name, *, stamp=None, label=None, index=True, pages=()):
    """Create a stand-in for one built version directory."""
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)

    if index:
        stamped = name if stamp is None else stamp
        marker = f"version_match = '{stamped}';" if stamped is not None else ""
        (directory / "index.html").write_text(
            f"<html><script>{marker}</script></html>", encoding="utf-8"
        )
        (directory / "pagelist.txt").write_text("/index.html,", encoding="utf-8")
        (directory / "404_helper.html").write_text(
            "<html>helper</html>", encoding="utf-8"
        )
        (directory / "objects.inv").write_text("inv", encoding="utf-8")

    for page in pages:
        page_path = directory / page
        page_path.parent.mkdir(parents=True, exist_ok=True)
        page_path.write_text("<html>page</html>", encoding="utf-8")

    if label is not None:
        (directory / publish_site.RELEASE_LABEL_FILE).write_text(
            label, encoding="utf-8"
        )

    return directory


def assemble(site_root, *extra):
    return publish_site.main([str(site_root), *extra])


def manifest(component_root):
    return json.loads((component_root / "nv-versions.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------


def test_directory_without_index_is_not_published(tmp_path):
    """A failed or partial upload must never be advertised in the switcher."""
    make_version(tmp_path, "unstable")
    make_version(tmp_path, "3.4", index=False)

    assert publish_site.discover_versions(tmp_path) == ["unstable"]


def test_non_version_dirs_ignored(tmp_path):
    make_version(tmp_path, "unstable")
    (tmp_path / "_static").mkdir()
    (tmp_path / "python").mkdir()
    (tmp_path / "3.4.2").mkdir()  # patch-level directories are not the scheme

    assert publish_site.discover_versions(tmp_path) == ["unstable"]


def test_versions_sort_numerically_with_the_tip_first(tmp_path):
    """Lexicographically "3.9" sorts after "3.10" and "4.0" lands wrong."""
    for name in ("3.9", "3.10", "4.0", "unstable", "3.4"):
        make_version(tmp_path, name)

    assert publish_site.discover_versions(tmp_path) == [
        "unstable",
        "4.0",
        "3.10",
        "3.9",
        "3.4",
    ]


# --------------------------------------------------------------------------
# Which version readers land on
# --------------------------------------------------------------------------


def test_latest_stable_is_the_highest_published_release(tmp_path):
    for name in ("unstable", "3.4", "3.10", "3.9"):
        make_version(tmp_path, name)
    versions = publish_site.discover_versions(tmp_path)

    assert publish_site.latest_stable("cpp", versions) == "3.10"


def test_no_release_published_means_no_latest_alias(tmp_path):
    """Stage 2 safety: with only the tip published, no reader's URL moves."""
    make_version(tmp_path, "unstable")

    assemble(tmp_path)

    assert publish_site.latest_stable("cpp", ["unstable"]) is None
    assert not (tmp_path / "latest").exists()
    assert "unstable/" in (tmp_path / "index.html").read_text(encoding="utf-8")


def test_publishing_a_release_promotes_it(tmp_path):
    make_version(tmp_path, "unstable")
    make_version(tmp_path, "3.4", label="3.4.2")

    assemble(tmp_path)

    assert (tmp_path / "latest" / "index.html").is_file()
    preferred = [e["version"] for e in manifest(tmp_path) if e["preferred"]]
    assert preferred == ["3.4"]


def test_override_pins_readers_to_an_older_release(tmp_path, monkeypatch):
    monkeypatch.setattr(publish_site, "LATEST_STABLE_OVERRIDE", {"cpp": "3.4"})
    for name in ("unstable", "3.4", "3.5"):
        make_version(tmp_path, name)
    versions = publish_site.discover_versions(tmp_path)

    assert publish_site.latest_stable("cpp", versions) == "3.4"


def test_override_naming_an_unpublished_version_degrades_safely(tmp_path, capsys):
    """It must fall back, not point readers at a directory that isn't there."""
    monkeypatch_target = {"cpp": "9.9"}
    original = publish_site.LATEST_STABLE_OVERRIDE
    publish_site.LATEST_STABLE_OVERRIDE = monkeypatch_target
    try:
        for name in ("unstable", "3.4"):
            make_version(tmp_path, name)
        versions = publish_site.discover_versions(tmp_path)
        assert publish_site.latest_stable("cpp", versions) == "3.4"
        assert "not published" in capsys.readouterr().err
    finally:
        publish_site.LATEST_STABLE_OVERRIDE = original


def test_site_root_never_targets_the_latest_alias(tmp_path):
    """The root must point at a real version directory, not at the stub tree."""
    make_version(tmp_path, "unstable")
    make_version(tmp_path, "3.4", label="3.4.2")

    assemble(tmp_path)

    root = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "url=latest/" not in root
    assert "3.4/" in root


# --------------------------------------------------------------------------
# Labels: the directory is the match key, the label is what readers see
# --------------------------------------------------------------------------


def test_release_label_is_displayed_but_not_matched_against(tmp_path):
    """This is what gives patch precision without a directory per patch."""
    make_version(tmp_path, "unstable")
    make_version(tmp_path, "3.4", label="3.4.2")

    assemble(tmp_path)

    entry = next(e for e in manifest(tmp_path) if e["version"] == "3.4")
    assert entry["name"] == "3.4.2"  # what the reader sees
    assert entry["version"] == "3.4"  # what version_match is compared against
    assert entry["url"].endswith("/3.4/")


def test_missing_label_falls_back_to_the_directory_name(tmp_path):
    make_version(tmp_path, "unstable")
    make_version(tmp_path, "3.4")

    assemble(tmp_path)

    entry = next(e for e in manifest(tmp_path) if e["version"] == "3.4")
    assert entry["name"] == "3.4"


# --------------------------------------------------------------------------
# The consistency check the switcher depends on
# --------------------------------------------------------------------------


def test_stamp_disagreeing_with_the_directory_fails_loudly(tmp_path):
    """Defect 2: pages stamped 3.6 while published at unstable/."""
    make_version(tmp_path, "unstable", stamp="3.6")

    with pytest.raises(SystemExit) as excinfo:
        assemble(tmp_path)

    message = str(excinfo.value)
    assert "version_match" in message
    assert "3.6" in message


def test_a_version_stamping_nothing_is_tolerated(tmp_path):
    """Releases predating the switcher stamp nothing; that is not an error."""
    make_version(tmp_path, "unstable")
    make_version(tmp_path, "3.4", stamp=None)
    (tmp_path / "3.4" / "index.html").write_text("<html>old</html>", encoding="utf-8")

    assemble(tmp_path)

    assert {e["version"] for e in manifest(tmp_path)} == {"unstable", "3.4"}


# --------------------------------------------------------------------------
# Components are independent
# --------------------------------------------------------------------------


def test_publishing_one_component_leaves_the_other_correct(tmp_path):
    """Deploying C++ must not strand the Python component's root files.

    On the fork this was a real bug: the assembler was told which component was
    built and could not see the other one, so a C++ deploy left /python/latest/
    pointing at whatever it had been before.
    """
    make_version(tmp_path, "unstable")
    make_version(tmp_path, "3.4", label="3.4.2")
    python_root = tmp_path / "python"
    make_version(python_root, "unstable")
    make_version(python_root, "1.1", label="1.1.1")

    assemble(tmp_path)

    # Now "rebuild" only C++ and reassemble, exactly as a main-branch deploy does.
    assemble(tmp_path)

    assert (python_root / "latest" / "index.html").is_file()
    assert (python_root / "index.html").is_file()
    python_preferred = [e["version"] for e in manifest(python_root) if e["preferred"]]
    assert python_preferred == ["1.1"]


def test_landing_page_appears_only_once_there_is_a_choice(tmp_path):
    make_version(tmp_path, "unstable")
    assemble(tmp_path)
    assert "refresh" in (tmp_path / "index.html").read_text(encoding="utf-8")

    make_version(tmp_path / "python", "1.1", label="1.1.1")
    assemble(tmp_path)
    root = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "python/1.1/" in root
    assert "C++" in root and "Python" in root


def test_component_with_nothing_published_is_not_linked(tmp_path):
    """Never link into a component directory that does not exist."""
    make_version(tmp_path, "unstable")
    make_version(tmp_path, "3.4", label="3.4.2")

    assemble(tmp_path)

    assert not (tmp_path / "python").exists()
    assert "python/" not in (tmp_path / "index.html").read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# The alias
# --------------------------------------------------------------------------


def test_latest_is_stubs_pointing_at_the_stable_release(tmp_path):
    make_version(tmp_path, "3.4", label="3.4.2", pages=("guide/deep.html",))

    assemble(tmp_path)

    stub = (tmp_path / "latest" / "guide" / "deep.html").read_text(encoding="utf-8")
    assert "../../3.4/guide/deep.html" in stub
    # The helper is a real copy: a stub would drop the query string carrying the
    # path the reader asked for.
    assert (tmp_path / "latest" / "404_helper.html").read_text(encoding="utf-8") == (
        "<html>helper</html>"
    )
    assert (tmp_path / "latest" / "pagelist.txt").is_file()


def test_latest_is_rebuilt_when_the_stable_release_changes(tmp_path):
    """Writing the alias only when its target is rebuilt is what made /latest/
    silently serve the previous release after a promotion."""
    make_version(tmp_path, "3.4", label="3.4.2")
    assemble(tmp_path)
    assert "3.4/index.html" in (tmp_path / "latest" / "index.html").read_text(
        encoding="utf-8"
    )

    make_version(tmp_path, "3.5", label="3.5.0")
    assemble(tmp_path)  # deploys nothing new; 3.5 simply exists now

    assert "3.5/index.html" in (tmp_path / "latest" / "index.html").read_text(
        encoding="utf-8"
    )


def test_root_objects_inv_tracks_the_stable_release(tmp_path):
    make_version(tmp_path, "unstable")
    (tmp_path / "unstable" / "objects.inv").write_text("tip", encoding="utf-8")
    make_version(tmp_path, "3.4", label="3.4.2")
    (tmp_path / "3.4" / "objects.inv").write_text("stable", encoding="utf-8")

    assemble(tmp_path)

    assert (tmp_path / "objects.inv").read_text(encoding="utf-8") == "stable"


# --------------------------------------------------------------------------
# The size guard
# --------------------------------------------------------------------------


def test_size_over_budget_fails_before_upload(tmp_path, monkeypatch):
    """Better an actionable error here than a rejected upload from Pages."""
    monkeypatch.setattr(publish_site, "SIZE_BUDGET_BYTES", 1024)
    make_version(tmp_path, "3.4", label="3.4.2")
    (tmp_path / "3.4" / "big.html").write_text("x" * 4096, encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        assemble(tmp_path)

    assert "budget" in str(excinfo.value)
    assert "Retire a version" in str(excinfo.value)


# --------------------------------------------------------------------------
# The 404 handler
# --------------------------------------------------------------------------


def test_routing_block_describes_what_is_published(tmp_path):
    make_version(tmp_path, "unstable")
    make_version(tmp_path, "3.4", label="3.4.2")
    make_version(tmp_path / "python", "1.1", label="1.1.1")

    assemble(tmp_path)

    rendered = (tmp_path / "404.html").read_text(encoding="utf-8")
    routing = json.loads(
        publish_site.ROUTING_BLOCK.search(rendered)
        .group(0)
        .split(">", 1)[1]
        .rsplit("<", 1)[0]
    )

    assert routing["sitePath"] == "/cccl/"
    assert routing["pythonPath"] == "python"
    assert routing["pythonDefault"] == "1.1"
    cpp = next(c for c in routing["components"] if c["path"] == "")
    assert cpp["default"] == "3.4"
    assert set(cpp["versions"]) == {"unstable", "3.4"}


# --------------------------------------------------------------------------
# Deriving the version from the source tree
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "encoded,expected",
    [
        (3004002, (3, 4, 2)),
        (3006000, (3, 6, 0)),
        (3010001, (3, 10, 1)),
        (4000000, (4, 0, 0)),
    ],
)
def test_cccl_version_decoding(encoded, expected):
    assert (
        release_version.parse_cccl_version(f"#define CCCL_VERSION {encoded}")
        == expected
    )


def make_checkout(tmp_path, encoded, version_md=None):
    header = tmp_path / release_version.VERSION_HEADER
    header.parent.mkdir(parents=True, exist_ok=True)
    header.write_text(f"#define CCCL_VERSION {encoded}\n", encoding="utf-8")
    if version_md is not None:
        md = tmp_path / release_version.VERSION_MD
        md.parent.mkdir(parents=True, exist_ok=True)
        md.write_text(version_md, encoding="utf-8")
    return tmp_path


def test_release_dir_and_label(tmp_path):
    checkout = make_checkout(tmp_path, 3004002, version_md="3.4\n")

    assert release_version.derive(checkout) == ("3.4", "3.4.2")


def test_development_tip_publishes_as_unstable(tmp_path):
    """main declares 3.6, but its docs are published at unstable/."""
    checkout = make_checkout(tmp_path, 3006000, version_md="3.6\n")

    assert release_version.derive(checkout, tip=True) == ("unstable", "")


def test_inconsistent_release_is_rejected(tmp_path):
    checkout = make_checkout(tmp_path, 3004002, version_md="3.5\n")

    with pytest.raises(SystemExit) as excinfo:
        release_version.derive(checkout)

    assert "must agree" in str(excinfo.value)


def test_missing_version_header_is_an_error(tmp_path):
    with pytest.raises(SystemExit) as excinfo:
        release_version.derive(tmp_path)

    assert "no such file" in str(excinfo.value)


# --------------------------------------------------------------------------
# The Python component versions independently of C++
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tag,expected",
    [
        ("python-1.1.1", (1, 1, 1)),
        ("python-0.7.0", (0, 7, 0)),
        ("python-1.10.2", (1, 10, 2)),
    ],
)
def test_python_tag_parsing(tag, expected):
    assert release_version.parse_python_tag(tag) == expected


@pytest.mark.parametrize("tag", ["v3.4.2", "python-1.1", "python-1.1.1-rc0", "1.1.1"])
def test_non_python_release_tags_are_rejected(tag):
    with pytest.raises(SystemExit):
        release_version.parse_python_tag(tag)


def test_python_version_comes_from_python_tags_not_cpp(tmp_path):
    """main's pyproject derives the package version from v[0-9]* -- the C++
    tags. The docs must version Python by Python's own releases regardless."""

    repo = tmp_path / "repo"
    repo.mkdir()
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
        "PATH": os.environ.get("PATH", ""),
    }

    def run(*args):
        return subprocess.run(args, cwd=repo, check=True, env=env, capture_output=True)

    run("git", "init", "-q")
    (repo / "f").write_text("x")
    run("git", "add", "-A")
    run("git", "commit", "-qm", "c")
    run("git", "tag", "v3.6.0")  # a C++ tag, which must be ignored
    run("git", "tag", "python-1.1.1")

    assert release_version.derive(repo, component="python") == ("1.1", "1.1.1")


def test_python_tip_publishes_as_unstable(tmp_path):
    assert release_version.derive(tmp_path, component="python", tip=True) == (
        "unstable",
        "",
    )


# --------------------------------------------------------------------------
# Retirement: the site is bounded, so releases age out automatically
# --------------------------------------------------------------------------


def test_oldest_releases_are_retired_beyond_the_keep_count(tmp_path, monkeypatch):
    monkeypatch.setitem(publish_site.KEEP_RELEASES, "cpp", 2)
    for name in ("unstable", "3.3", "3.4", "3.5"):
        make_version(tmp_path, name)

    assemble(tmp_path)

    assert (tmp_path / "3.5").is_dir()
    assert (tmp_path / "3.4").is_dir()
    assert not (tmp_path / "3.3").exists()  # oldest, retired
    assert (tmp_path / "unstable").is_dir()  # the tip never counts or retires


def test_retired_leave_switcher(tmp_path, monkeypatch):
    """The manifest must describe the site after retirement, not before."""
    monkeypatch.setitem(publish_site.KEEP_RELEASES, "cpp", 1)
    for name in ("unstable", "3.4", "3.5"):
        make_version(tmp_path, name)

    assemble(tmp_path)

    listed = {e["version"] for e in manifest(tmp_path)}
    assert listed == {"unstable", "3.5"}


def test_nothing_is_retired_below_the_keep_count(tmp_path, monkeypatch):
    monkeypatch.setitem(publish_site.KEEP_RELEASES, "cpp", 5)
    for name in ("unstable", "3.4", "3.5"):
        make_version(tmp_path, name)

    assemble(tmp_path)

    assert {p.name for p in tmp_path.iterdir() if p.is_dir()} >= {
        "unstable",
        "3.4",
        "3.5",
    }


def test_components_retire_independently(tmp_path, monkeypatch):
    """Python builds are tiny, so its history is kept far longer than C++'s."""
    monkeypatch.setitem(publish_site.KEEP_RELEASES, "cpp", 1)
    monkeypatch.setitem(publish_site.KEEP_RELEASES, "python", 3)
    for name in ("3.4", "3.5"):
        make_version(tmp_path, name)
    for name in ("1.0", "1.1", "1.2"):
        make_version(tmp_path / "python", name)

    assemble(tmp_path)

    assert not (tmp_path / "3.4").exists()
    assert {p.name for p in (tmp_path / "python").iterdir() if p.is_dir()} >= {
        "1.0",
        "1.1",
        "1.2",
    }


def test_retirement_cannot_remove_the_version_just_published(tmp_path, monkeypatch):
    """Publishing the newest release must never retire it as a side effect."""
    monkeypatch.setitem(publish_site.KEEP_RELEASES, "cpp", 1)
    for name in ("3.4", "3.5"):
        make_version(tmp_path, name)

    assemble(tmp_path)

    assert (tmp_path / "3.5" / "index.html").is_file()
    assert (
        publish_site.latest_stable("cpp", publish_site.discover_versions(tmp_path))
        == "3.5"
    )


# --------------------------------------------------------------------------
# A branch is not self-describing, so it must say what it publishes as
# --------------------------------------------------------------------------


def test_expected_version_must_match_the_tree(tmp_path):
    """The bogus 3.6: a branch off main carries main's version."""
    checkout = make_checkout(tmp_path, 3006000, version_md="3.6\n")

    with pytest.raises(SystemExit) as excinfo:
        release_version.derive(checkout, expect="3.4")

    assert "asked to publish as" in str(excinfo.value)
    assert "3.6" in str(excinfo.value)


def test_expected_version_matching_the_tree_is_accepted(tmp_path):
    checkout = make_checkout(tmp_path, 3004002, version_md="3.4\n")

    assert release_version.derive(checkout, expect="3.4") == ("3.4", "3.4.2")


def test_expect_is_ignored_for_the_tip(tmp_path):
    checkout = make_checkout(tmp_path, 3006000, version_md="3.6\n")

    assert release_version.derive(checkout, tip=True, expect="3.4") == ("unstable", "")


# --------------------------------------------------------------------------
# What a deploy publishes, and where
#
# This decides which component's documentation is published, from which ref,
# into which directory -- the highest-consequence decision in the deploy. It was
# bash embedded in YAML and accumulated three bugs there, each reproduced below.
# Calling plan() directly needs no git, no shell and no workflow runner.
# --------------------------------------------------------------------------

KNOWN_TAGS = {"v3.4.2", "v3.5.0-rc1", "v3.6.0.dev", "v3.4.2-ctk0", "python-1.1.1"}
KNOWN_BRANCHES = {"main", "branch/3.4.x", "docs-backfill-3.4"}


def fake_refs(ref):
    if ref in KNOWN_TAGS:
        return "tag"
    if ref in KNOWN_BRANCHES:
        return "branch"
    return None


def make_plan(event, **kwargs):
    return deploy_plan.plan(event, classify_ref=fake_refs, **kwargs)


def test_push_publishes_both_components():
    """One push advances both, so one deploy publishes both -- otherwise
    python/unstable goes stale and the STF docs, which exist only on main,
    are published nowhere."""
    result = make_plan("push")

    assert result["components"] == "cpp python"
    assert result["is_tip"] == "true"
    assert result["source_ref"] == "main"


def test_python_release_publishes_python():
    """Resolved after the release event sets the component, not before."""
    result = make_plan("release", release_tag="python-1.1.1")

    assert result["components"] == "python"
    assert result["source_ref"] == "python-1.1.1"


def test_cpp_release_publishes_cpp():
    assert make_plan("release", release_tag="v3.4.2")["components"] == "cpp"


def test_prerelease_is_not_published():
    with pytest.raises(SystemExit):
        make_plan("release", release_tag="v3.5.0-rc1", release_prerelease=True)


def test_branch_without_publish_as_is_rejected():
    with pytest.raises(SystemExit) as excinfo:
        make_plan("workflow_dispatch", component="cpp", source_ref="branch/3.4.x")

    assert "publish_as is required" in str(excinfo.value)


def test_branch_with_publish_as_sets_the_expectation():
    result = make_plan(
        "workflow_dispatch",
        component="cpp",
        source_ref="docs-backfill-3.4",
        publish_as="3.4",
    )

    assert result["expect"] == "3.4"
    assert result["is_tip"] == "false"


def test_branch_published_as_unstable_is_a_tip_build():
    result = make_plan(
        "workflow_dispatch",
        component="cpp",
        source_ref="branch/3.4.x",
        publish_as="unstable",
    )

    assert result["is_tip"] == "true"
    assert result["expect"] == ""


@pytest.mark.parametrize("tag", ["v3.5.0-rc1", "v3.6.0.dev", "v3.4.2-ctk0"])
def test_pre_release_tags_are_rejected(tag):
    with pytest.raises(SystemExit) as excinfo:
        make_plan("workflow_dispatch", component="cpp", source_ref=tag)

    assert "not a cpp release tag" in str(excinfo.value)


def test_components_cannot_borrow_each_others_tags():
    with pytest.raises(SystemExit) as excinfo:
        make_plan("workflow_dispatch", component="cpp", source_ref="python-1.1.1")
    assert "not a cpp release tag" in str(excinfo.value)

    with pytest.raises(SystemExit) as excinfo:
        make_plan("workflow_dispatch", component="python", source_ref="v3.4.2")
    assert "not a python release tag" in str(excinfo.value)


def test_production_cannot_be_targeted_by_typo():
    with pytest.raises(SystemExit) as excinfo:
        make_plan("workflow_dispatch", component="cpp", docs_branch="main")

    assert "gh-pages" in str(excinfo.value)


def test_all_publishes_both():
    result = make_plan("workflow_dispatch", component="all")

    assert result["components"] == "cpp python"
    assert result["is_tip"] == "true"


def test_all_refuses_a_release_ref():
    """A release belongs to one component, so 'all' cannot mean a tag."""
    with pytest.raises(SystemExit) as excinfo:
        make_plan("workflow_dispatch", component="all", source_ref="v3.4.2")

    assert "publishes both components from main" in str(excinfo.value)


def test_unknown_ref_is_rejected():
    with pytest.raises(SystemExit) as excinfo:
        make_plan("workflow_dispatch", component="cpp", source_ref="nope")

    assert "neither a tag nor a branch" in str(excinfo.value)


def test_component_paths_come_from_the_site_layout():
    """The workflow places builds using this plan, so a component's path is
    defined once -- in publish_site.COMPONENTS -- rather than repeated in YAML
    where the two could silently disagree."""
    planned = json.loads(make_plan("push")["component_plan"])
    by_id = {c["id"]: c for c in planned}

    for component in publish_site.COMPONENTS:
        assert by_id[component["id"]]["path"] == component["path"]
    assert by_id["cpp"]["build"] == "html"
    assert by_id["python"]["build"] == "python-html"


def test_pinned_version_survives_retirement(tmp_path, monkeypatch):
    """Retirement must not delete the version readers are pinned to.

    The override exists to hold people off a bad release; retiring its target
    would delete the safe version and move everyone onto the release they were
    being protected from.
    """
    monkeypatch.setitem(publish_site.KEEP_RELEASES, "cpp", 3)
    monkeypatch.setattr(publish_site, "LATEST_STABLE_OVERRIDE", {"cpp": "3.4"})
    for name in ("unstable", "3.4", "3.5", "3.6", "3.7"):
        make_version(tmp_path, name)

    assemble(tmp_path)

    assert (tmp_path / "3.4").is_dir()
    assert [e["version"] for e in manifest(tmp_path) if e["preferred"]] == ["3.4"]
    assert "3.4/index.html" in (tmp_path / "latest" / "index.html").read_text(
        encoding="utf-8"
    )


def test_retirement_still_runs_around_a_pin(tmp_path, monkeypatch):
    """Pinning one version must not disable retirement for the others."""
    monkeypatch.setitem(publish_site.KEEP_RELEASES, "cpp", 2)
    monkeypatch.setattr(publish_site, "LATEST_STABLE_OVERRIDE", {"cpp": "3.4"})
    for name in ("3.4", "3.5", "3.6", "3.7"):
        make_version(tmp_path, name)

    assemble(tmp_path)

    assert (tmp_path / "3.4").is_dir()  # pinned
    assert (tmp_path / "3.7").is_dir() and (tmp_path / "3.6").is_dir()
    assert not (tmp_path / "3.5").exists()  # retired normally


def test_a_label_cannot_claim_another_version(tmp_path):
    """The label is the only thing readers see that nothing else corroborates,
    so it must be consistent with the directory it describes."""
    make_version(tmp_path, "unstable")
    make_version(tmp_path, "3.4", label="9.9.9")

    with pytest.raises(SystemExit) as excinfo:
        assemble(tmp_path)

    assert "not a release of" in str(excinfo.value)


@pytest.mark.parametrize("label", ["3.4", "3.4.2", "3.4.10"])
def test_labels_in_the_line_are_accepted(tmp_path, label):
    make_version(tmp_path, "unstable")
    make_version(tmp_path, "3.4", label=label)

    assemble(tmp_path)

    entry = next(e for e in manifest(tmp_path) if e["version"] == "3.4")
    assert entry["name"] == label
