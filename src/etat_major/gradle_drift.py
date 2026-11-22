"""Compare Gradle declarations with repository-relative recorded evidence."""

from collections import Counter, defaultdict
from dataclasses import dataclass

from etat_major.floorplan import ArchitectureDocument
from etat_major.gradle import Declaration, GradleDependencies
from etat_major.gradle_parse import MAX_DEPTH
from etat_major.text_safety import public_text, safe
from etat_major.trail import SymbolIndex

type Pair = tuple[str, str]
type EvidenceKey = tuple[str, str, str, str | None]
type EvidenceCounts = Counter[tuple[EvidenceKey, bool]]

_TEST_SOURCE_SETS = frozenset({"test", "androidTest", "testFixtures"})
_PRODUCTION_CONFIGURATIONS = frozenset({"implementation", "api"})
_TIER_DETAILS = {
    "declared_and_used": (1, "An explicit declaration covers recorded evidence"),
    "declared_implicit": (1, "A convention plugin declaration covers recorded evidence"),
    "import_backed": (1, "A Floorplan import originates outside the test source sets"),
    "test_only": (2, "All recorded evidence originates in test source sets"),
    "call_only": (3, "Trail records symbol links without a non-test Floorplan import"),
    "build_time_configuration": (3, "An advisory declaration has no recorded evidence"),
    "unused_candidate": (1, "An explicit production declaration has no recorded evidence"),
}


@dataclass(frozen=True)
class Evidence:
    layer: str
    relation: str
    provenance: str
    confidence: str | None
    count: int


@dataclass(frozen=True)
class DriftEdge:
    source: str
    target: str
    declarations: tuple[Declaration, ...]
    evidence_count: int
    evidence: tuple[Evidence, ...]
    tier: str
    rank: int
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class DriftSummary:
    declared_and_used: int
    declared_implicit: int
    import_backed: int
    test_only: int
    call_only: int
    build_time_configuration: int
    unused_candidate: int
    modules_only_declared: int
    modules_only_observed: int


@dataclass(frozen=True)
class Drift:
    declared_and_used: tuple[DriftEdge, ...]
    declared_but_unused: tuple[DriftEdge, ...]
    used_but_undeclared: tuple[DriftEdge, ...]
    modules_only_declared: tuple[str, ...]
    modules_only_observed: tuple[str, ...]
    declared_implicit: tuple[DriftEdge, ...]
    call_only: tuple[DriftEdge, ...]
    summary: DriftSummary

    @property
    def has_differences(self) -> bool:
        return bool(self.summary.import_backed or self.summary.unused_candidate)


def _module_id(directory: str) -> str:
    return ":" + safe(public_text(directory)).replace("/", ":")


def _source_directory(file: str) -> str | None:
    prefix, slash, _ = file.partition("/src/")
    return prefix if slash else None


def _owner(file: str, directories: dict[str, str]) -> str | None:
    parts = file.split("/", MAX_DEPTH + 1)
    for depth in reversed(range(1, len(parts))):
        directory = "/".join(parts[:depth])
        if directory in directories:
            return directories[directory]
    return None


def _observed(
    declared: GradleDependencies,
    floorplan: ArchitectureDocument,
    trail: SymbolIndex | None,
) -> tuple[dict[str, str], set[str]]:
    files = {file.path for file in floorplan.files}
    if trail:
        files.update(symbol.path for symbol in trail.symbols)
    directories = {m.directory: m.id for m in declared.modules}
    scopes = trail.module_scopes if trail else ()
    for prefix in scopes:
        directories.setdefault(prefix, _module_id(prefix))
    owners = {}
    for file in files:
        owner = _owner(file, directories)
        directory = _source_directory(file) if owner is None else None
        if directory is not None:
            owner = _module_id(directory)
        if owner is None:
            owner = directories.get("")
        if owner is not None:
            owners[file] = owner
    observed = set(owners.values()) | {directories[scope] for scope in scopes}
    return owners, observed


def _count(
    evidence: dict[Pair, EvidenceCounts],
    endpoints: tuple[str, str],
    owners: dict[str, str],
    key: EvidenceKey,
) -> None:
    source, target = map(owners.get, endpoints)
    if source is not None and target is not None and source != target:
        test_source = not _TEST_SOURCE_SETS.isdisjoint(endpoints[0].split("/"))
        evidence[source, target][key, test_source] += 1


