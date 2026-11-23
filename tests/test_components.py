from pathlib import Path

import pytest
import yaml

from etat_major import components


def component(ident="feature.ping", **fields):
    return {
        "id": ident,
        "label": "Ping",
        "kind": "custom-kind",
        "paths": ["feature/ping"],
        **fields,
    }


def write_model(tmp_path, entries, **fields):
    path = tmp_path / "sample.yaml"
    path.write_text(
        yaml.safe_dump({"version": 1, "project": "sample", "components": entries, **fields})
    )
    return path


def test_match_and_coverage(tmp_path):
    path = write_model(
        tmp_path,
        [
            component("feature", paths=["feature"]),
            component(parent="feature"),
            component("feature.slow", parent="feature", paths=["feature/ping/slow/**/Test?.kt"]),
            component("feature.other", parent="feature", paths=["feature/ping/slow/**/Test*.kt"]),
        ],
    )
    model, issues = components.load_components(path)
    assert model is not None
    assert model.owner_of("feature/ping/Ping.kt").component.id == "feature.ping"
    assert model.owner_of("feature/ping-extra/Ping.kt").component.id == "feature"
    assert model.owner_of("feature/ping/slow/Test22.kt").component.id == "feature.other"
    tie = model.owner_of("feature/ping/slow/sub/Test1.kt")
    assert tie.component is None
    assert tie.ties == ("feature.other", "feature.slow")
    assert any(
        i.severity == "warning" and "feature.other" in i.message and "feature.slow" in i.message
        for i in issues
    )
    assert [c.id for c in model.children_of("feature")] == [
        "feature.other",
        "feature.ping",
        "feature.slow",
    ]
    assert [c.id for c in model.ancestors_of("feature.slow")] == ["feature"]
    coverage = model.coverage(["README.md", "feature/ping/Ping.kt", "feature/ping/Ping.kt"])
    assert coverage.owned == ("feature/ping/Ping.kt",)
    assert coverage.unowned == ("README.md",)
    assert coverage.percentage == 50.0
    assert model.coverage([]).percentage == 0.0
    with pytest.raises(ValueError):
        model.components[0].label = "changed"


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", "Upper"),
        ("id", "double..dot"),
        ("label", 1),
        ("kind", []),
        ("owner", 2),
        ("extra", True),
        ("paths", "/module"),
        *[
            ("paths", [bad])
            for bad in (
                "/module",
                "a/../b",
                "a\\b",
                "a\0b",
                "a%b",
                "a//b",
                "a/./b",
                "~/b",
                "C:/b",
                "a⁄b",
                "a b",
                "a#b",
                "https://private.invalid/repo",
            )
        ],
        ("summary", {"text": "summary"}),
        ("summary", {"text": "summary", "provenance": "draft"}),
        ("summary", {"text": "summary", "provenance": "human", "reviewed_by": "Reviewer"}),
        ("summary", {"text": "summary", "provenance": "human", "reviewed_on": "2026-11-22"}),
        (
            "summary",
            {
                "text": "summary",
                "provenance": "human",
                "reviewed_by": None,
                "reviewed_on": "2026-11-22",
            },
        ),
        (
            "summary",
            {
                "text": "summary",
                "provenance": "human",
                "reviewed_by": "R",
                "reviewed_on": "2026-02-31",
            },
        ),
    ],
)
def test_component_field_errors(tmp_path, field, value):
    model, issues = components.load_components(write_model(tmp_path, [component(**{field: value})]))
    assert model is None
    assert any(i.field.startswith(f"components.0.{field}") for i in issues)
    assert all(i.path == "sample.yaml" for i in issues)
    assert "private.invalid" not in str(issues)


@pytest.mark.parametrize(
    "fields,field",
    [
        ({"version": "1"}, "version"),
        ({"version": True}, "version"),
        ({"version": 2}, "version"),
        ({"project": "Other"}, "project"),
        ({"unexpected": 3}, "unexpected"),
    ],
)
def test_document_fields(tmp_path, fields, field):
    model, issues = components.load_components(write_model(tmp_path, [], **fields))
    assert model is None
    assert [i.field for i in issues] == [field]


