import json
import shutil
from pathlib import Path

import pytest
import yaml

from etat_major.components import load_components
from etat_major.components_seed import seed_components as seed
from etat_major.taskfile import TaskFileError

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def gradle_root(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(FIXTURES / "gradle-real", root)
    for path in ("app", "core/data", "core/scan", "feature/lanscan"):
        (root / path).mkdir(parents=True, exist_ok=True)
    return root


def rows(path):
    return {
        component["id"]: component
        for component in yaml.safe_load(path.read_text(encoding="utf-8"))["components"]
    }


def test_seed_real_gradle_is_deterministic_and_loadable(gradle_root, tmp_path):
    first, second = tmp_path / "netlens.yaml", tmp_path / "second.yaml"
    result = seed(gradle_root, "netlens", out=first)
    seed(gradle_root, "netlens", out=second)
    assert first.read_bytes() == second.read_bytes()
    proposed = rows(first)
    assert result.output == "netlens.yaml"
    assert result.project == "netlens"
    assert set(result.components) == proposed.keys()
    assert len(proposed) == 38
    assert proposed["feature.portscan"]["parent"] == "feature"
    assert proposed["core.network"]["parent"] == "core"
    assert proposed["core.network"]["paths"] == ["core/network"]
    assert proposed["feature"]["paths"] == []
    assert all(row["kind"] == "inferred_from_gradle" for row in proposed.values())
    assert all("summary" not in row for row in proposed.values())
    output = first.read_text(encoding="utf-8")
    assert "reviewed_by" not in output
    assert "reviewed_on" not in output
    comments = [line for line in output.splitlines() if line.strip().startswith("# Proposal")]
    assert len(comments) == len(proposed)
    model, issues = load_components(first)
    assert model is not None
    assert not any(issue.blocking for issue in issues)


def test_seed_uses_trail_scopes_for_additions_and_deduplicates(gradle_root, tmp_path):
    settings = gradle_root / "settings.gradle.kts"
    settings.write_text(
        settings.read_text(encoding="utf-8").replace('include(":feature:lanscan")', ""),
        encoding="utf-8",
    )
    out = tmp_path / "netlens.yaml"
    seed(gradle_root, "netlens", trail=FIXTURES / "trail/wiring-kotlin.json", out=out)
    proposed = rows(out)
    assert proposed["feature.lanscan"]["paths"] == ["feature/lanscan"]
    assert proposed["core.data"]["paths"] == ["core/data"]
    assert proposed["root"]["paths"] == ["**"]
    assert len(proposed) == 39


def test_seed_prefers_gradle_remap_and_keeps_a_scope_conflict_diagnostic(gradle_root, tmp_path):
    settings = gradle_root / "settings.gradle.kts"
    with settings.open("a", encoding="utf-8") as stream:
        stream.write('\nproject(":feature:lanscan").projectDir = file("modules/lan")\n')
    (gradle_root / "modules/lan").mkdir(parents=True)
    out = tmp_path / "netlens.yaml"
    result = seed(gradle_root, "netlens", trail=FIXTURES / "trail/wiring-kotlin.json", out=out)
    proposed = rows(out)
    assert "feature.lanscan" not in proposed
    assert proposed["modules.lan"]["paths"] == ["modules/lan"]
    assert any(
        issue.path == "wiring-kotlin.json"
        and issue.field == "meta.scopes"
        and not issue.blocking
        and "feature/lanscan" in issue.message
        and "modules/lan" in issue.message
        for issue in result.issues
    )


def test_seed_assigns_one_owner_for_modules_with_a_shared_directory(gradle_root, tmp_path):
    settings = gradle_root / "settings.gradle.kts"
    with settings.open("a", encoding="utf-8") as stream:
        stream.write(
            '\nproject(":feature:lanscan").projectDir = file("modules/shared")\n'
            'project(":feature:portscan").projectDir = file("modules/shared")\n'
        )
    (gradle_root / "modules/shared").mkdir(parents=True)
    out = tmp_path / "netlens.yaml"
    seed(gradle_root, "netlens", out=out)

    owners = [row["id"] for row in rows(out).values() if row["paths"] == ["modules/shared"]]
    assert owners == ["modules.shared"]
    model, issues = load_components(out)
    assert model is not None and not any(issue.blocking for issue in issues)
    assert model.owner_of("modules/shared/src/main/Shared.kt").component.id == "modules.shared"


@pytest.mark.parametrize("dependency", ["modulePath", '":missing"'])
def test_seed_keeps_modules_when_dependency_expressions_are_unresolved(
    gradle_root, tmp_path, dependency
):
    script = gradle_root / "feature/portscan/build.gradle.kts"
    with script.open("a", encoding="utf-8") as stream:
        stream.write(f"\ndependencies {{ implementation(project({dependency})) }}\n")
    out = tmp_path / "netlens.yaml"
    result = seed(gradle_root, "netlens", out=out)
    assert rows(out)["feature.portscan"]["paths"] == ["feature/portscan"]
    assert any(
        issue.path == "feature/portscan/build.gradle.kts"
        and issue.field == "dependencies"
        and not issue.blocking
        for issue in result.issues
    )


def test_seed_preserves_modules_with_colliding_normalized_ids(tmp_path):
    settings = tmp_path / "settings.gradle.kts"
    settings.write_text('include(":my.module", ":my-module", ":feature", ":feature:one")')
    out = tmp_path / "netlens.yaml"
    seed(tmp_path, "netlens", out=out)
    proposed = rows(out)
    assert proposed["my-module"]["paths"] == ["my-module"]
    assert proposed["my-module-2"]["paths"] == ["my.module"]
    assert proposed["feature"]["paths"] == ["feature"]
    assert proposed["feature.one"]["parent"] == "feature"


def test_seed_refuses_existing_file_or_dangling_link(gradle_root, tmp_path):
    out = tmp_path / "netlens.yaml"
    out.write_text("authored\n", encoding="utf-8")
    dangling = tmp_path / "dangling.yaml"
    dangling.symlink_to(tmp_path / "target")
    for existing in (out, dangling):
        with pytest.raises(TaskFileError, match=r"field 'out'.*already exists"):
            seed(gradle_root, "netlens", out=existing)
    assert out.read_text(encoding="utf-8") == "authored\n"
    assert not (tmp_path / "target").exists()


def test_proposal_has_only_missing_modules_and_preserves_authored_parents(gradle_root, tmp_path):
    original = tmp_path / "netlens.yaml"
    content = (
        "version: 1\nproject: netlens\ncomponents:\n"
        "- {id: feature, label: Features, kind: group, paths: []}\n"
        "- {id: feature.portscanner, label: Reviewed, kind: screen, parent: feature, "
        "paths: [feature/portscan]}\n"
        "- {id: feature.ping, label: Reviewed, kind: screen, parent: feature, "
        "paths: ['feature/ping/src/**/*.kt']}\n"
    )
    original.write_text(content, encoding="utf-8")
    result = seed(gradle_root, "netlens", proposal_for=original)
    out = original.with_suffix(".yaml.proposed")
    proposed = rows(out)
    assert result.output == "netlens.yaml.proposed"
    assert {"feature", "feature.portscan", "feature.portscanner"}.isdisjoint(proposed)
    assert not any(row["paths"] == ["feature/ping"] for row in proposed.values())
    assert proposed["feature.lanscan"]["parent"] == "feature"
    assert original.read_text(encoding="utf-8") == content
    before = out.read_bytes()
    with pytest.raises(TaskFileError, match=r"field 'proposal_for'.*already exists"):
        seed(gradle_root, "netlens", proposal_for=original)
    assert out.read_bytes() == before


def test_seed_refuses_output_through_symlink_directory(gradle_root, tmp_path):
    link = tmp_path / "link"
    target = tmp_path / "target"
    target.mkdir()
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(TaskFileError, match=r"netlens\.yaml: field 'out'"):
        seed(gradle_root, "netlens", out=link / "netlens.yaml")
    assert list(target.iterdir()) == []


def test_seed_invalid_trail_leaves_no_output(gradle_root, tmp_path):
    trail = tmp_path / "wiring.json"
    data = json.loads((FIXTURES / "trail/wiring-kotlin.json").read_text(encoding="utf-8"))
    data["meta"]["scopes"][0]["prefix"] = "feature/*"
    trail.write_text(json.dumps(data), encoding="utf-8")
    out = tmp_path / "netlens.yaml"
    with pytest.raises(TaskFileError, match=r"wiring\.json: field 'meta\.scopes"):
        seed(gradle_root, "netlens", out=out, trail=trail)
    assert not out.exists()


def test_seed_rejects_invalid_project_and_existing_project_mismatch(gradle_root, tmp_path):
    out = tmp_path / "netlens.yaml"
    with pytest.raises(TaskFileError, match=r"field 'project'"):
        seed(gradle_root, "../netlens", out=out)
    assert not out.exists()
    out.write_text("version: 1\nproject: netlens\ncomponents: []\n")
    with pytest.raises(TaskFileError, match=r"field 'project'"):
        seed(gradle_root, "other", proposal_for=out)
    assert not out.with_suffix(".yaml.proposed").exists()


def test_seed_rejects_an_out_of_contract_project_id(gradle_root, tmp_path):
    out = tmp_path / "netlens.yaml"
    with pytest.raises(TaskFileError, match=r"field 'project'"):
        seed(gradle_root, "p" * 129, out=out)
    assert not out.exists()


def test_seed_rejects_a_proposal_target_without_filename(gradle_root):
    with pytest.raises(TaskFileError, match=r"field 'proposal_for'"):
        seed(gradle_root, "netlens", proposal_for=Path("."))


def test_seed_keeps_collision_suffix_within_component_id_limit(tmp_path):
    first_segment = "a" * 128
    second_segment = "b" * 127
    settings = tmp_path / "settings.gradle.kts"
    modules = (f":{first_segment}:{second_segment}", f":{first_segment}:{second_segment.upper()}")
    settings.write_text(
        f'include("{modules[0]}", "{modules[1]}")',
        encoding="utf-8",
    )
    out = tmp_path / "netlens.yaml"
    seed(tmp_path, "netlens", out=out)
    model, issues = load_components(out)
    assert model is not None
    assert not any(issue.blocking for issue in issues)
    assert len(model.components) == 3


def test_seed_keeps_expanded_unicode_ids_within_component_limit(gradle_root, tmp_path):
    trail = tmp_path / "wiring.json"
    data = json.loads((FIXTURES / "trail/wiring-kotlin.json").read_text(encoding="utf-8"))
    directory = "İ" * 130
    data["meta"]["scopes"][0]["prefix"] = directory
    trail.write_text(json.dumps(data), encoding="utf-8")
    out = tmp_path / "netlens.yaml"
    seed(gradle_root, "netlens", out=out, trail=trail)
    model, issues = load_components(out)
    assert model is not None
    assert not any(issue.blocking for issue in issues)
    assert any(row.paths == (directory,) for row in model.components)


def test_seed_rejects_a_proposal_over_component_limit(tmp_path):
    settings = tmp_path / "settings.gradle.kts"
    settings.write_text("\n".join(f'include(":module{i}")' for i in range(501)), encoding="utf-8")
    out = tmp_path / "netlens.yaml"
    with pytest.raises(TaskFileError, match=r"field 'components'.*500"):
        seed(tmp_path, "netlens", out=out)
    assert not out.exists()
