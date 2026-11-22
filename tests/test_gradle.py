import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from etat_major.cli import main

SCHEMAS = Path(__file__).parents[1] / "docs/contracts/schemas"


def write(root, path, text):
    file = root / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text, encoding="utf-8")


def deps(root, capsys, status=0):
    assert main(["gradle", "deps", "--root", str(root), "--format", "json"]) == status
    output = capsys.readouterr()
    assert not output.err
    assert str(root) not in output.out
    value = json.loads(output.out)
    schema = json.loads((SCHEMAS / "gradle-deps.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(value)
    return value


def test_kotlin_module_paths_configurations_and_lines(tmp_path, capsys):
    write(
        tmp_path,
        "settings.gradle.kts",
        """
include(
    ":app", ":core:data",
    ":core:network", ":core:scan-testing",
)
project(":app").projectDir = file("clients/mobile")
""",
    )
    write(
        tmp_path,
        "clients/mobile/build.gradle.kts",
        """
val preview = "implementation(project(':core:data'))"
dependencies {
    api(project(":core:network"))
    implementation(projects.core.scanTesting)
    testImplementation(testFixtures(projects.core.data))
    androidTestImplementation(project(":core:network"))
    debugImplementation(project(":core:data"))
    releaseImplementation(project(":core:data"))
    compileOnly(project(":core:data"))
    runtimeOnly(project(":core:data"))
    ksp(projects.core.data)
    kapt(projects.core.data)
    testFixturesApi(projects.core.data)
    add("customConfig", project(":core:network"))
}
""",
    )
    data = deps(tmp_path, capsys)["data"]
    assert {row["id"]: row["directory"] for row in data["modules"]} == {
        ":app": "clients/mobile",
        ":core:data": "core/data",
        ":core:network": "core/network",
        ":core:scan-testing": "core/scan-testing",
    }
    assert [
        (e["target"], e["configuration"], e["test_only"], e["line"]) for e in data["edges"]
    ] == [
        (":core:network", "api", False, 4),
        (":core:scan-testing", "implementation", False, 5),
        (":core:data", "testImplementation", True, 6),
        (":core:network", "androidTestImplementation", True, 7),
        (":core:data", "debugImplementation", False, 8),
        (":core:data", "releaseImplementation", False, 9),
        (":core:data", "compileOnly", False, 10),
        (":core:data", "runtimeOnly", False, 11),
        (":core:data", "ksp", False, 12),
        (":core:data", "kapt", False, 13),
        (":core:data", "testFixturesApi", True, 14),
        (":core:network", "customConfig", False, 15),
    ]
    assert {e["file"] for e in data["edges"]} == {"clients/mobile/build.gradle.kts"}
    assert {e["source"] for e in data["edges"]} == {":app"}


def test_groovy_comments_and_literals(tmp_path, capsys):
    write(
        tmp_path,
        "settings.gradle",
        """
// include ':disabled'
include ':app',
    ':a:b',
    ':other',
rootProject.name = 'demo'
""",
    )
    write(
        tmp_path,
        "app/build.gradle",
        """
def dependenciesExample = "dependencies { api(project(':other')) }"
dependencies {
    // api(project(':other'))
    /* api(project(':other'))
       /* nested comment */
       api(project(':other')) */
    def preview = """
        + "'''"
        + """
       api(project(':other'))
"""
        + "'''"
        + """
    implementation project(path: ':a:b', configuration: 'default')
    testImplementation testFixtures(project(':other'))
    runtimeOnly projects.a.b
}
""",
    )
    data = deps(tmp_path, capsys)["data"]
    assert [m["id"] for m in data["modules"]] == [":a:b", ":app", ":other"]
    assert [(e["target"], e["configuration"], e["test_only"]) for e in data["edges"]] == [
        (":a:b", "implementation", False),
        (":other", "testImplementation", True),
        (":a:b", "runtimeOnly", False),
    ]


def test_unsupported_and_unresolved_constructs_are_reported(tmp_path, capsys):
    write(
        tmp_path,
        "settings.gradle.kts",
        """
include(":app", ":core:scan-testing", ":core:scanTesting", ":other")
include(moduleList)
includeBuild("composite")
project(":other").projectDir = directoryProvider.get()
""",
    )
    write(
        tmp_path,
        "app/build.gradle.kts",
        """
dependencies {
    implementation(project(computed))
    api(project(":absent"))
    ksp(projects.core.scanTesting)
    kapt(projects.unknown)
    implementation(project(path = ":core:scan-testing"))
}
""",
    )
    value = deps(tmp_path, capsys, 1)
    assert [e["target"] for e in value["data"]["edges"]] == [":core:scan-testing"]
    assert [(i["path"], i["field"]) for i in value["issues"]] == [
        ("settings.gradle.kts", "include"),
        ("settings.gradle.kts", "includeBuild"),
        ("settings.gradle.kts", "projectDir"),
        *[("app/build.gradle.kts", "dependencies")] * 4,
    ]
    assert "ambiguous" in value["issues"][-2]["message"]


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        ("x" * (256 * 1024 + 1), "256 KiB"),
        ("(" * 3000 + ")" * 3000, "nesting"),
        ("/* unfinished", "unterminated"),
        ("include(':bad\x1bname')", "unsupported"),
        ("include(':app:' + 'suffix')", "unsupported"),
    ],
)
def test_invalid_settings_are_bounded(tmp_path, capsys, contents, message):
    write(tmp_path, "settings.gradle", contents)
    status = 1 if message == "unsupported" else 2
    value = deps(tmp_path, capsys, status)
    (issue,) = value["issues"]
    assert issue["path"] == "settings.gradle"
    assert issue["field"]
    assert message in issue["message"]
    assert "\x1b" not in json.dumps(issue, ensure_ascii=False)