def test_reports_multiple_structural_and_field_errors(tmp_path):
    path = write_model(
        tmp_path,
        [
            component("root", parent="leaf", paths=[]),
            component("leaf", parent="root"),
            component("leaf", parent="missing"),
            component("empty", paths=[]),
            component("error", label=False, kind=2),
        ],
    )
    model, issues = components.load_components(path)
    assert model is None
    assert {
        "components.0.parent",
        "components.2.id",
        "components.2.parent",
        "components.3.paths",
        "components.4.label",
        "components.4.kind",
    } <= {i.field for i in issues}


def test_review_provenance_is_preserved(tmp_path):
    path = write_model(
        tmp_path,
        [
            component("feature", paths=[]),
            component(
                parent="feature",
                summary={
                    "text": "Written by AI and checked",
                    "provenance": "ai-generated",
                    "reviewed_by": "Reviewer",
                    "reviewed_on": "2026-11-22",
                },
            ),
        ],
    )
    model, issues = components.load_components(path)
    assert issues == ()
    assert model.get("feature").summary is None
    summary = model.get("feature.ping").summary
    assert summary.provenance == "ai-generated"
    assert summary.reviewed_on.isoformat() == "2026-11-22"


@pytest.mark.parametrize(
    "content",
    [
        "x" * (1024 * 1024 + 1),
        "field: " + "[" * 100 + "0" + "]" * 100,
        "project: sample\nproject: duplicate\n",
        "x: &anchor [*anchor]\n",
        "x: !!int broken\n",
        "x: \x1b\n",
        "x: " + "[0, " * 65 + "0" + "]" * 65,
        "x: [" + "0, " * 20001 + "0]\n",
        "!!set {a: null}\n",
    ],
)
def test_hostile_yaml_has_file_and_field_error(tmp_path, content):
    path = tmp_path / "sample.yaml"
    path.write_text(content)
    model, issues = components.load_components(path)
    assert model is None
    assert issues[0].path == "sample.yaml"
    assert issues[0].field
    assert "\x1b" not in str(issues[0])


def test_workspace_refuses_symlinks_and_reports_other_files(tmp_path):
    directory = tmp_path / "components"
    directory.mkdir()
    sample = write_model(tmp_path, [component()])
    (directory / "sample.yaml").symlink_to(sample)
    (directory / "b.yaml").write_text("version: 1\nproject: b\ncomponents: []\n")
    models, issues = components.load_component_workspace(tmp_path)
    assert list(models) == ["b"]
    assert [(i.path, i.field) for i in issues] == [("components/sample.yaml", "file")]
    (tmp_path / "link").symlink_to(directory, target_is_directory=True)
    model, issues = components.load_components(tmp_path / "link/b.yaml")
    assert model is None
    assert issues[0].field == "file"


def test_standalone_input_named_proposed_can_be_reloaded(tmp_path):
    path = write_model(tmp_path, [])
    proposal = path.with_suffix(".yaml.proposed")
    path.rename(proposal)
    model, issues = components.load_components(proposal)
    assert model.project == "sample"
    assert not issues


def test_standalone_catches_stream_marker_injection(tmp_path):
    path = tmp_path / "sample.yaml"
    path.write_text("version: 1\nproject: sample\ncomponents: []\n---\ninvalid\n")
    assert components.load_components(path)[0] is None


