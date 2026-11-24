"""Measure recorded Floorplan and Trail files: size, counts, load and index-build seconds."""

import argparse
import json
import sys
from pathlib import Path
from statistics import median
from time import perf_counter

from etat_major.floorplan import load_architecture
from etat_major.repo_index import load_repo_index
from etat_major.trail import load_wiring

DEFAULT_RUNS = 5


def _kind(path: Path) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ValueError(f"{path.name}: cannot read file (missing or not valid JSON)") from None
    if not isinstance(data, dict):
        raise ValueError(f"{path.name}: JSON: expected an object")
    return "floorplan" if "schema" in data else "trail"


def _timed(function, runs: int) -> tuple[object, dict[str, float | int]]:
    seconds = []
    result = None
    for _ in range(runs):
        start = perf_counter()
        result = function()
        seconds.append(perf_counter() - start)
    return result, {"runs": runs, "min": min(seconds), "median": float(median(seconds))}


def _recording(path: Path, kind: str, runs: int) -> dict[str, object]:
    base: dict[str, object] = {"file": path.name, "kind": kind, "bytes": path.stat().st_size}
    if kind == "floorplan":
        doc, seconds = _timed(lambda: load_architecture(path), runs)
        counts = {"nodes": len(doc.nodes), "edges": len(doc.links), "files": len(doc.files)}
    else:
        index, seconds = _timed(lambda: load_wiring(path), runs)
        symbols = sum(1 for symbol in index.symbols if symbol.kind != "file")
        counts = {"nodes": len(index.symbols), "edges": len(index.edges), "symbols": symbols}
    return {**base, **counts, "load_seconds": seconds}


def measure(paths, runs: int = DEFAULT_RUNS) -> dict[str, object]:
    """Return a report for each recording; an index build when a pair is given."""
    paths = [Path(p) for p in paths]
    kinds = [_kind(path) for path in paths]
    recordings = [_recording(path, kind, runs) for path, kind in zip(paths, kinds, strict=True)]
    graph = next((p for p, k in zip(paths, kinds, strict=True) if k == "floorplan"), None)
    trail = next((p for p, k in zip(paths, kinds, strict=True) if k == "trail"), None)
    build = None
    if graph and trail:
        _, build = _timed(lambda: load_repo_index(graph, trail), runs)
    return {"runs": runs, "recordings": recordings, "index_build_seconds": build}


def _text(report: dict[str, object]) -> str:
    lines = [f"runs: {report['runs']}"]
    for row in report["recordings"]:
        counts = " ".join(
            f"{k}={row[k]}" for k in ("nodes", "edges", "files", "symbols") if k in row
        )
        load = row["load_seconds"]
        lines.append(
            f"{row['file']} ({row['kind']}): bytes={row['bytes']} {counts} "
            f"load_min={load['min']:.6f}s load_median={load['median']:.6f}s"
        )
    build = report["index_build_seconds"]
    if build:
        stats = f"min={build['min']:.6f}s median={build['median']:.6f}s"
        lines.append(f"index build: {stats} (runs={build['runs']})")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recordings", nargs="+", type=Path)
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.runs < 1:
        parser.error("--runs must be at least 1")
    try:
        report = measure(args.recordings, args.runs)
    except (OSError, ValueError) as exc:
        message = str(exc)
        print(
            message if isinstance(exc, ValueError) else f"error: {exc.__class__.__name__}",
            file=sys.stderr,
        )
        return 2
    print(json.dumps(report, indent=2) if args.json else _text(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
