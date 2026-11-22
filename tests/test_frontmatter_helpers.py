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
