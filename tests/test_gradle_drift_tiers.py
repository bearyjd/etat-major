from dataclasses import asdict

import pytest

from etat_major.floorplan import ArchitectureDocument
from etat_major.gradle import Declaration, GradleDependencies, Module
from etat_major.gradle_drift import compare_dependencies
from etat_major.trail import Symbol, SymbolCoverage, SymbolEdge, SymbolIndex

APP = "app/src/main/App.kt"
TEST = "app/src/test/Test.kt"
CORE = "core/src/main/Core.kt"


def _dependencies(*edges, implicit_edges=()):
    modules = tuple(Module(f":{name}", name) for name in ("app", "core"))
    if implicit_edges:
        return GradleDependencies(modules, edges, (), implicit_edges=implicit_edges)
    return GradleDependencies(modules, edges, ())


def _graph(*imports, files=()):
    paths = set(files) | {path for pair in imports for path in pair}
    return ArchitectureDocument.model_validate(
        {
            "nodes": [],
            "files": [{"p": path} for path in sorted(paths)],
            "links": [{"a": f"f:{a}", "b": f"f:{b}", "k": "import"} for a, b in imports],
        }
    )


def _trail(*calls):
    paths = {path for pair in calls for path in pair}
    return SymbolIndex(
        tuple(Symbol(path, "function", path, 1, 1) for path in sorted(paths)),
        tuple(
            SymbolEdge(source=a, target=b, relation="calls", confidence="extracted")
            for a, b in calls
        ),
        SymbolCoverage((), {}, {}, frozenset(), frozenset(), {}, ()),
    )


def _declaration(configuration, *, test_only=False):
    return Declaration(":app", ":core", configuration, test_only, "app/build.gradle.kts", 1)


def test_one_production_import_outranks_44_trail_calls_and_test_evidence():
    imports = ((APP, CORE), (TEST, "alpha-test/src/main/Alpha.kt"))
    graph = _graph(*imports)
    trail = _trail(*[(APP, "calls/src/main/Calls.kt")] * 44)
    result = compare_dependencies(_dependencies(), graph, trail)

    assert [(row.target, row.tier, row.rank) for row in result.used_but_undeclared] == [
        (":core", "import_backed", 1),
        (":alpha-test", "test_only", 2),
    ]
    (call,) = result.call_only
    assert (call.target, call.tier, call.rank, call.evidence_count) == (
        ":calls",
        "call_only",
        3,
        44,
    )
    assert call.reasons and result.used_but_undeclared[0].reasons
    assert result.has_differences
    assert result == compare_dependencies(_dependencies(), _graph(*reversed(imports)), trail)
    assert asdict(result.summary) == {
        "declared_and_used": 0,
        "declared_implicit": 0,
        "import_backed": 1,
        "test_only": 1,
        "call_only": 1,
        "build_time_configuration": 0,
        "unused_candidate": 0,
        "modules_only_declared": 0,
        "modules_only_observed": 2,
    }


@pytest.mark.parametrize("source_set", ["test", "androidTest", "testFixtures"])
def test_all_evidence_from_test_source_sets_is_advisory(source_set):
    source = f"app/src/{source_set}/Test.kt"
    result = compare_dependencies(_dependencies(), _graph((source, CORE)), _trail((source, CORE)))

    (row,) = result.used_but_undeclared
    assert (row.tier, row.evidence_count) == ("test_only", 2)
    assert not result.has_differences


def test_test_import_does_not_raise_production_trail_calls_to_import_backed():
    result = compare_dependencies(_dependencies(), _graph((TEST, CORE)), _trail((APP, CORE)))

    assert result.used_but_undeclared == ()
    (row,) = result.call_only
    assert row.evidence_count == 2
    assert not result.has_differences


def test_test_path_segments_only_apply_to_source():
    source, target = "app/src/contest/Component.kt", "core/src/test/Test.kt"
    result = compare_dependencies(_dependencies(), _graph((source, target)))

    assert result.used_but_undeclared[0].tier == "import_backed"


def test_preserves_combined_counts_for_imports_from_different_source_sets():
    result = compare_dependencies(_dependencies(), _graph((APP, CORE), (TEST, CORE)))

    (row,) = result.used_but_undeclared
    assert (row.tier, row.evidence_count) == ("import_backed", 2)
    (evidence,) = row.evidence
    assert evidence.count == 2


@pytest.mark.parametrize(
    "configuration",
    [
        "baselineProfile",
        "ksp",
        "kapt",
        "annotationProcessor",
        "runtimeOnly",
        "compileOnly",
        "lintChecks",
        "debugImplementation",
        "releaseImplementation",
        "customConfiguration",
    ],
)
def test_configurations_outside_production_implementation_and_api_are_advisory(configuration):
    result = compare_dependencies(_dependencies(_declaration(configuration)), _graph())

    (row,) = result.declared_but_unused
    assert row.tier == "build_time_configuration"
    assert not result.has_differences


def test_only_explicit_production_implementation_and_api_are_unused_candidates():
    graph = _graph(files=(APP, CORE))
    baseline = _declaration("baselineProfile")
    fixtures = _declaration("implementation", test_only=True)
    advisory = compare_dependencies(_dependencies(baseline, fixtures), graph)
    candidate = compare_dependencies(_dependencies(baseline, fixtures, _declaration("api")), graph)

    assert advisory.declared_but_unused[0].tier == "build_time_configuration"
    assert advisory.summary.build_time_configuration == 1
    assert not advisory.has_differences
    assert candidate.declared_but_unused[0].tier == "unused_candidate"
    assert candidate.summary.unused_candidate == 1
    assert candidate.has_differences


def test_implicit_declarations_cover_evidence_and_remain_visible_without_evidence():
    from etat_major.gradle import ImplicitDeclaration

    implicit = ImplicitDeclaration(
        ":app",
        ":core",
        "implementation",
        False,
        "plugins/Convention.kt",
        3,
        plugin_id="example.convention",
        plugin_class="ConventionPlugin",
    )
    declared = _dependencies(implicit_edges=(implicit,))
    covered = compare_dependencies(declared, _graph((APP, CORE)))
    advisory = compare_dependencies(declared, _graph(files=(APP, CORE)))
    explicit = _declaration("implementation")
    candidate = compare_dependencies(
        _dependencies(explicit, implicit_edges=(implicit,)),
        _graph(files=(APP, CORE)),
    )
    covered_by_both = compare_dependencies(
        _dependencies(explicit, implicit_edges=(implicit,)), _graph((APP, CORE))
    )

    assert covered.used_but_undeclared == covered.declared_and_used == ()
    (row,) = covered.declared_implicit
    assert row.declarations == (implicit,)
    assert row.tier == "declared_implicit"
    assert covered.summary.declared_implicit == 1
    assert not covered.has_differences
    assert advisory.declared_but_unused[0].declarations == (implicit,)
    assert not advisory.has_differences
    assert candidate.declared_but_unused[0].tier == "unused_candidate"
    assert candidate.has_differences
    assert covered_by_both.declared_implicit == ()
    assert covered_by_both.declared_and_used[0].declarations == (explicit, implicit)


def test_module_only_deltas_are_advisory_and_order_independent():
    files = (APP, "zeta/src/main/Zeta.kt", "beta/src/main/Beta.kt")
    result = compare_dependencies(_dependencies(), _graph(files=files))
    reversed_result = compare_dependencies(_dependencies(), _graph(files=reversed(files)))

    assert result == reversed_result
    assert result.modules_only_declared == (":core",)
    assert result.modules_only_observed == (":beta", ":zeta")
    assert not result.has_differences
