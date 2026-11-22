import json
from pathlib import Path

import jsonschema
import pytest

from etat_major.taskfile import (
    TaskFileError,
    parse_initiative,
    parse_project,
    parse_task,
    split_frontmatter,
)

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((ROOT / "docs/contracts/task-file.schema.json").read_text())

GOOD = """---
id: 0042
title: Schema mapper for the example service
initiative: example-initiative
project: example-service
owner: alice
status: ready
priority: 2
acceptance:
  - Maps all source tables
  - Unit tests pass in CI
budget_tokens: 400000
evidence:
  - kind: pr
    ref: example-org/example-service#12
---
Free-form description.
"""


def task(tmp_path, text=GOOD, name="0042-schema-mapper.md"):
    p = tmp_path / "tasks" / "example-service" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def sub(old, new):
    assert old in GOOD
    return GOOD.replace(old, new)


def test_parse_good_task(tmp_path):
    t = parse_task(task(tmp_path))
    assert t.id == "0042"
    assert t.owner == "alice"
    assert t.status == "ready"
    assert t.acceptance == ("Maps all source tables", "Unit tests pass in CI")
    assert t.evidence[0].kind == "pr"
    assert t.body.strip() == "Free-form description."
    assert t.warnings == ()


def test_task_is_immutable(tmp_path):
    t = parse_task(task(tmp_path))
    with pytest.raises(Exception):  # noqa: B017
        t.status = "done"


@pytest.mark.parametrize("status", ["running", "needs-you", "review", "failed"])
def test_derived_status_rejected_with_file_and_field(tmp_path, status):
    p = task(tmp_path, sub("status: ready", f"status: {status}"))
    with pytest.raises(TaskFileError) as e:
        parse_task(p)
    msg = str(e.value)
    assert p.name in msg and "status" in msg and "derived" in msg
    assert e.value.field == "status"


@pytest.mark.parametrize("status", ["draft", "ready", "blocked", "done"])
def test_intent_status_accepted(tmp_path, status):
    assert parse_task(task(tmp_path, sub("status: ready", f"status: {status}"))).status == status


def test_unknown_status_rejected(tmp_path):
    with pytest.raises(TaskFileError, match="status"):
        parse_task(task(tmp_path, sub("status: ready", "status: wip")))


def test_id_must_match_filename_prefix(tmp_path):
    p = task(tmp_path, name="0043-other.md")
    with pytest.raises(TaskFileError) as e:
        parse_task(p)
    assert e.value.field == "id"
    assert "0043-other.md" in str(e.value)


def test_unquoted_leading_zero_id_stays_string(tmp_path):
    assert parse_task(task(tmp_path)).id == "0042"


def test_integer_id_without_padding_matches_filename(tmp_path):
    p = task(tmp_path, sub("id: 0042", "id: 42"), name="42-x.md")
    assert parse_task(p).id == "42"


@pytest.mark.parametrize("field", ["id", "title", "initiative", "project", "owner", "status"])
def test_missing_required_field(tmp_path, field):
    lines = [x for x in GOOD.splitlines(True) if not x.startswith(field + ":")]
    with pytest.raises(TaskFileError) as e:
        parse_task(task(tmp_path, "".join(lines)))
    assert e.value.field == field


def test_owner_must_be_single_string(tmp_path):
    with pytest.raises(TaskFileError) as e:
        parse_task(task(tmp_path, sub("owner: alice", "owner: [alice, bob]")))
    assert e.value.field == "owner"


def test_unknown_field_rejected(tmp_path):
    with pytest.raises(TaskFileError) as e:
        parse_task(task(tmp_path, sub("priority: 2", "priority: 2\nsession: abc")))
    assert e.value.field == "session"


