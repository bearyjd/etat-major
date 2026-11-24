<!-- Generated: 2026-11-23 | Files scanned: 47 | Token estimate: ~800 -->
# Architecture

Single Python 3.12 package `src/etat_major` (47 modules, ~10.8k lines). No database, no JS frontend, no network, no agent execution. Everything read from disk is untrusted (AGENTS.md).

## Data flow
```
RECORDED INPUTS (read-only files)         LOADERS                    MODELS / INDEXES            OUTPUT
Floorplan graph.json ------------------> floorplan.py -------+
Trail wiring.json ---------------------> trail.py -----------+--> repo_index.py (RepoIndex)    CLI text/json
prs.json, releases.json ---------------> evidence_records.py -+-> evidence.py (ProgressReport)  (cli.py, cli_json.py)
local git repo (bare, read-only) ------> evidence_git.py ----+    ^ uses planning.py board col
Meute snapshot YAML -------------------> meute.py -----------+
manual review / execution links YAML --> manual_review.py, execution_links.py
intent workspace (Markdown+YAML) ------> workspace.py + records.py, taskfile.py, planning.py
component YAML ------------------------> components.py (+component_paths, components_seed)
Gradle settings/build scripts ---------> gradle.py (+gradle_parse/_settings/_plugins) -> gradle_drift.py
                                                  |
        trace.py (feature -> research/decisions/arch)   planning_view.py (PlanningView)
                                                  |            |
                                  render.py / evidence_render.py   planning_html.py, understand.py
                                                               -> understand_html.py -> web.py (FastAPI)
```

## Layers
- Safe IO: `localfiles.py` (dir-fd opens, size-capped reads, atomic new-file writes), `text_safety.py` (`safe`, `public_text`), `refs.py`, `recorded_yaml.py`.
- Loaders/validators (pydantic, frozen models): see data.md.
- Derivation: `trace.py`, `evidence.py` (`derive_progress`), `repo_index.py`, `renames.py`, `overlay.py`, `gradle_drift.py`, `understand.py`.
- Presentation: CLI (`cli.py` + `components_cli.py`, `gradle_cli.py`), web (`web.py`, `planning_html.py`, `understand_html.py`), `cli_json.py` envelope.

## Subprocess users (only these import subprocess)
- `trail_runner.py` (`run_trail`) and `floorplan_runner.py` (`run_floorplan`): pinned tools, fixed args, no shell, scrubbed env, timeout, output cap, run in a caller-supplied throwaway copy. Floorplan runs Node on its bundle; CLI entry is `etat-major floorplan scan|build|refresh`. `run_trail` has no CLI subcommand (called only from `tests/test_trail_runner.py`).
- `renames.py` spawns read-only `git` (`--no-pager --bare`, fixed argv, no shell, `GIT_DIR` via fd); `evidence_git.py` imports `subprocess` but spawns through `renames._git_result`.

## Explicitly NOT present
- No network or HTTP client calls; no model/API calls; web server listens on 127.0.0.1 only.
- No agent start, queue or schedule (Codeman/Meute own that); no credential handling.
- No Gradle execution (scripts are parsed, never run); no `trail init`.
- Derived state (running/review/verified, drift tiers) computed, never written. Writes only: `research brief|import` (`write_new_text`), `components seed --out`, runner outputs inside the supplied copy.
