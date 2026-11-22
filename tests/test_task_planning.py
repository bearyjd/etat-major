import os
from pathlib import Path

import pytest

from etat_major.taskfile import TaskFileError, parse_task

GOOD = """---
id: 0042
title: Schema mapper
initiative: example-initiative
project: example-service
owner: alice
status: ready
priority: 2
---
"""


def task(tmp_path, text=GOOD):
    path = tmp_path / "0042-schema-mapper.md"
    path.write_text(text)
    return path


def sub(old, new):
    assert old in GOOD
    return GOOD.replace(old, new)


def test_task_links_are_parsed(tmp_path):
    p = task(
        tmp_path,
        sub(
            "priority: 2",
            "priority: 2\nmilestone: m3\ndepends_on: [0041, 43]\n"
            "targets: [fp:f:src/app.py, fp:n:demo, 'trail:src/app.py#main']",
        ),
    )
    t = parse_task(p)
    assert t.milestone == "m3"
    assert t.depends_on == ("0041", "43")
    assert [str(ref) for ref in t.targets] == [
        "fp:f:src/app.py",
        "fp:n:demo",
        "trail:src/app.py#main",
    ]
    assert t.targets[0].kind == "fp:f"


@pytest.mark.parametrize(
    ("extra", "field"),
    [
        ("milestone: milestone:demo/m3", "milestone"),
        ("milestone: M3", "milestone"),
        ("depends_on: [task:demo/0041]", "depends_on.0"),
        ("depends_on: [true]", "depends_on.0"),
        ("depends_on: 0041", "depends_on"),
        ("targets: [fp:f:/private/absolute/path]", "targets.0"),
        ("targets: [feature:demo/0010]", "targets.0"),
        ("targets: fp:f:src/app.py", "targets"),
    ],
)
def test_invalid_task_links(tmp_path, extra, field):
    with pytest.raises(TaskFileError) as e:
        parse_task(task(tmp_path, sub("priority: 2", f"priority: 2\n{extra}")))
    assert e.value.field == field
    assert "/private/absolute/path" not in str(e.value)


@pytest.mark.parametrize(
    ("status", "acceptance", "field"),
    [
        ("done", "accepted_on: 2027-03-01", "accepted_by"),
        ("done", "accepted_by: alice", "accepted_on"),
        ("done", "accepted_by: '  '\naccepted_on: 2027-03-01", "accepted_by"),
        ("done", "accepted_by: alice\naccepted_on: 2027-02-29", "accepted_on"),
        ("done", "accepted_by: alice\naccepted_on: '2027-02-29'", "accepted_on"),
        ("done", "accepted_by: alice\naccepted_on: '20270301'", "accepted_on"),
        ("done", "accepted_by: alice\naccepted_on: '2027-03-01T00:00:00'", "accepted_on"),
        ("done", "accepted_by: null\naccepted_on: 2027-03-01", "accepted_by"),
        ("ready", "accepted_by: alice", "accepted_by"),
        ("ready", "accepted_by: null", "accepted_by"),
        ("ready", "accepted_on: null", "accepted_on"),
    ],
)
def test_acceptance_requires_done_and_both_fields(tmp_path, status, acceptance, field):
    with pytest.raises(TaskFileError) as e:
        parse_task(task(tmp_path, sub("status: ready", f"status: {status}\n{acceptance}")))
    assert e.value.field == field


def test_parse_task_relative_to_directory_fd(tmp_path):
    p = task(tmp_path)
    fd = os.open(p.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        assert parse_task(Path(p.name), dir_fd=fd).id == "0042"
    finally:
        os.close(fd)