def test_component_yaml_schema(tmp_path):
    from json import loads

    from jsonschema import Draft202012Validator

    schema = loads(Path("docs/contracts/schemas/components.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    path = write_model(tmp_path, [component()])
    validator.validate(yaml.safe_load(path.read_text()))
    invalid = yaml.safe_load(path.read_text())
    invalid["components"][0]["paths"] = ["/module"]
    assert list(validator.iter_errors(invalid))


def test_workspace_filename_must_match_project(tmp_path):
    directory = tmp_path / "components"
    directory.mkdir()
    write_model(directory, [], project="other")
    models, issues = components.load_component_workspace(tmp_path)
    assert models == {}
    assert [(i.path, i.field) for i in issues] == [("components/sample.yaml", "project")]


def test_review_date_cannot_be_explicit_null(tmp_path):
    row = component(summary={"text": "Authored", "provenance": "human", "reviewed_on": None})
    model, issues = components.load_components(write_model(tmp_path, [row]))
    assert model is None
    assert any(i.field.startswith("components.0.summary") for i in issues)


def test_coverage_accepts_safe_filenames_with_spaces(tmp_path):
    model, _ = components.load_components(write_model(tmp_path, [component()]))
    assert model.coverage(["feature/ping/A B.kt"]).owned == ("feature/ping/A B.kt",)


def test_disjoint_globs_and_inverted_ranges(tmp_path):
    model, issues = components.load_components(
        write_model(
            tmp_path,
            [
                component("a", paths=["src/**/f[0-2].kt"]),
                component("b", paths=["src/**/f[3-5].kt"]),
                component("c", paths=["src/**/f[z-a].kt"]),
                component("d", paths=["src/**/f?.kt"]),
            ],
        )
    )
    assert model is not None
    assert [i.message for i in issues] == [
        "sibling paths overlap: a and d",
        "sibling paths overlap: b and d",
    ]


def test_invalid_label_does_not_hide_duplicate_or_orphan_a_child(tmp_path):
    path = write_model(
        tmp_path,
        [
            component("feature", label=3, paths=[]),
            component("feature", kind=2),
            component(parent="feature"),
        ],
    )
    model, issues = components.load_components(path)
    assert model is None
    assert {i.field for i in issues} == {
        "components.0.label",
        "components.1.kind",
        "components.1.id",
    }


def test_expensive_overlap_returns_bounded_file_diagnostic(tmp_path, monkeypatch):
    from etat_major import component_paths

    monkeypatch.setattr(component_paths, "_OVERLAP_WORK_LIMIT", 500, raising=False)
    rows = [component(ident, paths=["app/" + "*?" * 20 + ident]) for ident in ("a", "b", "c")]
    model, issues = components.load_components(write_model(tmp_path, rows))
    assert model is None
    assert any(i.field == "components" and "overlap" in i.message for i in issues)


def test_unclosed_bracket_in_directory_is_literal(tmp_path):
    model, issues = components.load_components(
        write_model(tmp_path, [component(paths=["feature/ping["])])
    )
    assert not issues
    assert model.owner_of("feature/ping[/Probe.kt").component.id == "feature.ping"


def test_component_schema_date_annotation_and_runtime_path_restrictions(tmp_path):
    from json import loads

    from jsonschema import Draft202012Validator, FormatChecker

    schema = loads(Path("docs/contracts/schemas/components.schema.json").read_text())
    portable = Draft202012Validator(schema)
    with_formats = Draft202012Validator(schema, format_checker=FormatChecker())
    summary = {
        "text": "Reviewed architecture",
        "provenance": "human",
        "reviewed_by": "maintainer",
        "reviewed_on": "2026-11-22",
    }
    valid = write_model(tmp_path, [component(summary=summary)])
    with_formats.validate(yaml.safe_load(valid.read_text()))
    assert components.load_components(valid)[0] is not None

    bad_date = write_model(tmp_path, [component(summary=summary | {"reviewed_on": "2026-02-31"})])
    decoded = yaml.safe_load(bad_date.read_text())
    portable.validate(decoded)
    assert list(with_formats.iter_errors(decoded))
    model, issues = components.load_components(bad_date)
    assert model is None and any(issue.field.endswith(".reviewed_on") for issue in issues)

    deceptive_path = write_model(tmp_path, [component(paths=["module\u202ename"])])
    with_formats.validate(yaml.safe_load(deceptive_path.read_text()))
    model, issues = components.load_components(deceptive_path)
    assert model is None and any(".paths" in issue.field for issue in issues)
