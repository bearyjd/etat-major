# Recorded-input limits and measurements

Status: small-sample only. **Large-repository limits are UNMEASURED.** Every figure below comes from the two checked-in trimmed recordings (about 100 KB each). Nothing near the 64 MiB cap has been measured. The full NetLens Floorplan and Trail recordings at the pinned revision are not in the repository; the maintainer must supply them (or authorize regenerating them) before any large-repository claim is made. Do not extrapolate the timings below to larger inputs.

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

## Still unmeasured

- Any recording larger than about 125 KB, including behavior near the 64 MiB cap.
- Memory use.
- Page rendering time and truncation frequency on a large index.
- Other machines and other Python versions.
