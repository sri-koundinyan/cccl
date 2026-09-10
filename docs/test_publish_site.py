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

import publish_site
import pytest
import release_version

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
    import subprocess

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
