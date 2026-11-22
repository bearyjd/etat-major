import json
from types import SimpleNamespace

import pytest

from etat_major.cli import main
from etat_major.refs import Ref
from etat_major.render import render_trace
from etat_major.text_safety import safe
from etat_major.trace import (
    AcceptanceLine,
    ArchLine,
    Cite,
    DecisionLine,
    FindingLine,
    LinkLine,
    ResearchLine,
    Trace,
)


@pytest.mark.parametrize(
    ("char", "escaped"),
    [
        ("\u2028", r"\u2028"),
        ("\u2029", r"\u2029"),
        ("\ue000", r"\ue000"),
        ("\U000f0000", r"\U000f0000"),
        ("\ud800", r"\ud800"),
        ("\u0378", r"\u0378"),
    ],
)
def test_safe_escapes_nonprinting_unicode(char, escaped):
    assert safe(f"café{char}x") == f"café{escaped}x"


def test_trace_escapes_controls_in_dynamic_values():
    value = "é\x1b\n\t\r\x7f\x85\u202e\U000e0001"
    ref = Ref("fp:n", value)
    feature = SimpleNamespace(project=value, id=value, status=value, title=value, outcome=value)
    trace = Trace(
        feature=feature,
        research=(
            ResearchLine(
                ref, True, value, value, value, (FindingLine(value, value, value, False, value),)
            ),
        ),
        decisions=(DecisionLine(ref, value, True, value, value, value, (Cite(ref, value),)),),
        architecture=(ArchLine(ref, value, value, value),),
        acceptance=(AcceptanceLine(value, value, value, value),),
        links=(LinkLine(ref, value),),
        warnings=(value,),
    )

    rendered = render_trace(trace)
    escaped = r"é\u001b\u000a\u0009\u000d\u007f\u0085\u202e\U000e0001"
    assert rendered.count(escaped) == 31
    assert len(rendered.splitlines()) == 16


def test_cli_escapes_controls_in_unrecognized_argument(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["decisions", "list", "--workspace", ".", "--extra\x1b\n\u202e"])
    assert exc.value.code == 2
    assert r"--extra\u001b\u000a\u202e" in capsys.readouterr().err


def test_cli_escapes_controls_in_graph_error(capsys, workspace_dir, tmp_path):
    path = tmp_path / "invalid\x1b\n\u202e.json"
    path.write_text("{}")
    code = main(
        [
            "trace",
            "feature:netlens/0031",
            "--workspace",
            str(workspace_dir),
            "--graph",
            str(path),
        ]
    )
    assert code == 2
    assert r"invalid\u001b\u000a\u202e.json: missing 'schema'" in capsys.readouterr().err


def test_cli_escapes_controls_in_workspace_issue(capsys, workspace_dir):
    path = workspace_dir / "research/0099-bad\x1b\n\u202e.md"
    path.write_text("not frontmatter")
    code = main(["decisions", "list", "--workspace", str(workspace_dir)])
    assert code == 1
    error = capsys.readouterr().err
    assert "0099-bad" in error
    assert all(char not in error for char in "\x1b\u202e")
    assert len(error.splitlines()) == 1


def test_cli_decision_question_escapes_osc_and_bidi(capsys, workspace_dir):
    path = workspace_dir / "decisions/0012-add-latency-graph.md"
    text = path.read_text()
    question = json.dumps("Question\x1b]0;title\x07\u202e")
    path.write_text(text.replace("Should NetLens add a live latency graph?", question))
    assert main(["decisions", "list", "--workspace", str(workspace_dir)]) == 0
    out, err = capsys.readouterr()
    assert r"Question\u001b]0;title\u0007\u202e" in out
    assert all(char not in out for char in "\x1b\x07\u202e")
    assert err == ""
