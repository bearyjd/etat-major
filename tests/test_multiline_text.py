"""Multi-line YAML values in view and export payloads, through the real loaders."""

import json
import re

import pytest

from etat_major.cli import main
from etat_major.planning_issues import planning_text, public_issue
from etat_major.text_safety import public_text, safe
from etat_major.workspace import Issue
from test_planning_web import client_for as client_for
from test_planning_web import planning_workspace as planning_workspace
from test_redaction import _MARKERS, CORPUS

FEATURE = "features/netlens/0031-latency-graph.md"
TASK = "tasks/netlens/0042-show-latency.md"
RESEARCH = "research/0007-android-network-tools.md"
DECISION = "decisions/0012-add-latency-graph.md"
COMPONENTS = "components/netlens.yaml"

# Double-quoted YAML, so that CR, NEL and the line separator reach the loader unchanged.
LINE = r'"\L\nLive\r\nlatency\tgraph\r## injected \u202E\e<script>alert(1)<x>\Ntail\N\n"'
LINE_OUT = (
    r"\u2028 Live latency graph ## injected \u202e\u001b<script>alert(1)<x>"
    r"\u0085tail\u0085"
)
PROSE = r'"one\r\ntwo\rthree\nfour\tfive\L\N\u202E\e<script>alert(2)<x>"'
PROSE_OUT = (
    "one\ntwo\nthree\nfour"
    r"\u0009five\u2028\u0085\u202e\u001b<script>alert(2)<x>"
)
BLOCK = "|\n  first line\n  second line\n"
BLOCK_OUT = "first line\nsecond line\n"
LITERAL_ESCAPES = ("\\u000a", "\\u000d")


def _set(workspace, name, field, value):
    """Replace one scalar field, keeping the rest of the real file."""
    path = workspace / name
    indent = r"(?P<lead>[ \t]*(?:- )?)"
    new, count = re.subn(
        rf"(?m)^{indent}{field}:.*$",
        lambda m: f"{m['lead']}{field}: {_indented(value, len(m['lead']))}",
        path.read_text(),
        count=1,
    )
    assert count == 1, field
    path.write_text(new)


def _indented(value, depth):
    if not value.startswith("|"):
        return value
    return value.rstrip("\n").replace("\n", "\n" + " " * depth)


@pytest.fixture
def hostile_workspace(planning_workspace):
    ws = planning_workspace
    for name, field, value in (
        (FEATURE, "title", LINE),
        (FEATURE, "outcome", PROSE),
        (TASK, "title", LINE),
        (RESEARCH, "title", LINE),
        (RESEARCH, "text", PROSE),
        (DECISION, "question", LINE),
        (DECISION, "chosen", PROSE),
        (DECISION, "rationale", BLOCK),
        (DECISION, "option", LINE),
        (DECISION, "why_not", PROSE),
    ):
        _set(ws, name, field, value)
    (ws / COMPONENTS).write_text(
        "version: 1\nproject: netlens\ncomponents:\n"
        f"  - id: core.network\n    label: {LINE}\n    kind: {LINE}\n    owner: {LINE}\n"
        f"    paths: [app/src/net/**]\n    summary:\n      text: {PROSE}\n"
        "      provenance: human\n"
    )
    return ws


def _export(kind, workspace, capsys, *flags):
    args = ["export", kind, "--json", "--workspace", str(workspace), "--project", "netlens"]
    assert main([*args, *map(str, flags)]) == 0, capsys.readouterr().err
    return json.loads(capsys.readouterr().out)


def _assert_planning(payload):
    [feature] = payload["features"]
    assert feature["title"] == LINE_OUT
    assert feature["outcome"] == PROSE_OUT
    assert next(t for t in payload["tasks"] if t["id"] == "netlens/0042")["title"] == LINE_OUT
    [component] = payload["components"]
    assert (component["label"], component["kind"], component["owner"]) == (LINE_OUT,) * 3
    assert component["summary"] == PROSE_OUT


def test_export_planning_keeps_prose_lines_and_flattens_single_line_fields(
    hostile_workspace, capsys
):
    _assert_planning(_export("planning", hostile_workspace, capsys))


def test_export_discover_keeps_prose_lines_and_flattens_single_line_fields(
    hostile_workspace, capsys
):
    payload = _export("discover", hostile_workspace, capsys)
    [research] = payload["research"]
    assert research["title"] == LINE_OUT
    assert research["findings"][0]["text"] == PROSE_OUT
    decision = next(d for d in payload["decisions"] if d["id"] == "0012")
    assert decision["question"] == LINE_OUT
    assert decision["chosen"] == PROSE_OUT
    assert decision["rationale"] == BLOCK_OUT
    assert decision["alternatives"] == [[LINE_OUT, PROSE_OUT]]


@pytest.mark.parametrize("style", [BLOCK, ">\n  first line\n  still first\n\n  second\n"])
def test_block_and_folded_scalars_reach_the_payload_as_text(planning_workspace, capsys, style):
    path = planning_workspace / FEATURE
    text = path.read_text()
    path.write_text(re.sub(r"(?m)^outcome:.*\n", f"outcome: {style}", text))
    outcome = _export("planning", planning_workspace, capsys)["features"][0]["outcome"]
    folded = "first line still first\nsecond\n"
    assert outcome == (BLOCK_OUT if style == BLOCK else folded)


