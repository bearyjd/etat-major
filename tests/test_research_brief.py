from pathlib import Path

import pytest

from etat_major.research_brief import write_brief
from etat_major.taskfile import TaskFileError

REF = "feature:netlens/0031"
FEATURE = "features/netlens/0031-latency-graph.md"


def _edit(workspace: Path, change: str) -> None:
    feature = workspace / FEATURE
    feature.write_text(feature.read_text().replace("status: planned", f"status: planned\n{change}"))


def test_brief_contains_only_allowed_context(workspace_dir, tmp_path):
    _edit(workspace_dir, 'research_questions: ["How do similar tools display latency?"]')
    feature = workspace_dir / FEATURE
    feature.write_text(feature.read_text() + "Internal feature notes must stay local.\n")
    out = tmp_path / "brief.md"
    write_brief(REF, workspace_dir, out)

    brief = out.read_text()
    for fragment in (
        "Live latency graph",
        "Users cannot see latency trends",
        "A graph of round-trip time",
        "How do similar tools display latency?",
        "Reddit",
        "GitHub",
        "documentation",
        "do not invent threads or citations; write not found instead",
    ):
        assert fragment in brief
    for fragment in ("Internal feature notes", "Latency.kt", "decision:0012", "research:0007"):
        assert fragment not in brief
    labels = [line.partition(":")[0] for line in brief.split("### F<n>\n")[1].splitlines()[:7]]
    assert labels == [
        "Claim",
        "Source URL",
        "Date",
        "Kind",
        "Evidence",
        "Conflicts",
        "Not verified",
    ]


@pytest.mark.parametrize(
    "sensitive",
    [
        "/" + "private" + "/workspace",
        "/",
        "C:" + chr(92) + "Program Files",
        "internal" + "." + "example",
        "内部" + chr(0x3002) + "系统",
        "ssh " + "worker-01",
        "C:" + chr(92),
        ".".join(("192", "0", "2", "1")),
        ":".join(("2001", "db8", "", "1")),
        "user" + "@" + "internal" + "." + "example",
        "g" + "hp_" + "x" * 36,
        "api" + "_key=" + "secret",
        "API key is " + "abc" + "123",
    ],
)
def test_refuses_to_write_sensitive_context(workspace_dir, tmp_path, sensitive):
    _edit(
        workspace_dir, f'research_questions: ["Review {sensitive.replace(chr(92), chr(92) * 2)}"]'
    )
    out = tmp_path / "brief.md"
    with pytest.raises(TaskFileError, match="redaction") as error:
        write_brief(REF, workspace_dir, out)
    assert sensitive not in str(error.value)
    assert not out.exists()


def test_existing_output_is_preserved_and_fallback_questions_are_present(workspace_dir, tmp_path):
    out = tmp_path / "brief.md"
    write_brief(REF, workspace_dir, out)
    brief = out.read_text()
    assert "## Questions\n" in brief
    assert "latency trends during a scan" in brief.split("## Questions\n", 1)[1]
    with pytest.raises(TaskFileError):
        write_brief(REF, workspace_dir, out)
    assert out.read_text() == brief


def test_symlinked_feature_is_rejected(workspace_dir, tmp_path):
    feature = workspace_dir / FEATURE
    outside = tmp_path / feature.name
    feature.rename(outside)
    feature.symlink_to(outside)
    out = tmp_path / "brief.md"
    with pytest.raises(TaskFileError):
        write_brief(REF, workspace_dir, out)
    assert not out.exists()


def test_cli_reports_feature_parse_field(workspace_dir, tmp_path, capsys):
    from etat_major.cli import main

    _edit(workspace_dir, "research_questions: 42")
    out = tmp_path / "brief.md"
    args = ["research", "brief", REF, "--workspace", str(workspace_dir), "--out", str(out)]
    assert main(args) != 0
    error = capsys.readouterr().err
    assert Path(FEATURE).name in error and "research_questions" in error
    assert str(tmp_path) not in error
    assert not out.exists()


def test_cli_blocks_redacted_brief_and_prints_safe_context(workspace_dir, tmp_path, capsys):
    from etat_major.cli import main

    sensitive = "sk-" + "short"
    _edit(workspace_dir, f'research_questions: ["Check {sensitive}"]')
    out = tmp_path / "brief.md"
    args = ["research", "brief", REF, "--workspace", str(workspace_dir), "--out", str(out)]
    assert main(args) != 0
    error = capsys.readouterr().err
    assert "redaction" in error and sensitive not in error
    assert not out.exists()


def test_brief_escapes_controls_and_html(workspace_dir, tmp_path):
    _edit(workspace_dir, r'research_questions: ["What does \u001b<em>latency mean?"]')
    out = tmp_path / "brief.md"
    write_brief(REF, workspace_dir, out)
    brief = out.read_text()
    assert r"\u001b" in brief and "\x1b" not in brief
    assert "&lt;em&gt;" in brief and "<em>" not in brief


def test_brief_error_does_not_echo_sensitive_field_name(workspace_dir, tmp_path):
    sensitive = "private" + "." + "worker"
    _edit(workspace_dir, f"{sensitive}: value")
    with pytest.raises(TaskFileError, match="frontmatter") as error:
        write_brief(REF, workspace_dir, tmp_path / "brief.md")
    assert sensitive not in str(error.value)