def test_bad_budget_and_priority(tmp_path):
    with pytest.raises(TaskFileError) as e:
        parse_task(task(tmp_path, sub("budget_tokens: 400000", "budget_tokens: -1")))
    assert e.value.field == "budget_tokens"
    with pytest.raises(TaskFileError) as e:
        parse_task(task(tmp_path, sub("priority: 2", "priority: high")))
    assert e.value.field == "priority"


def test_bad_evidence_kind(tmp_path):
    with pytest.raises(TaskFileError) as e:
        parse_task(task(tmp_path, sub("kind: pr", "kind: vibes")))
    assert e.value.field == "evidence.0.kind"


def test_acceptance_must_be_list_of_strings(tmp_path):
    text = sub(
        "acceptance:\n  - Maps all source tables\n  - Unit tests pass in CI\n",
        "acceptance: just text\n",
    )
    with pytest.raises(TaskFileError) as e:
        parse_task(task(tmp_path, text))
    assert e.value.field == "acceptance"


def test_optional_fields_default(tmp_path):
    text = "---\nid: 0042\ntitle: t\ninitiative: i\nproject: p\nowner: alice\nstatus: draft\n---\n"
    t = parse_task(task(tmp_path, text))
    assert t.acceptance == () and t.evidence == ()
    assert t.priority is None and t.budget_tokens is None


def test_missing_or_unclosed_frontmatter(tmp_path):
    for text in ["no frontmatter", "---\nid: 1\n"]:
        with pytest.raises(TaskFileError, match="frontmatter"):
            parse_task(task(tmp_path, text))


def test_invalid_yaml(tmp_path):
    with pytest.raises(TaskFileError, match="YAML"):
        parse_task(task(tmp_path, "---\nid: [\n---\n"))


def test_frontmatter_must_be_mapping(tmp_path):
    with pytest.raises(TaskFileError, match="mapping"):
        parse_task(task(tmp_path, "---\n- a\n---\n"))


def test_unreadable_file(tmp_path):
    with pytest.raises(TaskFileError, match="read"):
        parse_task(tmp_path / "0042-missing.md")


def test_native_backlog_drafts_folder_rejected(tmp_path):
    p = tmp_path / "backlog" / "drafts" / "0042-x.md"
    p.parent.mkdir(parents=True)
    p.write_text(GOOD)
    with pytest.raises(TaskFileError, match="drafts"):
        parse_task(p)


@pytest.mark.parametrize(
    "body",
    [
        "<script>alert(1)</script>",
        "hello <img src=x onerror=alert(1)>",
        "<div>raw</div>",
        "[x](javascript:alert(1))",
        "<iframe src='x'></iframe>",
    ],
)
def test_html_in_body_is_flagged(tmp_path, body):
    t = parse_task(task(tmp_path, sub("Free-form description.", body)))
    assert t.warnings and "line" in t.warnings[0]


@pytest.mark.parametrize(
    "body",
    [
        "plain `<div>` in code",
        "```html\n<script>x</script>\n```",
        "see <https://example.org>",
        "a < b and c > d",
    ],
)
def test_safe_body_not_flagged(tmp_path, body):
    assert parse_task(task(tmp_path, sub("Free-form description.", body))).warnings == ()


def test_split_frontmatter():
    meta, body = split_frontmatter("---\na: 1\n---\nbody\n", Path("x.md"))
    assert meta == {"a": 1} and body == "body\n"


INIT = """---
id: example-initiative
title: Example outcome
owner: alice
target_date: 2027-03-01
outcome: Ship the example service
---
Notes
"""
PROJ = """---
id: example-service
title: Example service
initiative: example-initiative
owner: alice
repo: example-service
---
"""


def test_parse_initiative(tmp_path):
    p = tmp_path / "example-initiative.md"
    p.write_text(INIT)
    i = parse_initiative(p)
    assert i.target_date.isoformat() == "2027-03-01" and i.owner == "alice"


def test_initiative_id_must_match_stem(tmp_path):
    p = tmp_path / "other.md"
    p.write_text(INIT)
    with pytest.raises(TaskFileError) as e:
        parse_initiative(p)
    assert e.value.field == "id"


