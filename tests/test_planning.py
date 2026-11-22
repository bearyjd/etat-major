from datetime import date

import pytest
from pydantic import ValidationError

from etat_major import planning, taskfile

MILESTONE = "id: m3\ntitle: Latency history\nhorizon: now\noutcome: Inspect recent latency\n"
VISION = "project: netlens\nvision: Make network behavior visible\ngoals: [Show recent latency]\n"


def markdown(directory, filename, metadata):
    file = directory / filename
    file.write_text(f"---\n{metadata}---\n\nMore context.\n", encoding="utf-8")
    return file


@pytest.mark.parametrize("horizon", ["now", "next", "later"])
def test_milestone_loads_with_optional_date(tmp_path, horizon):
    metadata = MILESTONE.replace("horizon: now", f"horizon: {horizon}")
    if horizon == "next":
        metadata += "target_date: 2027-03-01\n"
    milestone = planning.parse_milestone(markdown(tmp_path, "m3-latency.md", metadata))
    assert (milestone.id, milestone.horizon, milestone.outcome) == (
        "m3",
        horizon,
        "Inspect recent latency",
    )
    assert milestone.target_date == (date(2027, 3, 1) if horizon == "next" else None)
    with pytest.raises(ValidationError, match="frozen"):
        milestone.horizon = "later"


@pytest.mark.parametrize(
    ("filename", "metadata", "field"),
    [
        ("m4.md", MILESTONE, "id"),
        ("m3.md", MILESTONE.replace("now", "soon"), "horizon"),
        ("m3.md", MILESTONE + "target_date: 2027-02-30\n", "target_date"),
        ("m3.md", MILESTONE.replace("outcome:", "unrecognized:"), "outcome"),
    ],
)
def test_bad_milestone_names_file_and_field(tmp_path, filename, metadata, field):
    with pytest.raises(taskfile.TaskFileError, match=rf"{filename}.*'{field}'"):
        planning.parse_milestone(markdown(tmp_path, filename, metadata))


def test_vision_loads_goals_and_diagram_links(tmp_path):
    path = markdown(tmp_path, "netlens.md", VISION + "diagrams: [diagrams/overview.mmd]\n")
    vision = planning.parse_vision(path)
    assert (vision.project, vision.vision) == ("netlens", "Make network behavior visible")
    assert vision.goals == ("Show recent latency",)
    assert vision.diagrams == ("diagrams/overview.mmd",)
    assert vision.body.strip() == "More context."
    with pytest.raises(ValidationError, match="frozen"):
        vision.goals = ()


@pytest.mark.parametrize(
    ("filename", "metadata", "field"),
    [
        ("elsewhere.md", VISION, "project"),
        ("netlens.md", VISION.replace("[Show recent latency]", "[]"), "goals"),
        ("netlens.md", VISION + "diagrams: [diagrams/../outside.mmd]\n", "diagrams.0"),
        ("netlens.md", VISION + "diagrams: [/private/overview.mmd]\n", "diagrams.0"),
    ],
)
def test_invalid_vision_names_file_and_field(tmp_path, filename, metadata, field):
    with pytest.raises(taskfile.TaskFileError, match=rf"{filename}.*'{field}'") as exc:
        planning.parse_vision(markdown(tmp_path, filename, metadata))
    assert "/private/" not in str(exc.value)


@pytest.mark.parametrize(
    ("status", "dependency_status", "column"),
    [
        ("draft", "done", "draft"),
        ("ready", "done", "ready"),
        ("blocked", "done", "blocked"),
        ("done", None, "done"),
        ("ready", None, "blocked"),
        ("ready", "ready", "blocked"),
        ("draft", "blocked", "blocked"),
    ],
)
def test_board_uses_stored_status_and_project_local_dependencies(status, dependency_status, column):
    fields = {"accepted_by": "human", "accepted_on": "2027-03-01"} if status == "done" else {}
    task = taskfile.Task.model_validate(
        {
            "id": "0042",
            "title": "Latency",
            "initiative": "i",
            "project": "netlens",
            "owner": "maintainer",
            "status": status,
            "depends_on": ["0041"],
            **fields,
        }
    )
    dependency_states = {} if dependency_status is None else {"0041": dependency_status}
    assert planning.derive_board_column(task, dependency_states) == column
    summary = planning.BoardEvidence(True, True, True, True)
    assert planning.derive_board_column(task, dependency_states, evidence=summary) == column
