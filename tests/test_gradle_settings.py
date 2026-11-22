import pytest

from test_gradle import deps, write


@pytest.mark.parametrize(
    "settings",
    [
        "pluginManagement { repositories { google() } }",
        'pluginManagement { repositories { val include = "unused"; google() } }',
        'dependencyResolutionManagement { repositories { val projectDir = "unused"; google() } }',
        'enableFeaturePreview("TYPESAFE_PROJECT_ACCESSORS")',
        'enableFeaturePreview("TYPESAFE_PROJECT_ACCESSORS".let { include -> include })',
        'rootProject.name = "app"',
        'rootProject.name = "app".let { include -> include }',
    ],
)
def test_common_settings_are_ignored(tmp_path, capsys, settings):
    write(tmp_path, "settings.gradle.kts", f'{settings}\ninclude(":app")')
    value = deps(tmp_path, capsys)
    assert value["ok"] is True
    assert value["issues"] == []
    assert value["data"]["modules"] == [{"id": ":app", "directory": "app"}]


@pytest.mark.parametrize(
    ("name", "settings"),
    [
        ("settings.gradle.kts", 'includeBuild("build-logic")'),
        ("settings.gradle", "includeBuild 'build-logic'"),
        ("settings.gradle.kts", 'pluginManagement { includeBuild("build-logic") }'),
        ("settings.gradle.kts", 'if (true) { includeBuild("build-logic") }'),
        ("settings.gradle.kts", 'if (true) includeBuild("build-logic")'),
        ("settings.gradle.kts", 'settings.includeBuild("build-logic")'),
        (
            "settings.gradle.kts",
            'pluginManagement { if (true) { includeBuild("build-logic") } }',
        ),
    ],
)
def test_composite_build_is_a_nonblocking_warning(tmp_path, capsys, name, settings):
    write(tmp_path, name, f'{settings}\ninclude(":app")')
    value = deps(tmp_path, capsys)
    assert value["ok"] is True
    assert len(value["issues"]) == 1
    (issue,) = value["issues"]
    assert (issue["path"], issue["field"], issue["severity"]) == (name, "includeBuild", "warning")
    assert "composite build not followed" in issue["message"]
    assert value["data"]["modules"] == [{"id": ":app", "directory": "app"}]


def test_deps_accepts_android_settings(tmp_path, capsys):
    write(
        tmp_path,
        "settings.gradle.kts",
        """
pluginManagement {
    repositories { google() }
    includeBuild("build-logic")
}
dependencyResolutionManagement { }
rootProject.name = "app"
include(":app", ":core:data")
""",
    )
    write(
        tmp_path, "app/build.gradle.kts", 'dependencies { implementation(project(":core:data")) }'
    )
    value = deps(tmp_path, capsys)
    assert value["ok"] is True
    assert [(i["field"], i["severity"]) for i in value["issues"]] == [("includeBuild", "warning")]
    assert [m["id"] for m in value["data"]["modules"]] == [":app", ":core:data"]
    assert [e["target"] for e in value["data"]["edges"]] == [":core:data"]


def test_malformed_ignored_settings_block_still_fails(tmp_path, capsys):
    write(tmp_path, "settings.gradle.kts", "pluginManagement { repositories { google() }")
    value = deps(tmp_path, capsys, 2)
    (issue,) = value["issues"]
    assert (issue["path"], issue["field"], issue["severity"]) == (
        "settings.gradle.kts",
        "syntax",
        "error",
    )
