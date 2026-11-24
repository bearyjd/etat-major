# Contributing

Read [CLAUDE.md](../CLAUDE.md) for the hard constraints and [AGENTS.md](../AGENTS.md) for the working rules. [NEXT.md](NEXT.md) has the current state. Sections between `AUTO-GENERATED` markers come from `pyproject.toml`, `.github/workflows/ci.yml` and the CLI help; change those sources, then regenerate, instead of editing the text.

## Setup

Requires Python 3.12 or newer and Git. Node is needed only to run the pinned Floorplan wrapper.

```sh
pip install -e ".[dev,web]"
```

Without installing the package, prefix commands with `PYTHONPATH=src`.

<!-- AUTO-GENERATED: commands (source: etat-major --help) -->
## Commands

The `etat-major` console script (`etat_major.cli:main`) has these subcommands:

| Command | Description |
|---------|-------------|
| `trace` | print the research-to-code trace of a feature |
| `index` | export an architecture and symbol snapshot |
| `decisions` | decision records |
| `research` | prepare and import manual research |
| `gradle` | inspect recorded Gradle dependencies |
| `components` | inspect and seed component models |
| `floorplan` | run a pinned deterministic Floorplan step |
| `progress` | derive progress from local Git and recorded PRs |
| `workspace` | inspect an intent workspace |
| `serve` | serve one read-only Planning view on loopback |

Exit codes: 0 success, including warnings and unsourced findings; 1 missing, stale or gap trace items, or workspace validation issues; 2 usage errors, including unknown features and invalid workspaces or graphs. Run `etat-major <command> --help` for options. JSON output contracts are in [contracts/cli-json.md](contracts/cli-json.md).
<!-- /AUTO-GENERATED: commands -->

<!-- AUTO-GENERATED: checks (source: pyproject.toml, .github/workflows/ci.yml) -->
## Checks before a PR

CI runs these on Python 3.12, and each must pass on the PR's current head commit:

| Command | What it enforces |
|---------|------------------|
| `ruff check .` | lint rules E, F, I, B, UP, S; line length 100 |
| `ruff format --check .` | formatting |
| `pytest` | the test suite in `tests/`, with coverage of `etat_major` at or above 80% |
<!-- /AUTO-GENERATED: checks -->

## Tests

Write the failing test first, then the minimum code. Fixtures live in `tests/fixtures/`. Use real-shaped fixtures trimmed from real output, never invented ones. Run any new adapter on a real recorded artifact before calling it done. [REAL-DATA-SMOKE.md](REAL-DATA-SMOKE.md) describes the smoke runner (`scripts/real_data_smoke.py`), and [LIMITS.md](LIMITS.md) describes the measurement script (`scripts/measure_recordings.py`).

## Pull requests

- Keep each PR small and reviewable, with conventional commit messages and no attribution lines.
- Keep personal paths, hostnames, emails and keys out of the repository.
- A separate reviewer approves a change; the author does not approve their own.
- Merge only when CI is green on the exact head commit.
- Do not add dependencies. Any exception to the rules in `AGENTS.md` needs the maintainer's approval first.
