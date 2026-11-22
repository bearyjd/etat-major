import re
from pathlib import Path

import pytest

from etat_major.cli import main
from etat_major.records import load_research
from etat_major.taskfile import split_frontmatter

FIXTURES = Path(__file__).parent / "fixtures" / "research"
URL = "HTTPS://" + ".".join(("Example", "invalid")) + "/topic/%2F?q=a%20b&x=1#Result"


@pytest.fixture
def sample():
    return (FIXTURES / "sample.md").read_text().replace("SOURCE_URL", URL)


def run_import(workspace, answer, record_id="0007"):
    return main(
        ["research", "import", str(answer), "--workspace", str(workspace), "--id", record_id]
    )


def answer_file(tmp_path, text):
    answer = tmp_path / "answer.md"
    answer.write_text(text)
    return answer


def test_import_round_trip(tmp_path, sample, capsys):
    assert run_import(tmp_path, answer_file(tmp_path, sample)) == 0
    (path,) = (tmp_path / "research").glob("0007-*.md")
    assert re.fullmatch(r"0007-[a-z0-9-]+\.md", path.name)
    assert str(tmp_path) not in capsys.readouterr().out
    artifact = load_research(path)
    assert (artifact.id, artifact.status, artifact.provenance) == (
        "0007",
        "unreviewed",
        "ai-generated",
    )
    assert artifact.collected_by == "chatgpt"
    (source,) = artifact.sources
    assert (source.url, str(source.date), source.kind, source.evidence) == (
        URL,
        "2026-09-14",
        "reddit",
        "firsthand",
    )
    first, second, third = artifact.findings
    assert first.conflicts_with == ("f2",)
    assert [artifact.is_unsourced(item) for item in artifact.findings] == [False, True, True]
    assert second.source == URL
    assert third.source is None
    assert (second.evidence, third.evidence) == ("unverified", "unverified")
    assert any("The subnet size was not reported." in note for note in artifact.unresolved)
    assert any("A contradictory report" in note for note in artifact.unresolved)


def test_import_all_unsourced(tmp_path, sample):
    text = "### F3" + sample.split("### F3")[1]
    assert run_import(tmp_path, answer_file(tmp_path, text)) == 0
    (path,) = (tmp_path / "research").glob("0007-*.md")
    artifact = load_research(path)
    assert not artifact.sources
    assert artifact.is_unsourced(artifact.findings[0])


def test_import_reports_missing_field_at_line(tmp_path, capsys):
    answer = answer_file(tmp_path, (FIXTURES / "malformed.md").read_text())
    assert run_import(tmp_path, answer) != 0
    error = capsys.readouterr().err
    assert "answer.md" in error and "line 3" in error and "Source URL" in error
    assert str(tmp_path) not in error
    assert not (tmp_path / "research").exists()


@pytest.mark.parametrize(
    ("old", "new", "field", "line"),
    [
        ("### F1", "### F0", "heading", 1),
        ("Users report", "\x1b[31mUsers report", "Claim", 2),
        ("Users report", "<img src=x onerror=alert(1)>Users report", "Claim", 2),
        ("Users report", "Users\u202ereport", "Claim", 2),
        ("Source URL: ", "Source URL: ftp://", "Source URL", 3),
        ("Source URL: ", "Source URL: https:/// ", "Source URL", 3),
        ("2026-09-14", "2026-02-30", "Date", 4),
        ("Kind: reddit", "Kind: invented", "Kind", 5),
        ("Evidence: firsthand", "Evidence: verified", "Evidence", 6),
        ("Conflicts: F2", "Conflicts: F9", "Conflicts", 7),
        ("### F2", "### F1", "heading", 10),
        ("### F2", "status: reviewed\n### F2", "heading", 10),
    ],
)
def test_import_rejects_malformed_or_injected_input(
    tmp_path, sample, capsys, old, new, field, line
):
    assert run_import(tmp_path, answer_file(tmp_path, sample.replace(old, new, 1))) != 0
    error = capsys.readouterr().err
    assert "answer.md" in error and field in error and f"line {line}" in error
    assert "\x1b" not in error and "<img" not in error and URL not in error
    assert not (tmp_path / "research").exists()