def test_export_understand_keeps_summary_lines_and_flattens_labels(hostile_workspace, capsys):
    payload = _export("understand", hostile_workspace, capsys)
    [component] = payload["components"]
    assert (component["label"], component["kind"], component["owner"]) == (LINE_OUT,) * 3
    assert component["summary"] == PROSE_OUT


def test_project_json_and_pages_render_lines_as_escaped_text(hostile_workspace, client_for):
    with client_for(hostile_workspace) as client:
        _assert_planning(client.get("/project.json").json())
        planning = client.get("/planning").text
        discover = client.get("/discover").text
        selector = re.search(r'href="(\./understand\?component=[^"]+)"', planning)[1]
        understand = client.get(selector.replace("&amp;", "&").split("#")[0]).text
    for page in (planning, discover, understand):
        assert "<script" not in page
        assert "&lt;script&gt;alert(" in page
        assert "one\ntwo\nthree\nfour\\u0009five\\u2028" in page
        assert not any(escaped in page for escaped in LITERAL_ESCAPES)
    assert "Live latency graph ## injected \\u202e" in planning
    assert "first line\nsecond line" in discover


def test_manual_review_outcome_is_a_single_line(planning_workspace, client_for, tmp_path):
    review = tmp_path / "manual.yaml"
    review.write_text(
        "version: 1\nsource: manual-anthropic-api-review\ntask: netlens/0042\n"
        'ref: reports/review.md\nrecorded_at: "2026-11-22T14:00:00Z"\n'
        "outcome: |\n  completed\n  with notes\n"
        f"commit: '{'c' * 40}'\nreport_sha256: '{'a' * 64}'\n"
    )
    with client_for(planning_workspace, "--manual-review", review) as client:
        data = client.get("/project.json").json()
    assert data["manual_review"]["outcome"] == "completed with notes"


def test_issue_rows_are_single_lines():
    issue = public_issue(Issue("tasks/netlens/a.md", "bad\nfield", "first\r\n\tsecond\u2028"))
    assert (issue.field, issue.message) == ("bad field", r"first second\u2028")


def test_single_line_collapse_leaves_ordinary_spacing_alone():
    assert planning_text("  a  b \n c  ") == "a  b c"
    assert planning_text("\x0b\x0c\x1c\xa0a") == "\\u000b\\u000c\\u001c\xa0a"


@pytest.mark.parametrize("multiline", [False, True])
def test_limit_applies_after_line_handling(multiline):
    shown = planning_text("ab\r\ncd\x00", limit=6, multiline=multiline)
    assert shown == ("ab\ncd…" if multiline else "ab cd…")


def test_terminal_escaping_is_unchanged():
    assert safe("a\nb\r\tc") == r"a\u000ab\u000d\u0009c"


def test_a_written_escape_sequence_is_not_turned_into_a_line_break():
    text = r"the characters \u000a stay"
    assert planning_text(text, multiline=True, match_escaped=True) == text


_PROBES = [
    "Copy to box.invalid:\n/srv/S1x",
    "box.invalid:\nS1x",
    "Note:\nread/S1x",
    "box.invalid:\n  org/S1x",
    "a b.invalid:\tS1x",
    "git@h.invalid:\norg/S1x.git",
    "Plan B:\nS1x later",
]


def _broken_variants():
    for value, _ in [*CORPUS, *((probe, None) for probe in _PROBES)]:
        yield value
        for match in re.finditer(r"[:@/ ,]", value):
            for gap in ("\n", "\t", "\r\n", "\r", "\x85", "\u2028"):
                variant = value[: match.end()] + gap + value[match.end() :]
                # Short enough that the 512 character cut never decides the outcome.
                if len(variant) < 80:
                    yield variant


def _old(value):
    return safe(public_text(value, scp_remotes=True), limit=512)


@pytest.mark.parametrize("multiline", [False, True])
def test_no_payload_shows_what_the_earlier_escaping_hid(multiline):
    for value in _broken_variants():
        once = planning_text(value, multiline=multiline)
        discover = planning_text(value, multiline=multiline, match_escaped=True)
        page = planning_text(discover, multiline=True)
        for marker in _MARKERS:
            assert marker not in once or marker in _old(value), value
            for shown in (discover, page):
                assert marker not in shown or marker in _old(_old(value)), value


def test_research_brief_writes_each_value_on_one_line(workspace_dir, tmp_path, capsys):
    _set(workspace_dir, FEATURE, "title", LINE)
    _set(workspace_dir, FEATURE, "outcome", BLOCK)
    out = tmp_path / "brief.md"
    args = ["research", "brief", "feature:netlens/0031", "--workspace", str(workspace_dir)]
    assert main([*args, "--out", str(out)]) == 0, capsys.readouterr().err
    brief = out.read_text()
    assert "- Desired outcome: first line second line\n" in brief
    assert "\n## injected" not in brief and "<script" not in brief
    assert not any(escaped in brief for escaped in LITERAL_ESCAPES)


def test_research_brief_checks_the_joined_line_for_secrets(workspace_dir, tmp_path, capsys):
    _set(workspace_dir, FEATURE, "outcome", r'"the api\nkey: abc123"')
    out = tmp_path / "brief.md"
    args = ["research", "brief", "feature:netlens/0031", "--workspace", str(workspace_dir)]
    assert main([*args, "--out", str(out)]) == 2
    assert "outcome" in capsys.readouterr().err
    assert not out.exists()
