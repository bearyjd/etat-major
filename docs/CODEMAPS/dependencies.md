<!-- Generated: 2026-11-23 | Files scanned: 6 | Token estimate: ~600 -->
# Dependencies

There is no `frontend.md`: no JS frontend exists. Web pages are server-rendered HTML strings (`planning_html.py`, `understand_html.py`).

## Python (pyproject.toml; requires >=3.12; build: setuptools>=68)
- Runtime: pydantic>=2, pyyaml>=6, jsonschema>=4, markdown-it-py>=3.
- Extra `web`: fastapi>=0.115, uvicorn>=0.34 (imported lazily in `web.py`; missing -> clear error in `run_serve`).
- Extra `dev`: httpx>=0.27, pytest>=8, pytest-cov>=5, ruff>=0.5.
- Gates: pytest with `--cov-fail-under=80`; ruff line-length 100, rules E,F,I,B,UP,S.
- Scripts: `etat-major = etat_major.cli:main`; helper scripts `scripts/real_data_smoke.py`, `scripts/measure_recordings.py`.

## External tools (pins.toml)
| Tool | Pin | May be executed by |
|------|-----|--------------------|
| Floorplan | tag `floorplan--v0.11.0`, commit `94f81b46...` (bundle digest checked in floorplan_runner) | `floorplan_runner.py` only, via `node` found with `shutil.which`, outside the copy |
| Trail | version `0.30.5` | `trail_runner.py` only; trusted absolute executable supplied by caller (not in checkout); validates `meta.version` |
| git | none | `evidence_git.py`, `renames.py` (read-only, fixed argv, no shell); `trail_runner` prepares scratch git metadata |
| node | none | `floorplan_runner.py` |
| Gradle | n/a | never executed (parsed text only) |
Floorplan/Trail output is otherwise consumed as recorded files by `floorplan.py` / `trail.py` (no exec).

## Bounding rules (AGENTS.md, CLAUDE.md)
- No credentials stored/proxied; no model or network calls from product code.
- No Gradle, Floorplan model steps, `trail init`, or code from scanned repos; git read-only.
- Runner exception (docs/NEXT.md): fixed args, no shell, scrubbed env/telemetry off, timeout, output cap, throwaway copy; tests use fake executables.
- No new dependencies without maintainer approval (web extra approved).
- Core must work with no session host, Meute, live Floorplan or agent.
