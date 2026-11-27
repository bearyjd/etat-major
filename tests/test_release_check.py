"""The release check run by .github/workflows/release.yml."""

import os
import subprocess
import sys
from pathlib import Path
from runpy import run_path

import pytest

import etat_major

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/release_check.py"
DYNAMIC = """[project]
name = "etat-major"
dynamic = ["version"]

[tool.setuptools.dynamic]
version = { attr = "etat_major.__version__" }
"""
CHANGELOG = """# Changelog

Intro text.

## [1.2.3] - 2026-01-31

### Added

- A thing.

## [1.2.2] - 2026-01-01

- An older thing.
"""


@pytest.fixture(scope="module")
def script():
    return run_path(str(SCRIPT))


def make_repo(root: Path, *, pyproject=DYNAMIC, version="1.2.3", changelog=CHANGELOG) -> Path:
    (root / "src/etat_major").mkdir(parents=True)
    (root / "pyproject.toml").write_text(pyproject, encoding="utf-8")
    init = f'"""Package."""\n\n__version__ = "{version}"\n'
    (root / "src/etat_major/__init__.py").write_text(init, encoding="utf-8")
    (root / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    return root


def run_script(root: Path, tag: str | None, notes: Path):
    env = {key: value for key, value in os.environ.items() if key != "RELEASE_TAG"}
    if tag is not None:
        env["RELEASE_TAG"] = tag
    # -I -S: isolated and without site packages, so the script can only use the standard library.
    return subprocess.run(  # noqa: S603
        [sys.executable, "-I", "-S", str(SCRIPT), "--root", str(root), "--notes-out", str(notes)],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.mark.parametrize(
    ("tag", "version"), [("v0.2.0", "0.2.0"), ("v10.0.31", "10.0.31"), ("v1.0.0", "1.0.0")]
)
def test_release_tag_is_parsed(script, tag, version):
    assert script["parse_tag"](tag) == version


@pytest.mark.parametrize(
    "tag",
    [
        "",
        "v",
        "0.2.0",
        "V0.2.0",
        "v0.2",
        "v0.2.0.1",
        "v01.2.0",
        "v0.2.0-rc.1",
        "v0.2.0+build",
        " v0.2.0",
        "v0.2.0\n",
        "refs/tags/v0.2.0",
        "v١.٢.٣",
        "v1.0.0;rm",
        "v1.0.0$(id)",
        "v1.0.0`id`",
        "v1.0.0&&id",
        "v1.0.0|id",
        "v1.0.0'\"",
        "v1.0.0/../x",
    ],
    ids=repr,
)
def test_anything_else_is_refused(script, tag):
    with pytest.raises(script["ReleaseError"], match="vMAJOR.MINOR.PATCH"):
        script["parse_tag"](tag)


def test_matching_repository_returns_the_section(script, tmp_path):
    notes = script["check_release"](make_repo(tmp_path), "v1.2.3")
    assert notes == "### Added\n\n- A thing.\n"


def test_last_section_ends_at_end_of_file(script):
    assert script["release_notes"](CHANGELOG, "1.2.2") == "- An older thing.\n"


@pytest.mark.parametrize(
    ("changes", "tag", "named"),
    [
        ({}, "v1.2.4", "src/etat_major/__init__.py"),
        ({"version": "1.2.4"}, "v1.2.3", "src/etat_major/__init__.py"),
        (
            {"pyproject": '[project]\nname = "etat-major"\nversion = "1.2.4"\n'},
            "v1.2.3",
            "pyproject.toml",
        ),
        ({"pyproject": DYNAMIC.replace("__version__", "OTHER")}, "v1.2.3", "pyproject.toml"),
        ({"pyproject": '[project]\nname = "etat-major"\n'}, "v1.2.3", "pyproject.toml"),
        ({"pyproject": "not toml ["}, "v1.2.3", "pyproject.toml"),
        ({"version": '1.2.3"\n__version__ = "1.2.3'}, "v1.2.3", "__version__"),
        ({"version": '1.2.3" + "'}, "v1.2.3", "__version__"),
        ({"version": '1.2.3" ('}, "v1.2.3", "src/etat_major/__init__.py"),
        ({"version": '1.2.3"\nif True:\n    __version__ = "9'}, "v1.2.3", "__version__"),
        ({"version": '1.2.3"\n__version__ += "x'}, "v1.2.3", "__version__"),
        ({"version": '1.2.3"\n__version__: str = "9'}, "v1.2.3", "__version__"),
        ({"version": '1.2.3"\ndel __version__\nx = "'}, "v1.2.3", "__version__"),
        ({"version": '1.2.3"\nfrom os import sep as __version__\nx = "'}, "v1.2.3", "__version__"),
        ({"version": '1.2.3"\nfor __version__ in "9":\n    x = "'}, "v1.2.3", "__version__"),
        ({"version": '1.2.3"\ndef __version__():\n    return "9'}, "v1.2.3", "__version__"),
        ({"pyproject": 'project = "x"\n'}, "v1.2.3", "pyproject.toml"),
        ({"pyproject": "[project]\ndynamic = 1\n"}, "v1.2.3", "pyproject.toml"),
        ({"pyproject": 'tool = "x"\n[project]\ndynamic = ["version"]\n'}, "v1.2.3", "pyproject"),
        ({"pyproject": DYNAMIC.replace('dynamic = ["version"]\n', "")}, "v1.2.3", "pyproject.toml"),
        (
            {"pyproject": DYNAMIC.replace('["version"]', '["readme"]')},
            "v1.2.3",
            "pyproject.toml",
        ),
        ({"changelog": "# Changelog\n"}, "v1.2.3", "CHANGELOG.md"),
        (
            {"changelog": "## [1.2.4] - 2026-02-01\n\n- Newer.\n\n" + CHANGELOG},
            "v1.2.3",
            "top release",
        ),
    ],
)
def test_disagreement_is_refused(script, tmp_path, changes, tag, named):
    with pytest.raises(script["ReleaseError"]) as exc:
        script["check_release"](make_repo(tmp_path, **changes), tag)
    assert named in str(exc.value)


def test_static_pyproject_version_is_accepted_when_equal(script, tmp_path):
    static = '[project]\nname = "etat-major"\nversion = "1.2.3"\n'
    assert script["check_release"](make_repo(tmp_path, pyproject=static), "v1.2.3")


@pytest.mark.parametrize(
    ("changelog", "message"),
    [
        ("## [1.2.2] - 2026-01-01\n\n- Old.\n", "no section"),
        ("## [1.2.3] - unreleased\n\n- A thing.\n", "date"),
        ("## [1.2.3]\n\n- A thing.\n", "date"),
        ("## [1.2.3] - 2026-02-30\n\n- A thing.\n", "date"),
        ("## [1.2.3] - 20260131\n\n- A thing.\n", "date"),
        ("## [1.2.3] - 2026-01-31\n\n## [1.2.2] - 2026-01-01\n\n- Old.\n", "empty"),
        (CHANGELOG + "\n## [1.2.3] - 2026-01-31\n\n- Again.\n", "more than one"),
        ("## [1.2.3] - 2026-01-31 draft\n\n- A thing.\n", "date"),
        ("## [1.2.3] - 2026-01-31x\n\n- A thing.\n", "date"),
        ("## [1.2.3] - 2026-01-31\n\n### Added\n\n#### More\n", "empty"),
        ("## [1.2.3] - 2026-01-31\n\n- A thing.\n\n```\nopen\n", "never closed"),
        ("Write `## [1.2.3] - 2026-01-31` above.\n\n- A thing.\n", "no section"),
        ("## About ## [1.2.3] - 2026-01-31\n\n- A thing.\n", "no section"),
        ("```\n## [1.2.3] - 2026-01-31\n- An example.\n```\n", "no section"),
    ],
)
def test_unusable_changelog_section_is_refused(script, changelog, message):
    with pytest.raises(script["ReleaseError"], match=message):
        script["release_notes"](changelog, "1.2.3")


@pytest.mark.parametrize(
    "block",
    [
        "```\n## not a heading\n# nor this\n```",
        "~~~text\n## not a heading\n~~~",
        "````\n```\n## still fenced\n````",
        "```\n~~~\n## still fenced\n```",
        "```\n``` not a closer\n## still fenced\n```",
        "- Item:\n\n  ```sh\n## still fenced\n  ```",
        "    ## indented code",
        "##not-a-heading",
        "Text with ## in the middle.",
        "``` a`b\n- not a fence",
    ],
)
def test_text_that_is_not_a_heading_stays_in_the_notes(script, block):
    text = f"## [1.2.3] - 2026-01-31\n\n{block}\n\n- Last.\n\n## [1.2.2] - 2026-01-01\n"
    assert script["release_notes"](text, "1.2.3") == f"{block}\n\n- Last.\n"


@pytest.mark.parametrize(
    "heading", ["# Policy", "  ## Policy", "   # Policy", "##\tPolicy", "##", "#"], ids=repr
)
def test_section_ends_at_any_first_or_second_level_heading(script, heading):
    text = f"## [1.2.3] - 2026-01-31\n\n- A thing.\n\n{heading}\n\nNot notes.\n"
    assert script["release_notes"](text, "1.2.3") == "- A thing.\n"


def test_mentions_and_examples_of_a_heading_are_not_releases(script, tmp_path):
    preamble = "Head a section `## [9.9.9] - 2026-01-01`.\n\n```\n## [9.9.9] - 2026-01-01\n```\n\n"
    root = make_repo(tmp_path, changelog=preamble + CHANGELOG)
    assert script["check_release"](root, "v1.2.3") == "### Added\n\n- A thing.\n"


def test_windows_line_endings_are_read(script):
    text = CHANGELOG.replace("\n", "\r\n")
    assert script["release_notes"](text, "1.2.2") == "- An older thing.\n"


@pytest.mark.parametrize(
    "body",
    [
        "---",
        "***",
        "_ _ _",
        "- - -",
        "===",
        "  --  ",
        "<!-- nothing yet -->",
        "<!--\n- Draft only.\n-->",
        "<!-- a --> <!-- b -->",
        "[0.2.0]: https://example.invalid/v0.2.0",
        '[docs]: <./a b.md> "Title"',
        "### Added\n\n---\n\n<!-- soon -->\n\n[a]: b",
    ],
    ids=repr,
)
def test_a_section_with_nothing_to_read_is_empty(script, body):
    text = f"## [1.2.3] - 2026-01-31\n\n{body}\n\n## [1.2.2] - 2026-01-01\n\n- Old.\n"
    with pytest.raises(script["ReleaseError"], match="empty"):
        script["release_notes"](text, "1.2.3")


@pytest.mark.parametrize(
    "block",
    [
        "<!--\n## not a heading\n# nor this\n-->",
        "  <!-- opened\n## hidden --> trailing",
        "<!--\n```\n-->",
        "```\n<!--\n```",
        "<!-->",
        "Mention `<!--` in the middle.",
        "[Breaking]: removed a flag.",
        "<!-- note --> Visible words.",
    ],
    ids=repr,
)
def test_comments_neither_end_nor_empty_the_notes(script, block):
    text = f"## [1.2.3] - 2026-01-31\n\n{block}\n\n- Last.\n\n## [1.2.2] - 2026-01-01\n"
    assert script["release_notes"](text, "1.2.3") == f"{block}\n\n- Last.\n"


@pytest.mark.parametrize("line", ["<!-- note --> Visible words.", "[Breaking]: removed a flag."])
def test_readable_text_beside_markup_is_not_empty(script, line):
    text = f"## [1.2.3] - 2026-01-31\n\n{line}\n"
    assert script["release_notes"](text, "1.2.3") == f"{line}\n"


def test_a_commented_out_release_is_not_one(script, tmp_path):
    draft = "<!--\n## [9.9.9] - 2026-01-01\n\n- Draft.\n-->\n\n"
    root = make_repo(tmp_path, changelog=draft + CHANGELOG)
    assert script["check_release"](root, "v1.2.3") == "### Added\n\n- A thing.\n"
    with pytest.raises(script["ReleaseError"], match="no section"):
        script["release_notes"](draft + CHANGELOG, "9.9.9")


def test_an_unclosed_comment_is_refused(script):
    text = "## [1.2.3] - 2026-01-31\n\n- A thing.\n\n<!--\n## [1.2.2] - 2026-01-01\n"
    with pytest.raises(script["ReleaseError"], match="comment is never closed"):
        script["release_notes"](text, "1.2.3")


@pytest.mark.parametrize("name", ["pyproject.toml", "src/etat_major/__init__.py", "CHANGELOG.md"])
def test_missing_file_is_refused_without_an_absolute_path(script, tmp_path, name):
    root = make_repo(tmp_path)
    (root / name).unlink()
    with pytest.raises(script["ReleaseError"]) as exc:
        script["check_release"](root, "v1.2.3")
    assert name in str(exc.value) and str(tmp_path) not in str(exc.value)


def test_script_writes_the_notes(tmp_path):
    notes = tmp_path / "notes.md"
    done = run_script(make_repo(tmp_path / "repo"), "v1.2.3", notes)
    assert done.returncode == 0, done.stderr
    assert notes.read_text(encoding="utf-8") == "### Added\n\n- A thing.\n"


@pytest.mark.parametrize("tag", [None, "v9.9.9", "v1.0.0;rm", "v1.0.0$(touch pwned)"])
def test_script_fails_closed(tmp_path, tag):
    notes = tmp_path / "notes.md"
    done = run_script(make_repo(tmp_path / "repo"), tag, notes)
    assert done.returncode == 1
    assert done.stderr.startswith("release check: ")
    assert "Traceback" not in done.stderr and len(done.stderr.splitlines()) == 1
    assert done.stdout == "" and not notes.exists()


def test_script_refuses_a_malformed_pyproject_without_a_traceback(tmp_path):
    root = make_repo(tmp_path / "repo", pyproject='project = "x"\n')
    done = run_script(root, "v1.2.3", tmp_path / "notes.md")
    assert done.returncode == 1
    assert done.stderr.startswith("release check: pyproject.toml: ")
    assert "Traceback" not in done.stderr


def test_script_reports_an_unwritable_notes_file(tmp_path):
    done = run_script(make_repo(tmp_path / "repo"), "v1.2.3", tmp_path / "missing/notes.md")
    assert done.returncode == 1
    assert "notes.md" in done.stderr and "Traceback" not in done.stderr


def test_this_repository_agrees_once_its_section_is_dated(script, tmp_path):
    version = etat_major.__version__
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    dated = changelog.replace(f"## [{version}] - unreleased", f"## [{version}] - 2026-01-31")
    root = make_repo(
        tmp_path,
        pyproject=(ROOT / "pyproject.toml").read_text(encoding="utf-8"),
        version=version,
        changelog=dated,
    )
    assert script["check_release"](root, f"v{version}").strip()
