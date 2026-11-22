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


@dataclass(frozen=True)
class Drift:
    declared_and_used: tuple[DriftEdge, ...]
    declared_but_unused: tuple[DriftEdge, ...]
    used_but_undeclared: tuple[DriftEdge, ...]
    modules_only_declared: tuple[str, ...]
    modules_only_observed: tuple[str, ...]

    @property
    def has_differences(self) -> bool:
        return bool(
            self.declared_but_unused
            or self.used_but_undeclared
            or self.modules_only_declared
            or self.modules_only_observed
        )


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
    evidence: dict[Pair, Counter[EvidenceKey]],
    endpoints: tuple[str, str],
    owners: dict[str, str],
    key: EvidenceKey,
) -> None:
    source, target = map(owners.get, endpoints)
    if source is not None and target is not None and source != target:
        evidence[source, target][key] += 1


def _evidence(
    floorplan: ArchitectureDocument,
    trail: SymbolIndex | None,
    owners: dict[str, str],
) -> dict[Pair, Counter[EvidenceKey]]:
    evidence: dict[Pair, Counter[EvidenceKey]] = defaultdict(Counter)
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


def compare_dependencies(
    declared: GradleDependencies,
    floorplan: ArchitectureDocument,
    trail: SymbolIndex | None = None,
) -> Drift:
    """Compare ordered module pairs, keeping every configuration and evidence source."""
    owners, observed = _observed(declared, floorplan, trail)
    evidence = _evidence(floorplan, trail, owners)
    declarations: dict[Pair, list[Declaration]] = defaultdict(list)
    for declaration in declared.edges:
        declarations[declaration.source, declaration.target].append(declaration)
    used, unused, undeclared = [], [], []
    for pair in sorted(declarations.keys() | evidence.keys()):
        declared_items = tuple(declarations.get(pair, ()))
        counts = evidence.get(pair, Counter())
        items = tuple(Evidence(*key, count) for key, count in sorted(counts.items()))
        row = DriftEdge(*pair, declared_items, sum(counts.values()), items)
        if declared_items and items:
            used.append(row)
        elif declared_items:
            unused.append(row)
        else:
            undeclared.append(row)
    declared_modules = {module.id for module in declared.modules}
    return Drift(
        tuple(used),
        tuple(unused),
        tuple(undeclared),
        tuple(sorted(declared_modules - observed)),
        tuple(sorted(observed - declared_modules)),
    )
