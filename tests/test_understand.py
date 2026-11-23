from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from test_planning_web import Page
from test_planning_web import client_for as client_for
from test_planning_web import planning_workspace as planning_workspace

TRAIL = Path(__file__).parent / "fixtures/trail/wiring-kotlin.json"


def links(html, level):
    return [
        href
        for href in Page(html).hrefs
        if href.startswith("./understand?") and level in parse_qs(urlsplit(href).query)
    ]


def test_recorded_inspector(client_for, planning_workspace):
    client = client_for(planning_workspace, "--trail", TRAIL)
    page = client.get("/understand")
    assert page.status_code == 200
    assert "Floorplan: missing" in page.text and "Trail: present" in page.text
    components = links(page.text, "component")
    files = next(items for href in components if (items := links(client.get(href).text, "file")))
    symbols = links(client.get(files[0]).text, "symbol")
    assert symbols
    inspector = client.get(symbols[0])
    assert "Callers" in inspector.text and "Callees" in inspector.text
    assert "immutable" in inspector.text
    assert "understand" not in client.get("/project.json").json()


def test_bad_selection(client_for, planning_workspace):
    response = client_for(planning_workspace).get("/understand?file=outside")
    assert response.status_code == 400
    assert "outside" not in response.text


@pytest.mark.parametrize("case", ["parent", "leaf", "escape", "oversize", "span", "encoding"])
def test_excerpt_rejects(tmp_path, case):
    from etat_major.trail import Symbol
    from etat_major.understand import excerpt

    folder = tmp_path / "dir"
    folder.mkdir()
    path = folder / "code"
    path.write_text("one\n")
    relative = "dir/code"
    if case == "escape":
        relative = "../dir/code"
    elif case == "parent":
        (tmp_path / "alias").symlink_to(folder)
        relative = "alias/code"
    elif case == "leaf":
        (folder / "alias").symlink_to(path)
        relative = "dir/alias"
    elif case == "oversize":
        path.write_bytes(b"x" * 262145)
    elif case == "encoding":
        path.write_bytes(b"\xff")
    symbol = Symbol("key", "method", relative, 1, 2 if case == "span" else 1)
    body, note = excerpt(tmp_path, "fresh", symbol)
    assert not body and note.startswith("source.")
    assert str(tmp_path) not in note


def test_excerpt_limits(tmp_path):
    from etat_major.trail import Symbol
    from etat_major.understand import excerpt

    (tmp_path / "code").write_text("<b>\x1b /private/path\n" + ("é" * 200 + "\n") * 80)
    symbol = Symbol("key", "method", "code", 1, 81)
    text, note = excerpt(tmp_path, "fresh", symbol)
    assert "truncated" in note and len(text.encode()) <= 8192
    assert len(text.splitlines()) <= 40 and "/private/path" not in text
    assert "\x1b" not in text
    assert not excerpt(tmp_path, "unknown", symbol)[0]


def test_selection_rejected_before_source_read(client_for, planning_workspace, monkeypatch):
    from etat_major import understand_html

    def unexpected(*_args):
        pytest.fail("excerpt was read before membership validation")

    monkeypatch.setattr(understand_html, "excerpt", unexpected)
    client = client_for(planning_workspace, "--trail", TRAIL)
    components = links(client.get("/understand").text, "component")
    files = next(items for href in components if (items := links(client.get(href).text, "file")))
    params = parse_qs(urlsplit(files[0]).query)
    wrong = next(
        c
        for href in components
        if (c := parse_qs(urlsplit(href).query)["component"]) != params["component"]
    )
    from urllib.parse import urlencode

    url = "/understand?" + urlencode(params | {"component": wrong}, doseq=True)
    assert client.get(url).status_code == 400


def test_missing_configured_and_invalid_artifacts(client_for, planning_workspace, tmp_path):
    invalid = tmp_path / "invalid"
    invalid.write_text("{}")
    page = client_for(planning_workspace, "--graph", tmp_path / "absent", "--trail", invalid).get(
        "/understand"
    )
    assert "Floorplan: missing" in page.text and "Trail: invalid" in page.text
    assert "File coverage unavailable" in page.text and "core.network" in page.text


def test_capped_page_keeps_selection_and_snapshot_labels(
    client_for, planning_workspace, monkeypatch
):
    from etat_major import understand_html

    client = client_for(planning_workspace, "--trail", TRAIL)
    link = links(client.get("/understand").text, "component")[-1]
    monkeypatch.setattr(understand_html, "LIMIT", 2500)
    html = client.get(link).text
    assert "Narrow the selection" in html and "Trail: present" in html
    assert urlsplit(link).fragment in Page(html).ids
    assert len(html.encode()) <= 2500


def test_tokens_bound_surrogate_and_fail_closed_on_collision(planning_workspace, monkeypatch):
    from etat_major import understand
    from etat_major.planning_view import PlanningInputs, load_planning_view
    from etat_major.taskfile import TaskFileError

    assert understand.token("file", "raw\ud800") != understand.token("symbol", "raw\ud800")
    monkeypatch.setattr(understand, "token", lambda *args: "same")
    with pytest.raises(TaskFileError, match="selection"):
        load_planning_view(PlanningInputs(planning_workspace, "netlens"))


