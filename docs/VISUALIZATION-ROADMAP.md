# État-major: roadmap

Status: plan. Replaces the six-phase roadmap in [SPEC.md](SPEC.md) and the earlier M0 to M8 list. Design: [VISUALIZATION-ARCHITECTURE.md](VISUALIZATION-ARCHITECTURE.md). Traceability model: [TRACEABILITY.md](TRACEABILITY.md). Tool decisions: [TOOL-EVALUATION.md](TOOL-EVALUATION.md).

Rules for every phase:

- Small, reviewable steps; tests written first for every contract change; coverage 80% or better on new code.
- A phase ends at its acceptance criteria. The next does not start before they pass.
- Build the smallest vertical slice first (Slice 1 below), not all phases at once.
- The core runs with no Codeman, no Meute and no live Floorplan or agent. Integrations come last.
- Nothing here stores or handles Claude or Codex credentials, and nothing sends data to ChatGPT or any model automatically.
- Reuse, do not rebuild: Floorplan for architecture maps, Trail for symbols, Git for intent.

## What exists today

- Scaffold, CI, and the task-file contract with a validator (`src/etat_major/taskfile.py`, `docs/contracts/`). It is reused in Phase 4.
- Decision record that Backlog.md's format is not adopted (`docs/spikes/phase1-spike.md`).
- Design documents: architecture, traceability model, tool evaluation, this roadmap.
- The CLI runs the trace, decision listing, recorded index, progress, workspace validation and manual research handoff. Trace, decisions, index, progress and validation support JSON.

## Phase 1: tool evaluation

**Status** — Mechanical tool evaluation is complete. Quality and cost of model-written Floorplan maps remain unverified.

Floorplan, Trail and Understand Anything inspected and run on copies; decision recorded in [TOOL-EVALUATION.md](TOOL-EVALUATION.md): Floorplan for the architecture layer, Trail for symbols, Understand Anything skipped as an indexer.

- **Acceptance (met):** mechanical (model-free) maps generated on two repositories; a blueprint built from a hand-written `plan.json` for a proposed feature; exported JSON inspected; integration feasibility and limits documented.
- **Still unverified:** the quality and per-refresh cost of an LLM-written Floorplan architecture layer. Verify on a real repository before relying on the architecture layer.

## Slice 1: the thinnest research-to-code trace

**Status** — The CLI trace, decision listing, record loaders and recorded Floorplan graph reader are implemented.

The first thing to build, before any web UI. It proves the model.

- **Depends on:** Phase 1.
- **Build:**
  - Loaders (with validators) for ResearchArtifact, Decision and Feature Markdown files (ArchitectureLinks are embedded in a Feature), following [TRACEABILITY.md](TRACEABILITY.md), plus an `etat-major` console script entry in `pyproject.toml`.
  - A reader for `floorplan/graph@1` that rejects any other schema string and strips the absolute root and remote (sanitize the recorded fixture before committing it).
  - `etat-major trace feature:<project>/<id>`: prints research, decisions, the feature's target components and files, and acceptance items (all open until Phase 5), each with provenance, marking missing links `unverified` or `gap`, and checking that each ArchitectureLink ref exists in the supplied graph.
- **Fixtures:** a small demo workspace with one research artifact, one decision (plus one rejected decision), one feature and a recorded `graph.json`. Tests parse the recorded files, never the network.
- **Done when:** on the demo workspace, `trace` prints the full chain; a `modifies` or `uses` ref that no longer exists is reported `stale` (a renamed file reads stale until Phase 2); a `new` ref with no matching file is reported `gap`; a finding without a source URL is flagged `unsourced`; `etat-major decisions list` shows rejected and postponed decisions alongside approved ones; `trace` also lists decisions that cite the same research.

## Phase 2: repository visualization

**Status** — Recorded Floorplan and Trail adapters, index joins, renames and overlays are implemented. Tool execution, the read-only API and the Understand screen remain.

