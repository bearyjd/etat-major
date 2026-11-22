from pathlib import Path

import pytest

from etat_major.gradle import load_dependencies

REAL = Path(__file__).parent / "fixtures/gradle-real"


def write(root, path, content):
    file = root / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(content, encoding="utf-8")
    return file


def plugin_build(root, settings='includeBuild("build-logic")'):
    write(root, "settings.gradle.kts", f'{settings}\ninclude(":app", ":core", ":test")')
    write(
        root,
        "build-logic/convention/build.gradle.kts",
        """
gradlePlugin {
    plugins {
        register("first") {
            id = "demo.first"
            implementationClass = "demo.First"
        }
        create("second") {
            id = "demo.second"
            implementationClass = "demo.Second"
        }
    }
}
""",
    )


def source(root, name, body):
    return write(
        root,
        f"build-logic/convention/src/main/kotlin/demo/{name}.kt",
        f"package demo\nclass {name} : Plugin<Project> {{\n"
        "  override fun apply(target: Project) {\n" + body + "\n  }\n}",
    )


def test_real_feature_plugin_supplies_two_project_dependencies():
    graph = load_dependencies(REAL)
    edges = graph.implicit_edges
    assert [(edge.source, edge.target) for edge in edges] == [
        (":feature:portscan", ":core:billing"),
        (":feature:portscan", ":core:ui"),
    ]
    assert all(edge.plugin_id == "netlens.android.feature" for edge in edges)
    assert all(edge.plugin_class == "AndroidFeatureConventionPlugin" for edge in edges)
    assert all(edge.implicit and edge.configuration == "implementation" for edge in edges)
    assert not any(issue.field == "includeBuild" for issue in graph.issues)


@pytest.mark.parametrize(
    "application",
    [
        'plugins { id("demo.first") }',
        "plugins { alias(libs.plugins.demo.first) }",
        'apply(plugin = "demo.first")',
        'apply plugin: "demo.first"',
    ],
)
def test_alias_and_literal_application_with_composition_and_provenance(tmp_path, application):
    plugin_build(tmp_path, 'pluginManagement { includeBuild("build-logic") }')
    write(tmp_path, "app/build.gradle.kts", application)
    write(tmp_path, "gradle/libs.versions.toml", '[plugins]\ndemo-first = { id = "demo.first" }')
    source(
        tmp_path,
        "First",
        """
    with(target) {
      pluginManager.apply("demo.second")
      dependencies {
        add("api", project(":core"))
        "androidTestImplementation"(project(":test"))
      }
    }
    """,
    )
    second = source(
        tmp_path,
        "Second",
        """
    target.dependencies {
      debugImplementation(project(":core"))
    }
    api(project(":test"))
    """,
    )
    graph = load_dependencies(tmp_path)
    edges = graph.implicit_edges
    assert [
        (edge.target, edge.configuration, edge.test_only, edge.plugin_id) for edge in edges
    ] == [
        (":core", "api", False, "demo.first"),
        (":test", "androidTestImplementation", True, "demo.first"),
        (":core", "debugImplementation", False, "demo.second"),
    ]
    assert edges[-1].file == second.relative_to(tmp_path).as_posix()
    assert edges[-1].line == 6
    assert edges[-1].plugin_class == "demo.Second"
    assert not graph.issues


def test_computed_plugin_arguments_are_warned_and_cycle_is_bounded(tmp_path):
    plugin_build(tmp_path)
    write(tmp_path, "app/build.gradle.kts", 'plugins { id("demo.first"); id(computedId) }')
    source(
        tmp_path,
        "First",
        """
    apply(plugin = "demo.second")
    dependencies {
      add(config, project(":core"))
      api(project(somePath))
      if (condition) { api(project(":test")) }
    }
    """,
    )
    source(
        tmp_path,
        "Second",
        """
    pluginManager.apply("demo.first")
    pluginManager.apply(dynamicId)
    dependencies { api(project(":core")) }
    """,
    )
    graph = load_dependencies(tmp_path)
    assert [(edge.target, edge.plugin_id) for edge in graph.implicit_edges] == [
        (":core", "demo.second")
    ]
    assert any("cycle" in issue.message for issue in graph.issues)
    assert sum(issue.field == "dependencies" for issue in graph.issues) == 3
    assert all(issue.severity == "warning" and "line " in issue.message for issue in graph.issues)


