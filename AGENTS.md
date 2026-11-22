# AGENTS.md: working in this repo (for Codex and other coding agents)

État-major is a self-hosted visual product-development workspace: research and decisions, how the code works, what to build, and evidence of progress. Read `CLAUDE.md` for the hard constraints, then `docs/NEXT.md` for the current state and the next tasks. The design is in `docs/VISUALIZATION-ARCHITECTURE.md` and `docs/TRACEABILITY.md`; the tool decisions are in `docs/TOOL-EVALUATION.md` and `docs/FLOORPLAN-PROOF.md`.

## Rules that are easy to get wrong
- Never store, proxy or pool Claude or Codex credentials. Never call a model or the network from product code.
- Git holds intent. Derived values (running, review, verified, drift tiers) are computed, never written to files. Only a human records a Decision, acceptance or "reviewed"; tooling writes only `proposed`, `unreviewed` or `draft`.
- Everything read from disk is untrusted: no symlink following, size caps, depth caps, escape printed text with `safe()`, turn every parse failure into a file-and-field error (no tracebacks). Never print absolute paths or remotes from third-party data.
- Never execute Gradle, Floorplan's model steps, `trail init`, or anything from a scanned repository. Git may be called only as a read-only subprocess with a fixed argument list and no shell.
- Do not add dependencies. There is no network in the dev environment.
- Keep personal paths, hostnames, emails and keys out of the repo.

## How to work
- Strict TDD: a failing test first, then the minimum code. Functions under 50 lines, files under 400, frozen models, error messages naming file and field.
- Gates before you call anything done: `pytest` (coverage at least 80%), `ruff check .`, `ruff format --check .`. CI runs these on Python 3.12.
- **Run every new adapter on a real artifact before calling it done.** Hand-made fixtures hid four bugs that a real Kotlin repository exposed in one afternoon (see `docs/FLOORPLAN-PROOF.md`). Use a real-shaped fixture trimmed from real output, never one you invented.
- Small commits with conventional messages and no attribution lines. Do not push, open PRs or merge unless the maintainer asks. When merging is asked for, CI must be green on the PR's current head commit.
- Separate authoring from review: do not approve your own change.
- Report only what you ran. Never claim a test passes unless you ran it.

## Commands
`etat-major trace | index | decisions list | research brief|import | gradle deps|drift | progress | workspace validate`. Most support `--format json` (see `docs/contracts/cli-json.md`).