- **Depends on:** Slice 1.
- **Build:**
  - Floorplan adapter: a pinned Floorplan commit, a CI check that a recorded `graph@1` still parses, optional invocation of only the deterministic `scan`, `build` and `refresh` scripts on a copy or worktree (never the model-backed steps, `serve.mjs` or the Ask bar), a rename reconciler using Git rename detection, and the planned-versus-built overlay computed by diffing a blueprint's `f:` ids against the current code map.
  - Trail adapter: build in a copy or worktree, read `wiring.json`, accept only `meta.version` 1, map `relation` and `confidence` to provenance, compute coverage and freshness against `HEAD`.
  - A join of the two layers by repository-relative path and revision; both layers and their provenance stay visible.
  - Read-only FastAPI JSON API and a first Understand screen: repository selector, file tree, symbol search, architecture map (start by embedding or linking Floorplan's generated viewer), function-level graph from Trail, node inspector, source viewer, coverage panel.
- **Decide here:** whether Floorplan's viewer is enough for architecture or État-major needs its own Cytoscape.js overlays; confirm library licenses.
- **Done when:** for one repository, you can pick a component, drill to a function, see callers and callees with provenance and coverage limits, and open source; a planned feature's blueprint shows planned, built and existing files; the page works on a phone-width screen with no Codeman, Meute or agent running.
- **Not promised:** `references`, `implements` or `lsp_*` edges (not observed), call edges for languages without full-fidelity support, or a module graph beyond directories and imports.

## Phase 3: research and feature model

**Status** — Research and feature loaders, relevant decision listing, manual brief/import and derived feature stages are implemented. Interactive decision search and the review UI remain.

- **Depends on:** Slice 1, and Phase 2 for the architecture links.
- **Build:** full loaders and the lifecycle (Idea to Released, plus Rejected and Postponed); the Decision search ("has this question been decided?"); the manual ChatGPT handoff, that is `research brief` (writes a prompt file after a redaction check) and `research import` (parses a pasted answer into an `unreviewed`, `ai-generated` draft, flags unsourced items, keeps URLs verbatim); the review step that marks an artifact `reviewed`.
- **Done when:** the importer and UI never write `approved`, `reviewed`, `decided_by`, `accepted_by` or `accepted_on` (tested); a brief is generated for a feature with no local paths, hostnames or keys; pasting a recorded sample answer yields a draft whose unsourced items are flagged; an unreviewed artifact cannot back an approved Decision; a stored Feature file cannot hold a derived lifecycle stage; nothing is sent anywhere automatically.

## Phase 4: planning visualization

**Status** — Task, vision and milestone models, dependency validation, board-state derivation and blueprint reading are implemented. The roadmap, board, diagram rendering and edit UI remain.

- **Depends on:** Phase 3.
- **Build:** extend the merged task contract (keep initiative, project, task; add optional `milestone`, `accepted_by`, `accepted_on`, `depends_on`, `targets`, and a link to a Feature; drop `budget_tokens`), the vision file, milestones with Now/Next/Later, dependency cycle detection, a Kanban (Draft, Ready, In Progress, Review, Done, Blocked), dependency view, Mermaid diagrams and wireframes rendered with sanitization, and Floorplan blueprints attached to features.
- **Edits:** the UI writes Markdown or YAML only into the configured intent workspace (a Git working tree) and shows the resulting diff. État-major commits and pushes nothing.
- **Done when:** the demo roadmap and board render from files; clicking a feature highlights its planned and existing components; a task naming a derived status is rejected; a dependency cycle is rejected; every edit is an uncommitted diff in the workspace.

## Phase 5: progress and traceability

**Status** — Progress derives evidence from local Git and recorded GitHub data and reports lifecycle stages, gaps and stale links. Live GitHub access and the progress UI remain.

- **Depends on:** Phases 3 and 4.
- **Build:** ProgressEvidence from Git and GitHub (link key `Task: <project>/<id>` in a commit trailer, branch or PR body; PRs, reviews, checks and releases through the user's own `gh` login); the evidence ladder; derived In Progress, Review, Implementing, Verified and Released; gap, stale and disconnected-work reports; comparison of the delivered result with the Feature's `outcome`.
- **Tests:** a fixture repository with scripted history and recorded `gh` JSON.
- **Done when:** each task and feature shows exactly the rungs its records prove and nothing more; a merged PR without `accepted_by` and `accepted_on` is shown in Review and not `done`; unimplemented, unverified and blocked requirements are listed; every completion claim links to a commit, PR, check, release or human acceptance, or reads `unverified`.

## Phase 6: optional integrations and hardening

**Status** — Codeman and Meute integrations, portfolio and mobile views, and deployment hardening remain planned.

- **Depends on:** Phases 2 to 5.
- **Meute (read-only):** parse `state/log` and `reports/**` directly into `generated` evidence and a summary; never call the per-report command that marks reports read. A run links to a task only if its commits carry the `Task:` trailer or its report names the task id. Submit approved work only through `meute promote` or `meute plan --enqueue`, on an explicit human click.
- **Codeman:** show linked sessions from `GET /api/sessions`; open one by deep link; launch one for an approved task on an explicit human click. État-major never sets `envOverrides`. Verify against the real server first.
- **Cross-repository portfolio and mobile refinement.**
- **Hardening:** large-repository limits, incremental reindex, freshness alerts, and the credential-isolation check for a second user (separate OS users with separate Codeman instances, or verified per-user config directories, plus account-eligibility confirmation with Anthropic).
- **Done when:** with all services stopped nothing else changes; with them running a task shows its ExecutionLink; no second queue or terminal exists; a large-repository run is documented; the isolation check result (pass, or fail with the reason) is recorded and the second user is added only on a pass.

## Dependency order

Phase 1 → Slice 1 → Phase 2 and Phase 3 (Phase 3 uses Phase 2 for links) → Phase 4 → Phase 5 → Phase 6. The Meute `generated` rung of the evidence ladder arrives in Phase 6, not Phase 5. The "module to why" query is tested in Phase 5.

## Recommended next step

Build the read-only API and Understand screen using recorded artifacts and the existing CLI index.