def test_symlinks_are_never_read(tmp_path, capsys):
    root = tmp_path / "root"
    write(root, "settings.gradle", "include ':linked', ':file'")
    write(tmp_path, "outside/build.gradle", "dependencies { api(project(':file')) }")
    (root / "linked").symlink_to(tmp_path / "outside", target_is_directory=True)
    (root / "file").mkdir()
    (root / "file/build.gradle").symlink_to(tmp_path / "outside/build.gradle")
    value = deps(root, capsys, 1)
    assert value["data"]["edges"] == []
    assert {i["path"] for i in value["issues"]} == {"linked", "file/build.gradle"}
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    assert deps(alias, capsys, 2)["issues"][0]["field"] == "root"
    (root / "settings.gradle").unlink()
    (root / "settings.gradle").symlink_to(tmp_path / "outside/build.gradle")
    assert deps(root, capsys, 2)["issues"][0]["path"] == "settings.gradle"


def test_tree_budget_and_project_depth(tmp_path, capsys):
    settings = "include " + ",".join(f"':m{i}'" for i in range(2500))
    write(tmp_path, "settings.gradle", settings)
    assert "5000" in deps(tmp_path, capsys, 2)["issues"][0]["message"]
    write(tmp_path, "settings.gradle", "include '" + ":m" * 100 + "'")
    assert "depth" in deps(tmp_path, capsys, 1)["issues"][0]["message"]


def test_cli_text_and_json_argument_errors(tmp_path, capsys):
    write(tmp_path, "settings.gradle", "include ':app'")
    write(tmp_path, "build.gradle", "dependencies { api project(':app') }")
    assert main(["gradle", "deps", "--root", str(tmp_path)]) == 0
    output = capsys.readouterr()
    assert ": -> :app" in output.out
    assert "build.gradle:1" in output.out
    assert main(["gradle", "deps", "--format=json"]) == 2
    output = capsys.readouterr()
    assert not output.err
    assert json.loads(output.out)["issues"][0]["field"] == "arguments"


def test_unparsed_project_expressions_are_flagged_without_guessing(tmp_path, capsys):
    write(
        tmp_path,
        "settings.gradle",
        """
include ':app', computedPath
if (enabled) { include ':other' }
""",
    )
    write(
        tmp_path,
        "app/build.gradle",
        """
dependencies {
    def preview = /
        api(project(':app'))
    /
    implementation(wrap(project(':app')))
    if (enabled) { implementation(project(':app')) }
}
""",
    )
    value = deps(tmp_path, capsys, 1)
    assert value["data"]["edges"] == []
    assert [i["field"] for i in value["issues"]] == [
        "include",
        "include",
        "dependencies",
        "dependencies",
    ]
    assert [i["message"].split(":")[0] for i in value["issues"]] == [
        "line 2",
        "line 3",
        "line 6",
        "line 7",
    ]


def test_computed_project_directory_is_never_used(tmp_path, capsys):
    write(
        tmp_path,
        "settings.gradle.kts",
        """
include(":app")
project(":app").projectDir = file("static") / computed
""",
    )
    write(tmp_path, "static/build.gradle.kts", 'dependencies { api(project(":app")) }')
    value = deps(tmp_path, capsys, 1)
    assert value["data"]["edges"] == []
    assert value["issues"][0]["field"] == "projectDir"


def test_malformed_build_script_keeps_other_modules(tmp_path, capsys):
    write(tmp_path, "settings.gradle", "include ':app', ':lib'")
    write(tmp_path, "app/build.gradle", "dependencies { api(project(':lib')) }")
    write(tmp_path, "lib/build.gradle", "dependencies { api(project(':app')")
    value = deps(tmp_path, capsys, 1)
    assert len(value["data"]["edges"]) == 1
    (issue,) = value["issues"]
    assert (issue["path"], issue["field"]) == ("lib/build.gradle", "syntax")


def test_qualified_and_nested_settings_cannot_redirect_discovery(tmp_path, capsys):
    write(
        tmp_path,
        "settings.gradle.kts",
        """
include(":app", ":lib")
helper.include(":fake")
helper.project(":lib").projectDir = file("wrong")
if (enabled) { project(":app").projectDir = file("elsewhere") }
""",
    )
    write(tmp_path, "wrong/build.gradle.kts", 'dependencies { api(project(":lib")) }')
    write(tmp_path, "app/build.gradle.kts", 'dependencies { api(project(":lib")) }')
    value = deps(tmp_path, capsys, 1)
    assert value["data"]["edges"] == []
    assert value["data"]["modules"] == [{"id": ":lib", "directory": "lib"}]
    assert [i["field"] for i in value["issues"]] == ["include", "projectDir", "projectDir"]


def test_interpolations_and_qualified_blocks_do_not_declare_projects(tmp_path, capsys):
    write(
        tmp_path,
        "settings.gradle.kts",
        """
include(":app")
val example = "${"include(':fake')"}"
""",
    )
    write(
        tmp_path,
        "app/build.gradle.kts",
        """
val example = "${"dependencies { api(project(':app')) }"}"
helper.dependencies { api(project(':app')) }
dependencies { implementation(project(":app")) }
""",
    )
    data = deps(tmp_path, capsys)["data"]
    assert [m["id"] for m in data["modules"]] == [":app"]
    assert [e["configuration"] for e in data["edges"]] == ["implementation"]