@pytest.mark.parametrize(
    "settings",
    [
        'includeBuild("../outside")',
        'includeBuild("build-logic" + suffix)',
        'if (condition) { includeBuild("build-logic") }',
        'if (condition)\nincludeBuild("build-logic")',
        'pluginManagement { if (condition)\nincludeBuild("build-logic") }',
    ],
)
def test_unsupported_include_build_is_never_followed(tmp_path, settings):
    plugin_build(tmp_path, settings)
    write(tmp_path, "app/build.gradle.kts", 'plugins { id("demo.first") }')
    source(tmp_path, "First", 'dependencies { api(project(":core")) }')
    graph = load_dependencies(tmp_path)
    assert graph.implicit_edges == ()
    assert any(
        issue.path == "settings.gradle.kts"
        and issue.field == "includeBuild"
        and issue.severity == "warning"
        and issue.message.startswith("line ")
        for issue in graph.issues
    )


def test_symlinked_include_build_and_sources_are_never_read(tmp_path):
    plugin_build(tmp_path, 'includeBuild("linked")\nincludeBuild("build-logic")')
    (tmp_path / "linked").symlink_to(tmp_path / "build-logic", target_is_directory=True)
    write(tmp_path, "app/build.gradle.kts", 'plugins { id("demo.first") }')
    original = source(tmp_path, "Outside", 'dependencies { api(project(":core")) }')
    denied = original.with_name("First.kt")
    denied.symlink_to(original)
    graph = load_dependencies(tmp_path)
    assert graph.implicit_edges == ()
    assert any(
        issue.field == "includeBuild" and "line 1" in issue.message for issue in graph.issues
    )
    assert any("symlink" in issue.message for issue in graph.issues)


@pytest.mark.parametrize(
    "body, message",
    [
        ("x" * (256 * 1024 + 1), "file exceeds"),
        ("x" + "(" * 65 + ")" * 65, "nesting limit exceeded"),
    ],
    ids=["size", "delimiter-depth"],
)
def test_invalid_plugin_source_is_bounded_and_other_plugins_are_read(tmp_path, body, message):
    plugin_build(tmp_path)
    write(tmp_path, "app/build.gradle.kts", 'plugins { id("demo.first"); id("demo.second") }')
    source(tmp_path, "First", body)
    source(tmp_path, "Second", 'dependencies { api(project(":core")) }')
    graph = load_dependencies(tmp_path)
    assert [edge.plugin_id for edge in graph.implicit_edges] == ["demo.second"]
    assert any(
        issue.path.endswith("First.kt") and message in issue.message for issue in graph.issues
    )


def test_invalid_path_with_control_characters_is_not_echoed(tmp_path):
    plugin_build(tmp_path, 'includeBuild("\x1b[31moutside")')
    graph = load_dependencies(tmp_path)
    assert graph.implicit_edges == ()
    assert all(
        "outside" not in issue.message and "\x1b" not in issue.message for issue in graph.issues
    )
    assert any(issue.field == "includeBuild" for issue in graph.issues)


def test_control_characters_in_plugin_source_are_never_echoed(tmp_path):
    plugin_build(tmp_path)
    write(tmp_path, "app/build.gradle.kts", 'plugins { id("demo.first") }')
    source(tmp_path, "First", 'dependencies { add("implementation\x1b", project(":core")) }')
    graph = load_dependencies(tmp_path)
    assert graph.implicit_edges == ()
    issue = next(issue for issue in graph.issues if issue.field == "dependencies")
    assert issue.path.endswith("First.kt")
    assert issue.message.startswith("line 4:") and "\x1b" not in issue.message


def test_long_plugin_chain_warns_at_depth_limit(tmp_path):
    plugin_build(tmp_path)
    registrations = []
    for i in range(70):
        plugin_id = "demo.first" if i == 0 else f"demo.plugin{i}"
        registrations.append(
            f'register("p{i}") {{ id = "{plugin_id}"; implementationClass = "demo.Plugin{i}" }}'
        )
        source(tmp_path, f"Plugin{i}", f'pluginManager.apply("demo.plugin{i + 1}")')
    write(
        tmp_path,
        "build-logic/convention/build.gradle.kts",
        "gradlePlugin { plugins { " + "\n".join(registrations) + " } }",
    )
    write(tmp_path, "app/build.gradle.kts", 'plugins { id("demo.first") }')
    graph = load_dependencies(tmp_path)
    assert any("depth limit" in issue.message for issue in graph.issues)