def test_recorded_call_endpoints_and_freshness(client_for, planning_workspace, tmp_path):
    import json

    from etat_major.understand import token

    data = json.loads(TRAIL.read_text())
    extracted = next(
        e for e in data["edges"] if e["relation"] == "calls" and e["confidence"] == "extracted"
    )
    inferred = next(
        e
        for e in data["edges"]
        if e["relation"] == "calls"
        and e["confidence"] == "inferred"
        and e["target"] == extracted["target"]
    )
    data["nodes"] = [n for n in data["nodes"] if n["id"] != inferred["source"]]
    recording = tmp_path / "trimmed.json"
    recording.write_text(json.dumps(data))
    revision = "a" * 40
    client = client_for(
        planning_workspace,
        "--trail",
        recording,
        "--trail-revision",
        revision,
        "--source-revision",
        "b" * 40,
        "--immutable-source",
        tmp_path,
    )
    key = extracted["target"]
    params = {
        "component": token("component", "root"),
        "file": token("file", key.split("#")[0]),
        "symbol": token("symbol", key),
    }
    body = client.get("/understand", params=params).text
    callers = body.split('id="list-callers"', 1)[1].split("</section>", 1)[0]
    assert "verified · confidence extracted" in callers
    assert extracted["source"] in callers
    assert "unresolved · inferred · confidence inferred" in callers
    assert inferred["source"] in callers
    assert "source.revision" in body and f"stale · snapshot {revision}" in body
    assert token("symbol", inferred["source"]) not in Page(callers).hrefs


def test_deferred_symbol_link_includes_correct_page(client_for, planning_workspace):
    import json

    from etat_major.understand import token

    recorded = TRAIL.with_name("wiring.json")
    data = json.loads(recorded.read_text())
    path = "tests/test_taskfile.py"
    symbols = sorted(n["id"] for n in data["nodes"] if n["path"] == path)
    client = client_for(planning_workspace, "--trail", recorded)
    page = client.get(
        "/understand",
        params={"component": token("component", "root"), "file": token("file", path), "symbols": 2},
    )
    section = page.text.split('id="list-symbols"', 1)[1].split("</section>", 1)[0]
    assert "34 total · page 2 of 2" in section and "Previous symbols" in section
    link = links(section, "symbol")[0]
    params = parse_qs(urlsplit(link).query)
    assert params["symbols"] == ["2"] and params["symbol"] == [token("symbol", symbols[25])]
    assert urlsplit(link).fragment in Page(client.get(link).text).ids


def test_no_partial_private_location_at_byte_boundary(tmp_path):
    from etat_major.trail import Symbol
    from etat_major.understand import excerpt

    (tmp_path / "code").write_text("x" * 8175 + " git@private-host:secret/project")
    body, note = excerpt(tmp_path, "fresh", Symbol("key", "method", "code", 1, 1))
    assert "private-host" not in body and "truncated" in note


def test_unmatchable_floorplan_file_remains_navigable(client_for, planning_workspace, tmp_path):
    import json

    from test_planning_web import GRAPH

    graph = json.loads(GRAPH.read_text())
    graph["files"][0]["p"] = "build/100%.kt"
    recording = tmp_path / "graph.json"
    recording.write_text(json.dumps(graph))
    client = client_for(planning_workspace, "--graph", recording)
    main = client.get("/understand").text
    link = next(
        link
        for link in links(main, "component")
        if "Unowned files"
        in client.get(link).text.split('<h2 tabindex="-1"', 1)[-1].split("</section>")[0]
    )
    page = client.get(link).text
    assert "build/100%.kt" in page
    assert all("100%" not in href for href in Page(page).hrefs)


def test_capped_symbol_preserves_excerpt_reason(client_for, planning_workspace, monkeypatch):
    from etat_major import understand_html

    client = client_for(planning_workspace, "--trail", TRAIL)
    components = links(client.get("/understand").text, "component")
    files = next(items for href in components if (items := links(client.get(href).text, "file")))
    symbol = links(client.get(files[0]).text, "symbol")[0]
    monkeypatch.setattr(understand_html, "LIMIT", 3000)
    body = client.get(symbol).text
    assert "Narrow the selection" in body and "source.root" in body


def test_old_view_omits_unavailable_inspector(planning_workspace):
    from dataclasses import replace

    from etat_major.planning_html import render
    from etat_major.planning_view import PlanningInputs, load_planning_view

    view = load_planning_view(PlanningInputs(planning_workspace, "netlens"))
    assert "./understand" not in render(replace(view, _understand=None))


def test_snapshot_compiles_component_patterns_once(planning_workspace, monkeypatch):
    from etat_major import components
    from etat_major.planning_view import PlanningInputs, load_planning_view

    calls = []
    compile_patterns = components._patterns

    def counted(rows):
        calls.append(1)
        return compile_patterns(rows)

    monkeypatch.setattr(components, "_patterns", counted)
    view = load_planning_view(PlanningInputs(planning_workspace, "netlens", trail=TRAIL))
    assert len(view._understand.owner) > 25 and len(calls) == 1