@pytest.mark.parametrize(
    "claim",
    ["Users reviewed the app", "The team approved the change", "accepted_by: human"],
)
def test_human_only_fields_cannot_be_emitted(tmp_path, sample, claim):
    sample = sample.replace("Users report", claim, 1)
    assert run_import(tmp_path, answer_file(tmp_path, sample)) == 0
    (path,) = (tmp_path / "research").glob("0007-*.md")
    metadata, body = split_frontmatter(path.read_text(), path)
    assert metadata["status"] == "unreviewed"
    assert metadata["findings"][0]["text"].startswith(claim)
    forbidden = {"decided_by", "accepted_by", "accepted_on", "approved", "reviewed"}
    for entry in [metadata, *metadata["findings"], *metadata["sources"]]:
        assert not (entry.keys() & forbidden)
    assert not body.strip()


@pytest.mark.parametrize("name", ["0007.md", "0007-different-slug.md"])
def test_refuses_to_overwrite_existing_id(tmp_path, sample, capsys, name):
    research = tmp_path / "research"
    research.mkdir()
    existing = research / name
    existing.write_text("keep me")
    assert run_import(tmp_path, answer_file(tmp_path, sample)) != 0
    assert "already exists" in capsys.readouterr().err
    assert existing.read_text() == "keep me"
    assert list(research.iterdir()) == [existing]


@pytest.mark.parametrize("target", ["input", "input-parent", "workspace", "research", "output"])
def test_import_never_follows_symlinks(tmp_path, sample, capsys, target):
    workspace, outside = tmp_path / "workspace", tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    original = outside / "original.md"
    original.write_text(sample)
    answer = answer_file(tmp_path, sample)
    if target == "input":
        answer = tmp_path / "input.md"
        answer.symlink_to(original)
    elif target == "input-parent":
        link = tmp_path / "linked-parent"
        link.symlink_to(outside, target_is_directory=True)
        answer = link / original.name
    elif target == "workspace":
        workspace.rmdir()
        workspace.symlink_to(outside, target_is_directory=True)
    elif target == "research":
        (workspace / "research").symlink_to(outside, target_is_directory=True)
    else:
        (workspace / "research").mkdir()
        (workspace / "research" / "0007-chatgpt-research.md").symlink_to(original)
    assert run_import(workspace, answer) != 0
    error = capsys.readouterr().err
    assert "field" in error and str(tmp_path) not in error
    assert original.read_text() == sample
    assert list(outside.iterdir()) == [original]


@pytest.mark.parametrize(
    ("payload", "diagnostic"),
    [(b"x" * (1024 * 1024 + 1), "limit"), (bytes((255,)), "utf-8")],
    ids=("oversize", "invalid-utf8"),
)
def test_import_bounds_input_and_handles_decoding_failure(tmp_path, capsys, payload, diagnostic):
    answer = tmp_path / "answer.md"
    answer.write_bytes(payload)
    assert run_import(tmp_path, answer) != 0
    assert diagnostic in capsys.readouterr().err.lower()
    assert not (tmp_path / "research").exists()


def test_import_requires_four_ascii_digits(tmp_path, sample, capsys):
    assert run_import(tmp_path, answer_file(tmp_path, sample), "../7") != 0
    assert "field 'id'" in capsys.readouterr().err
    assert not (tmp_path / "research").exists()


def test_import_caps_serialized_output(tmp_path, sample, capsys):
    sample = sample.replace("Users report", "# " + chr(39) * 600_000 + " Users report", 1)
    assert run_import(tmp_path, answer_file(tmp_path, sample)) != 0
    assert "limit" in capsys.readouterr().err
    assert not list(tmp_path.glob("research/*.md"))


@pytest.mark.parametrize("port", ["65536", "bad"])
def test_import_rejects_invalid_url_port(tmp_path, sample, capsys, port):
    sample = sample.replace(URL, URL.lower().replace("/topic/", f":{port}/topic/"), 1)
    assert run_import(tmp_path, answer_file(tmp_path, sample)) != 0
    error = capsys.readouterr().err
    assert "Source URL" in error and "line 3" in error