def _evidence(
    floorplan: ArchitectureDocument,
    trail: SymbolIndex | None,
    owners: dict[str, str],
) -> dict[Pair, EvidenceCounts]:
    evidence: dict[Pair, EvidenceCounts] = defaultdict(Counter)
    for link in floorplan.links:
        if link.kind == "import" and link.source.startswith("f:") and link.target.startswith("f:"):
            _count(
                evidence,
                (link.source[2:], link.target[2:]),
                owners,
                ("floorplan", "import", link.provenance, None),
            )
    if trail:
        paths = {symbol.id: symbol.path for symbol in trail.symbols}
        for edge in trail.edges:
            if (
                edge.relation in {"calls", "extends"}
                and edge.source in paths
                and edge.target in paths
            ):
                _count(
                    evidence,
                    (paths[edge.source], paths[edge.target]),
                    owners,
                    ("trail", edge.relation, edge.provenance, safe(public_text(edge.confidence))),
                )
    return evidence


def _tier(
    explicit: tuple[Declaration, ...], implicit: tuple[Declaration, ...], counts: EvidenceCounts
) -> str:
    if not counts:
        if any(d.configuration in _PRODUCTION_CONFIGURATIONS and not d.test_only for d in explicit):
            return "unused_candidate"
        return "build_time_configuration"
    if explicit:
        return "declared_and_used"
    if implicit:
        return "declared_implicit"
    if any(key[0] == "floorplan" and not test_source for key, test_source in counts):
        return "import_backed"
    if all(test_source for _, test_source in counts):
        return "test_only"
    return "call_only"


def _drift_edge(
    pair: Pair,
    explicit: tuple[Declaration, ...],
    implicit: tuple[Declaration, ...],
    counts: EvidenceCounts,
) -> DriftEdge:
    evidence: Counter[EvidenceKey] = Counter()
    for (key, _), count in counts.items():
        evidence[key] += count
    items = tuple(Evidence(*key, count) for key, count in sorted(evidence.items()))
    tier = _tier(explicit, implicit, counts)
    rank, reason = _TIER_DETAILS[tier]
    return DriftEdge(
        *pair, explicit + implicit, sum(evidence.values()), items, tier, rank, (reason,)
    )


def _by_pair(edges: tuple[Declaration, ...]) -> dict[Pair, list[Declaration]]:
    declarations: dict[Pair, list[Declaration]] = defaultdict(list)
    for edge in edges:
        declarations[edge.source, edge.target].append(edge)
    return declarations


def compare_dependencies(
    declared: GradleDependencies,
    floorplan: ArchitectureDocument,
    trail: SymbolIndex | None = None,
) -> Drift:
    """Compare ordered module pairs, keeping every configuration and evidence source."""
    owners, observed = _observed(declared, floorplan, trail)
    evidence = _evidence(floorplan, trail, owners)
    explicit = _by_pair(declared.edges)
    implicit = _by_pair(declared.implicit_edges)
    by_tier: dict[str, list[DriftEdge]] = defaultdict(list)
    unused = []
    for pair in sorted(explicit.keys() | implicit.keys() | evidence.keys()):
        row = _drift_edge(
            pair,
            tuple(explicit.get(pair, ())),
            tuple(implicit.get(pair, ())),
            evidence.get(pair, Counter()),
        )
        by_tier[row.tier].append(row)
        if not row.evidence:
            unused.append(row)
    declared_modules = {module.id for module in declared.modules}
    only_declared = tuple(sorted(declared_modules - observed))
    only_observed = tuple(sorted(observed - declared_modules))
    return Drift(
        declared_and_used=tuple(by_tier["declared_and_used"]),
        declared_but_unused=tuple(unused),
        used_but_undeclared=tuple(by_tier["import_backed"] + by_tier["test_only"]),
        modules_only_declared=only_declared,
        modules_only_observed=only_observed,
        declared_implicit=tuple(by_tier["declared_implicit"]),
        call_only=tuple(by_tier["call_only"]),
        summary=DriftSummary(
            **{tier: len(by_tier[tier]) for tier in _TIER_DETAILS},
            modules_only_declared=len(only_declared),
            modules_only_observed=len(only_observed),
        ),
    )
