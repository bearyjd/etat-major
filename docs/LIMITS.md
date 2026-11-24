# Recorded-input limits and measurements

Status: two measured sizes, both far below the caps. **Behavior near the 64 MiB cap is UNMEASURED.** The first set of figures comes from the two checked-in trimmed recordings (about 100 KB each). The second comes from full NetLens recordings (about 8.8 MB combined) that are not in the repository. Do not extrapolate the timings to larger inputs.

## Enforced caps

| Limit | Value | Where |
|-------|-------|-------|
| Floorplan graph file | 64 MiB | `floorplan.py` `_LIMIT_MIB` |
| Trail wiring file | 64 MiB | `trail.py` `_LIMIT_MIB` |
| Source excerpt file | 256 KiB | `understand.py` `excerpt` |
| Understand page | 256 KiB (`LIMIT` in `understand_html.py`) | a longer page is replaced by a truncation notice |
| Rows per list page | 25 (`PAGE` in `understand.py`) | symbol and file lists are paged |

Files over a file cap are rejected with an error that names the file and the limit. These caps are enforced by tests; the measurements below are not.

## Tool pins

From `pins.toml`: Floorplan `floorplan--v0.11.0` (commit `94f81b463b7617e06d873ac71323ce71644c8399`), Trail `0.30.5`. The recordings are trimmed outputs of those versions. No tool was run to produce these figures; only État-major's loaders were timed.

## Observed figures (small sample)

Measured with Python 3.14.10 on Linux, one machine, one session. Timings are wall-clock seconds from `perf_counter`, 5 repeated runs, reporting min and median. Load time includes reading and validating the file. The index build loads both files and builds the repository index. Timings are indicative of nothing beyond these two small files.

Command (from the repository root):

```
PYTHONPATH=src python scripts/measure_recordings.py \
  tests/fixtures/floorplan/graph-real.json tests/fixtures/trail/wiring-kotlin.json
```

Output:

```
runs: 5
graph-real.json (floorplan): bytes=122938 nodes=34 edges=215 files=170 load_min=0.007527s load_median=0.007715s
wiring-kotlin.json (trail): bytes=101218 nodes=160 edges=20 symbols=144 load_min=0.005268s load_median=0.005330s
index build: min=0.016922s median=0.017230s (runs=5)
```

Counts: for Floorplan, `nodes` are components, `edges` are links and `files` are file entries. For Trail, `nodes` are all graph nodes, `symbols` are the nodes whose kind is not `file`, and `edges` are relations. Pass `--runs N` to change the repeat count and `--json` for machine-readable output. Output names files by base name only.

## Observed figures (full NetLens recordings)

The recordings were generated from a disposable export of NetLens revision `5188ca6725007bd663ce0eaa5ad2de9e460d26a0`, the revision pinned by the [full NetLens baseline](examples/netlens-real-data-smoke.json). Trail 0.30.5 produced the wiring through the Trail runner. Floorplan `floorplan--v0.11.0` produced the graph through the Floorplan runner (`scan`, then `build`) with the one-component `architecture.json` from [REAL-DATA-SMOKE](REAL-DATA-SMOKE.md). The recordings are private repository data and are not committed. File, node and edge counts equal the baseline's `index` expectations (716 files, 5,498 nodes, 14,386 edges).

Measured with Python 3.14.10 on Linux with 22 logical CPUs, one machine, one session, 5 repeated runs (min and median of `perf_counter`).

```
runs: 5
graph.json (floorplan): bytes=690916 nodes=2 edges=2200 files=716 load_min=0.051615s load_median=0.052512s
wiring.json (trail): bytes=8071092 nodes=5498 edges=14386 symbols=4783 load_min=0.189582s load_median=0.193425s
index build: min=0.674171s median=0.723427s (runs=5)
```

Against the trimmed recordings, the Trail file is about 80 times larger and loads about 36 times slower (median 0.193 s against 5.3 ms). The index build is about 42 times slower (median 0.72 s against 17 ms). These figures are one sample on one machine. The graph has two components because the supplied architecture input defines one; the model-written layer was not run.

## Still unmeasured

- Any recording larger than about 8 MB, including behavior near the 64 MiB cap.
- Memory use.
- Page rendering time and truncation frequency on a large index.
- Other machines and other Python versions.