def test_other_kotlin_locations_under_src_main_are_read(tmp_path):
    plugin_build(tmp_path)
    write(tmp_path, "app/build.gradle.kts", 'plugins { id("demo.first") }')
    first = source(tmp_path, "First", 'dependencies { api(project(":core")) }')
    first.rename(first.parents[2] / "First.kt")
    assert [edge.target for edge in load_dependencies(tmp_path).implicit_edges] == [":core"]


@pytest.mark.parametrize(
    "application",
    [
        'plugins { receiver.id("demo.first") }',
        'plugins { if (false)\n id("demo.first") }',
        'plugins { id("demo.first") apply false }',
        'plugins { id("demo.first").apply(false) }',
        'plugins { id("demo.first").version("1").apply(false) }',
        "apply plugin:",
        'apply plugin: "demo.first" + suffix',
    ],
)
def test_non_application_never_activates_plugin(tmp_path, application):
    plugin_build(tmp_path)
    write(tmp_path, "app/build.gradle.kts", application)
    source(tmp_path, "First", 'dependencies { api(project(":core")) }')
    assert load_dependencies(tmp_path).implicit_edges == ()


def test_application_is_limited_to_static_apply_block(tmp_path):
    plugin_build(tmp_path)
    write(tmp_path, "app/build.gradle.kts", 'plugins { id("demo.first") }')
    write(
        tmp_path,
        "build-logic/convention/src/main/kotlin/demo/First.kt",
        """
package demo
class First : Plugin<Project> {
    override fun apply(target: Project) = with(target) {
        if (false) {
            dependencies { api(project(":test")) }
            pluginManager.apply("demo.second")
        }
        dependencies { api(project(":core")) }
    }
    fun helper() {
        dependencies { api(project(":test")) }
    }
}
""",
    )
    source(tmp_path, "Second", 'dependencies { api(project(":test")) }')
    graph = load_dependencies(tmp_path)
    assert [(edge.target, edge.plugin_id) for edge in graph.implicit_edges] == [
        (":core", "demo.first")
    ]
    assert any(
        issue.path.endswith("First.kt") and "unsupported" in issue.message for issue in graph.issues
    )


def test_catalog_plugin_short_notation(tmp_path):
    plugin_build(tmp_path)
    write(tmp_path, "app/build.gradle.kts", "plugins { alias(libs.plugins.demo.first) }")
    write(tmp_path, "gradle/libs.versions.toml", '[plugins]\ndemo-first = "demo.first:1.0"')
    source(tmp_path, "First", 'dependencies { api(project(":core")) }')
    assert [edge.target for edge in load_dependencies(tmp_path).implicit_edges] == [":core"]


def test_walk_does_not_silently_stop_at_entry_budget(tmp_path):
    plugin_build(tmp_path)
    for i in range(999):
        write(tmp_path, f"build-logic/file{i}", "")
    graph = load_dependencies(tmp_path)
    assert any("file probe limit" in issue.message for issue in graph.issues)


def test_unrelated_apply_overload_is_not_followed(tmp_path):
    plugin_build(tmp_path)
    write(tmp_path, "app/build.gradle.kts", 'plugins { id("demo.first") }')
    write(
        tmp_path,
        "build-logic/convention/src/main/kotlin/demo/First.kt",
        """
package demo
class First : Plugin<Project> {
    override fun apply(project: org.gradle.api.Project) {
        project.dependencies { api(project(":core")) }
    }
    fun apply(project: Project, ignored: Boolean) {
        project.dependencies { api(project(":test")) }
    }
}
""",
    )
    assert [edge.target for edge in load_dependencies(tmp_path).implicit_edges] == [":core"]


def test_nested_module_plugin_application_is_reported_without_being_followed(tmp_path):
    plugin_build(tmp_path)
    write(tmp_path, "app/build.gradle.kts", 'plugins { if (false) { id("demo.first") } }')
    source(tmp_path, "First", 'dependencies { api(project(":core")) }')
    graph = load_dependencies(tmp_path)
    assert graph.implicit_edges == ()
    assert any(
        issue.path == "app/build.gradle.kts" and issue.field == "plugins" for issue in graph.issues
    )
