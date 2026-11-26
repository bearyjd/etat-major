# Handoff for current work

Updated 2026-11-23. Keep this file under 60 lines. Working rules are in `AGENTS.md` and `CLAUDE.md`.

## State

- The CLI reads local and recorded data for trace, index, decisions, research, progress, workspace validation and Gradle analysis. The reviewed [component model](contracts/components.md) provides validation, ownership, coverage and seed proposals.
- [Planning and Fleet](PLANNING.md) present read-only snapshots in a browser or sandboxed Codeman Web Tab. They include recorded Meute evidence, manual review evidence, copyable task handoffs and nonce-gated in-memory refresh. Planning preserves project diagnostics and shared diagnostic counts without exposing shared records.
- The read-only Discover page (`/discover`, see [Planning](PLANNING.md)) lists decisions (including rejected ones) and research with status, provenance and citation badges, a bounded `?q=` filter, a failed-record count and a stale-snapshot notice. It is absent from `/project.json`. The copyable brief/import panel and review UI remain.
- The [Trail runner](contracts/trail-adapter.md#building-a-fresh-local-graph) builds in disposable checkouts and validates `meta.version`. Real-data checks covered both `graft/` and `.trail/cache/`.
- The [Floorplan runner](FLOORPLAN-RUNNER.md) runs only deterministic `scan`, `build` and `refresh`. A real Android checkout copy retained all 80 authored component IDs across a rename and reported both paths.
- The read-only [Understand inspector](UNDERSTAND-MVP.md) (#23) shows components, files and symbols with coverage and provenance. The [real-data smoke runner](REAL-DATA-SMOKE.md) (#24) passed all 17 NetLens operations. At #24, CI ran 1,187 tests at 94.92% coverage on Python 3.12.
- An earlier local Alto pilot verified recorded evidence, snapshot refresh, Fleet and task handoff links. Isolated staging passed for both pilots on `9baf429`, but live services still run earlier releases. The current combined release has yet to be deployed or verified on Alto.

## Alto follow-ons

The [Alto delivery workflow](ALTO-MVP-DELIVERY.md) defines three separate PRs, with explicit rollout scope, acceptance and rollback for each.

1. Verify the exact merged read-only release live on Alto, then switch the pilots one at a time within the authorized scope: NetLens first, then Relais, rolling back a failed pilot. Staging passed; the live switch needs an authenticated Codeman browser (an unauthenticated probe returned HTTP 429). See the [runbook](ALTO-READ-ONLY-RUNBOOK.md).
2. Add native **Open session** in Codeman. The opaque Planning iframe can nominate an existing session. Selection requires a click in the opted-in Codeman parent's native UI and its access checks. Copyable links stay: a browser simulation showed a plain `#session=` link cannot select a session from the sandboxed tab (see the PR 2 decision). Require an exact owner match in multi-user mode and return to the exact Planning task.
3. Gate explicit Fleet actions in Meute. The first allowlisted action is `dismiss`. Start with a private authenticated top-level link and verify the actual sandboxed browser against Meute's Host, Fetch Metadata, write Origin and token checks before enabling iframe writes.

An optional Codeman theme is post-MVP.

## Understand and indexing

- The [Understand MVP](UNDERSTAND-MVP.md) is merged. Remaining acceptance: repeat it with a human-reviewed component in a deployed Codeman Web Tab. Browser checks so far were local (phone and desktop widths, simulated opaque Web Tab, seeded component).
- Milestone 5: freshness, missing-input and oversize behavior is pinned by tests (#26). `scripts/measure_recordings.py` and [LIMITS](LIMITS.md) record small-sample figures from the trimmed recordings. Full NetLens recordings (about 8.8 MB, revision `5188ca6`) were also measured. Behavior near the 64 MiB cap stays unmeasured, so the milestone is only partly done.
- `export understand --json` follows the [Understand export contract](contracts/understand-export.md). Its answers and shape choices are provisional until the maintainer decides. It has not been run on full real recordings, and its 4 MiB cap is unmeasured on large ones.
- Re-run the [real-data smoke runner](REAL-DATA-SMOKE.md) after changes to compare CLI results with pinned expectations.

**Subprocess exception for the runner wrappers only.** Each dedicated wrapper
may invoke its specified tool with fixed arguments, no shell, a scrubbed
environment with telemetry off and no credentials, a timeout and an output cap.
Run only inside a throwaway copy or worktree supplied by the caller. Tests use
fake executables. Real execution is limited to maintainers and real-data smoke
checks. The general execution ban in `AGENTS.md` still applies.

## Evidence limits and open questions

Floorplan's deterministic imports are useful as optional file evidence. Its model-written layer missed the accuracy target and its graph contract has no stability promise. Trail's Kotlin imports remain unresolved and cross-module calls are weak. Gradle drift on the real 33-module sample found 102 declared-and-used dependencies, 37 implicit through plugins, one hand-verified undeclared dependency and four hand-verified unused candidates. See [real-data proof](FLOORPLAN-PROOF.md).

Codeman credential isolation and account eligibility remain gates before adding a second user.
