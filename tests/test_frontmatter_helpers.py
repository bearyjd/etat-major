import pytest

from etat_major import taskfile


def test_public_loader_shares_structured_filename_error(tmp_path):
    path = tmp_path / "002-wrong.md"
    path.write_text(
        "---\nid: 001\ntitle: Test\ninitiative: i\nproject: p\nowner: human\nstatus: ready\n---\n"
    )
    with pytest.raises(taskfile.TaskFileError) as exc:
        taskfile.load_frontmatter_model(path, taskfile.Task, filename_prefix=True)
    assert exc.value.field == "id"
    assert exc.value.message == "id '001' does not match filename prefix '002'"


def test_public_first_error_names_the_field(tmp_path):
    path = tmp_path / "001-test.md"
    with pytest.raises(taskfile.ValidationError) as exc:
        taskfile.Task.model_validate({})
    error = taskfile.first_error(path, exc.value)
    assert (error.path, error.field, error.message) == (path, "id", "Field required")


def test_loader_rejects_symlink_in_parent_directory(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (real / "p.md").write_text("---\nid: p\ntitle: Project\nowner: human\ninitiative: i\n---\n")
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    with pytest.raises(taskfile.TaskFileError, match="p.md.*'file'"):
        taskfile.parse_project(alias / "p.md")


@pytest.mark.parametrize(
    ("yaml", "field"),
    [
        ("target_date: 2027-02-30", "target_date"),
        ("target_date: !!int /private/date", "frontmatter"),
        ("'/private/extra': ignored", "frontmatter"),
    ],
)
def test_frontmatter_diagnostics_do_not_echo_untrusted_paths(tmp_path, yaml, field):
    path = tmp_path / "record\x1b.md"
    path.write_text(f"---\nid: x\ntitle: Record\nowner: human\ninitiative: i\n{yaml}\n---\n")
    with pytest.raises(taskfile.TaskFileError) as exc:
        taskfile.parse_project(path)
    assert exc.value.field == field
    assert r"record\u001b.md" in str(exc.value)
    assert "/private/" not in str(exc.value)
    assert exc.value.__suppress_context__ and exc.value.__cause__ is None


def test_frontmatter_rejects_excessive_yaml_aliases(tmp_path):
    path = tmp_path / "0042-task.md"
    targets = ", ".join(["&target fp:f:src/app.py"] + ["*target"] * 100)
    path.write_text(
        "---\nid: 0042\ntitle: Task\nowner: human\ninitiative: i\nproject: p\nstatus: ready\n"
        f"targets: [{targets}]\n---\n"
    )
    with pytest.raises(taskfile.TaskFileError, match="0042-task.md.*frontmatter.*alias"):
        taskfile.parse_task(path)
