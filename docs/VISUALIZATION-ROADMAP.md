# État-major: visualization roadmap

Status: plan. Replaces the six-phase roadmap in [SPEC.md](SPEC.md). Design and contracts: [VISUALIZATION-ARCHITECTURE.md](VISUALIZATION-ARCHITECTURE.md).

Rules for every milestone:

- Small, reviewable steps; tests written first for every contract change; coverage 80% or better on new code.
- A milestone ends at its acceptance criteria. The next one does not start before they pass.
- The core runs with no Codeman, no Meute and no agent. Integrations come last.
- Nothing here stores or handles Claude or Codex credentials.

## What exists today

- Scaffold, CI, and the task-file contract with a validator (`src/etat_major/taskfile.py`, `docs/contracts/`). It is reused by milestone M2.
- A decision record that Backlog.md's format is not adopted (`docs/spikes/phase1-spike.md`).
- No indexer adapter, no evidence code, no web UI.

## Milestones

### M0: Reconcile the design (this change)

Docs only: architecture, roadmap, and superseded markers in the README, `CLAUDE.md`, `SPEC.md` and `RESEARCH.md`.

- **Done when:** the four docs agree on the product; superseded plans are marked; no document claims a capability that is not built.

### M1: RepoIndex adapter for Trail

Read Trail's graph into the `RepoIndex` contract.

- **Depends on:** M0.
- **Build:** a versioned adapter that runs `trail build` against a copy or worktree, reads `wiring.json`, rejects any `meta.version` other than 1, maps `relation` and `confidence` to provenance, computes module nodes from directories and imports (marked `inferred`), and reports coverage (languages, files skipped, indexed revision against current `HEAD`).
- **Tests:** a small committed fixture graph; version rejection; unknown relation handled without crashing; a stale-revision case.
- **Done when:** for this repo, a command prints RepoIndex JSON with symbol ranges, call and import edges with provenance, and a coverage block; the Trail version is pinned; the indexer sits behind an interface with a second stub implementation proving it can be swapped.
- **Open check:** `references`, `implements` and `lsp_*` edges were not observed; the adapter must handle them, and the roadmap does not promise them.

### M2: ProjectIntent loader

Extend the merged validator to the full intent model.

- **Depends on:** M0.
- **Build:** vision file, milestones (`horizon`: now, next, later), tasks with `depends_on`, `targets` and diagram paths; dependency cycle detection; a loader for a workspace directory with errors that name file and field.
- **Rules kept:** only `draft`, `ready`, `blocked`, `done` are valid stored statuses; derived columns are never written to files.
- **Done when:** a demo workspace loads; a task naming a derived status is rejected; a dependency cycle is rejected; a `targets` entry that does not resolve in a RepoIndex is reported as stale.

### M3: ProgressEvidence from Git and GitHub

Compute the evidence ladder.

- **Depends on:** M2 (task ids), and M1 only for symbol-level mapping.
- **Build:** link commits, branches and PRs to tasks by trailer `Task: <id>`, branch `task/<id>-...` or PR body; read PR state, reviews, checks and releases through `gh`; derive In Progress, Review and Blocked; compute `generated` evidence only from Meute artifacts when configured; mark every rung without proof `unverified`; list disconnected work.
- **Tests:** a fixture repository with scripted history; PR and check data from recorded `gh` JSON, not the network.
- **Done when:** on the fixture, each task shows exactly the rungs its records prove and no more; a task with a merged PR but no human acceptance is not `done`; disconnected commits are listed.

### M4: Read-only web UI, Understand view

A first screen on real data.

- **Depends on:** M1.
- **Build:** FastAPI serving a read-only JSON API and the UI; repository selector, file tree, symbol search, Cytoscape.js graph with module-to-function zoom, node inspector, source viewer, and a coverage and freshness panel. Confirm Cytoscape.js against React Flow here and check licenses.
- **Done when:** selecting a repository, finding a function or class, inspecting its references and dependencies, and opening its source works; the UI shows edge provenance and what is not covered; the page works on a phone-width screen; it needs no Codeman, Meute or agent.

### M5: Build view

The planning half.

- **Depends on:** M2, M4.
- **Build:** vision, milestones with Now/Next/Later, a Kanban with Draft, Ready, In Progress, Review, Done and Blocked (the last two derived columns use M3 when available), dependency view, Mermaid diagrams and wireframes rendered with sanitization; a task's `targets` highlight nodes in the Understand graph.
- **Edits:** changes are written as Markdown or YAML for review in Git; the UI never keeps a separate copy.
- **Done when:** the demo roadmap and board render from files; a task click highlights its code nodes; a stale mapping is visible; no edit bypasses Git.

### M6: Progress view and portfolio

The proof half.

- **Depends on:** M3, M5.
- **Build:** per-milestone progress from the evidence ladder, blocked tasks, stale plans (milestones past date, unresolved targets), disconnected work, and a cross-repository portfolio page.
- **Done when:** every completion claim on screen links to a commit, PR, check, release or human acceptance, or reads `unverified`; clicking a module shows its dependent tasks and their evidence.

### M7: Integrations (optional, last)

- **Depends on:** M5, M6.
- **Meute (read-only):** parse `state/log` and `reports/**` directly into `generated` evidence and a summary; never call the per-report command that marks reports read. Submit approved work only through `meute promote` or `meute plan --enqueue`, behind explicit human approval.
- **Codeman:** show linked sessions from `GET /api/sessions`; open one by deep link; launch one for an approved task. Verify against the real server first.
- **Done when:** with both services stopped, nothing else changes; with them running, a task shows its `ExecutionLink`; no second queue or terminal exists.

### M8: Hardening and the second user

- **Depends on:** M4 through M7.
- **Build:** behaviour and limits on large repositories (graph size, on-demand loading), incremental reindex, freshness alerts, and the credential-isolation check for a second user.
- **Credential check:** verify end to end that two people on one machine use distinct Claude and Codex logins through the chosen setup (separate OS users with separate Codeman instances, or verified per-user config directories). Confirm account eligibility with Anthropic before the second user is added.
- **Done when:** a documented large-repository run; the isolation check passes or the second user is deferred with the reason recorded.

## Dependency order

M0 → (M1, M2) → M3 → M4 uses M1 → M5 uses M2 and M4 → M6 uses M3 and M5 → M7 → M8. M1 and M2 can run in parallel; M3 needs M2.

## Recommended next step

Start M1. It is the smallest piece that proves the product's core claim (a verifiable code map), it has a real fixture available from a run against this repository, and it does not depend on any decision still open.