def test_parse_project(tmp_path):
    p = tmp_path / "example-service.md"
    p.write_text(PROJ)
    assert parse_project(p).initiative == "example-initiative"


def test_project_missing_initiative(tmp_path):
    p = tmp_path / "example-service.md"
    p.write_text(PROJ.replace("initiative: example-initiative\n", ""))
    with pytest.raises(TaskFileError) as e:
        parse_project(p)
    assert e.value.field == "initiative"


def test_schema_is_valid_and_agrees_with_parser(tmp_path):
    jsonschema.Draft202012Validator.check_schema(SCHEMA)
    v = jsonschema.Draft202012Validator(SCHEMA)
    meta, _ = split_frontmatter(GOOD, Path("x.md"))
    assert not list(v.iter_errors(json.loads(json.dumps(meta, default=str))))
    for status in ["running", "needs-you", "review", "failed"]:
        assert list(v.iter_errors({**json.loads(json.dumps(meta, default=str)), "status": status}))
    assert list(v.iter_errors({"id": "0042"}))


@pytest.mark.parametrize(
    ("text", "field"),
    [
        (sub("status: ready\n", "status: running\nstatus: ready\n"), "status"),
        (sub("owner: alice\n", "owner: alice\nowner: bob\n"), "owner"),
        (sub("    ref: example-org", "    kind: release\n    ref: example-org"), "kind"),
    ],
    ids=["derived-status-masked", "owner", "nested"],
)
def test_duplicate_key_rejected(tmp_path, text, field):
    with pytest.raises(TaskFileError) as e:
        parse_task(task(tmp_path, text))
    assert e.value.field == field
    assert "duplicate" in str(e.value)


@pytest.mark.parametrize(
    "text",
    [
        sub("status: ready\n", "<<: {status: running}\nstatus: ready\n"),
        sub("id: 0042\n", "id: 0042\n<<: &base {status: running}\n"),
        sub("    ref: example-org", "    <<: {kind: bogus}\n    ref: example-org"),
    ],
    ids=["derived-status-masked", "anchored", "nested"],
)
def test_yaml_merge_key_rejected(tmp_path, text):
    with pytest.raises(TaskFileError) as e:
        parse_task(task(tmp_path, text))
    assert e.value.field == "<<"
    assert "merge" in str(e.value)


@pytest.mark.parametrize(
    ("body", "lines"),
    [
        ("intro\n\n<div\nclass=x>\nraw\n</div>", [3]),
        ("intro\nhello <img\nsrc=x\nonerror=alert(1)> and\n<b>bold</b>", [2, 5]),
        ("``` a`b\n<script>alert(1)</script>\n```", [2]),
        ("````\n```\n<script>alert(1)</script>\n````\n\n<p>out</p>", [6]),
        ("~~~\n~~~ not a closer\n<script>alert(1)</script>\n~~~", []),
        ("`code\n<b>` then\n<i>real</i>", [3]),
        ("> quoted\n> <span>x</span>", [2]),
        ("one\n[x](javascript:alert(1))\n![y](data:text/html,z)\n<vbscript:x>", [2, 3, 4]),
        ("[x][r]\n\n[r]: JavaScript:alert(1)", [1]),
    ],
    ids=[
        "multiline-block-tag",
        "multiline-inline-tag",
        "backtick-in-info-is-not-a-fence",
        "shorter-run-does-not-close",
        "closer-with-info-does-not-close",
        "multiline-code-span",
        "blockquote",
        "script-urls",
        "reference-link",
    ],
)
def test_markup_warnings_name_exact_source_lines(tmp_path, body, lines):
    t = parse_task(task(tmp_path, sub("Free-form description.", body)))
    assert t.warnings == tuple(f"line {n}: raw HTML or script markup in body" for n in lines)
