<!-- Generated: 2026-11-23 | Files scanned: 47 | Token estimate: ~900 -->
# Backend: CLI and web routes

Entry `etat-major = etat_major.cli:main` (cli.py:324). Dispatch dict maps command -> handler; exit codes via `cli_json.py` (OK / PROBLEMS / USAGE). `--format text|json` on trace, index, decisions list, progress, workspace validate, components, gradle.

## CLI: command -> handler -> main callees
```
trace <ref>            cli._trace            parse_ref, load_workspace, load_graph/load_wiring (_load_indexes),
                                             components.load_*, trace.trace_feature, render.render_trace
decisions list         cli._decisions_list   load_workspace
index                  cli._index            repo_index.load_repo_index
progress               cli._progress         evidence.load_progress -> derive_progress, evidence_git.load_git,
                                             evidence_records.load_prs/load_releases, meute; evidence_render
workspace validate     cli._workspace_validate  load_workspace(validate_all=True)
research brief|import  cli._research         research_brief.write_brief | research_import.import_answer
gradle deps|drift      gradle_cli.run_gradle gradle.load_dependencies; drift: floorplan.load_graph(architecture=True),
                                             trail.load_wiring, gradle_drift.compare_dependencies
components validate|map|coverage|seed
                       components_cli.run_components  components.load_component_workspace; coverage: floorplan.load_graph;
                                             seed: components_seed.seed_components, component_paths
floorplan scan|build|refresh
                       floorplan_runner.run_floorplan_cli -> run_floorplan (node subprocess), renames reconcile
serve                  web.run_serve         planning_view.load_planning_view, uvicorn (127.0.0.1)
```
Errors: `TaskFileError` (file + field) -> message, no tracebacks.

## Web (web.py `create_app`, FastAPI, optional extra)
Host allowlist 127.0.0.1/localhost; docs/openapi off; CSP `default-src 'none'`, no-store.
```
GET /, /planning   snapshots.responses[0]  <- planning_view.load_planning_view -> planning_html.render
GET /fleet         responses[1]            <- planning_html.render_fleet
GET /project.json  responses[2]            <- web._json_snapshot (asdict of PlanningView)
GET /understand    understand_html.register -> _selection -> render(nav)   (query params; 400 invalid, 404 no snapshot)
GET /refresh, /fleet-refresh  (token-gated, 403 otherwise)  -> _Snapshots.update(reload) re-runs load_planning_view
```
`load_planning_view` loads workspace, components, indexes, prs, releases, git, meute, manual review, execution links, then `derive_progress`, `understand.build`.

## Key files (lines)
cli.py 372, web.py 268, planning_view.py 392, planning_html.py 369, understand_html.py 272, understand.py 205,
evidence.py 399, workspace.py 397, taskfile.py 399, components.py 386, trail_runner.py 380, floorplan_runner.py 398,
repo_index.py 341, trace.py 249, cli_json.py 145, gradle_cli.py 108, components_cli.py 210.
