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

**Revised after the Floorplan proof-out ([FLOORPLAN-PROOF.md](FLOORPLAN-PROOF.md)).** Do first: (a) fix the Trail adapter to accept every node kind real graphs contain (it rejected a real Kotlin graph), (b) add a Gradle declared-dependency adapter and compare it with actual import links to show drift, (c) keep the Floorplan adapter to the deterministic import-link and glob role, with a reviewed Git-backed component model as the source of truth for components. The Floorplan items below that mention blueprints or the architecture layer apply only as advisory inputs.

**Status** — Recorded Floorplan and Trail adapters, index joins, renames and overlays are implemented. The reviewed component model and both deterministic runner wrappers are implemented. Real smoke covered both Trail output layouts and a Floorplan rename refresh that retained all 80 authored component IDs. The [Understand MVP design](UNDERSTAND-MVP.md) defines the next read-only screen.

- **Depends on:** Slice 1.
- **Build:**
  - Floorplan adapter: a pinned Floorplan commit, a CI check that a recorded `graph@1` still parses, optional invocation of only the deterministic `scan`, `build` and `refresh` scripts on a disposable copy (never the model-backed steps, `serve.mjs` or the Ask bar), a rename reconciler using Git rename detection, and the planned-versus-built overlay computed by diffing a blueprint's `f:` ids against the current code map.
  - Trail adapter: build in a copy or worktree, read `wiring.json`, accept only `meta.version` 1, map `relation` and `confidence` to provenance, compute coverage and freshness against `HEAD`.
  - A join of the two layers by repository-relative path and revision; both layers and their provenance stay visible.
  - First [Understand MVP](UNDERSTAND-MVP.md): the configured project, with a read-only component, file and symbol inspector and coverage from recorded artifacts. The existing web service renders the page from its startup snapshot.
  - Later options: a public read-only JSON API, repository selector and interactive architecture or symbol graph. The MVP uses recorded Floorplan output and executes no Floorplan viewer.
- **Decide for later slices:** whether viewer links or État-major graph overlays add enough value; confirm library licenses.
- **MVP done when:** for one repository, you can pick a component, drill to a recorded file and symbol, and see callers and callees with provenance and coverage limits. A matching configured source snapshot can provide a bounded excerpt. The page works on a phone-width screen with no Codeman, Meute or agent running. A general source browser and visual blueprint overlays remain later options.
- **Not promised:** `references`, `implements` or `lsp_*` edges (not observed), call edges for languages without full-fidelity support, or a module graph beyond directories and imports.

## Phase 3: research and feature model

**Status** — Research and feature loaders, relevant decision listing, manual brief/import and derived feature stages are implemented. A read-only Discover page (`GET /discover`, bounded `?q=` filter) lists all decisions and research with status, provenance and citation badges. The review UI and the in-page brief/import handoff panel remain.

- **Depends on:** Slice 1, and Phase 2 for the architecture links.
- **Build:** full loaders and the lifecycle (Idea to Released, plus Rejected and Postponed); the Decision search ("has this question been decided?"); the manual ChatGPT handoff, that is `research brief` (writes a prompt file after a redaction check) and `research import` (parses a pasted answer into an `unreviewed`, `ai-generated` draft, flags unsourced items, keeps URLs verbatim); the review step that marks an artifact `reviewed`.
- **Done when:** the importer and UI never write `approved`, `reviewed`, `decided_by`, `accepted_by` or `accepted_on` (tested); a brief is generated for a feature with no local paths, hostnames or keys; pasting a recorded sample answer yields a draft whose unsourced items are flagged; an unreviewed artifact cannot back an approved Decision; a stored Feature file cannot hold a derived lifecycle stage; nothing is sent anywhere automatically.

## Phase 4: planning visualization

**Status** — Task, vision and milestone models, dependency validation, board-state derivation and blueprint reading are implemented. The [read-only Planning pilot](PLANNING.md) shows one project's recorded intent, evidence and board state, with nonce-gated snapshot refresh. Diagram rendering and editing remain planned.

- **Depends on:** Phase 3.
- **Build:** extend the merged task contract (keep initiative, project, task; add optional `milestone`, `accepted_by`, `accepted_on`, `depends_on`, `targets`, and a link to a Feature; drop `budget_tokens`), the vision file, milestones with Now/Next/Later, dependency cycle detection, a Kanban (Draft, Ready, In Progress, Review, Done, Blocked), dependency view, Mermaid diagrams and wireframes rendered with sanitization, and Floorplan blueprints attached to features.
- **Future edits:** the editor would write Markdown or YAML only into the configured intent workspace (a Git working tree) and shows the resulting diff. État-major commits and pushes nothing.
- **Done when:** the demo roadmap and board render from files; clicking a feature highlights its planned and existing components; a task naming a derived status is rejected; a dependency cycle is rejected; every edit is an uncommitted diff in the workspace.

## Phase 5: progress and traceability

**Status** — Progress derives evidence from local Git and recorded GitHub data and reports lifecycle stages, gaps and stale links. The read-only Planning pilot displays recorded Meute and manual review evidence with provenance. Live GitHub access and further progress UI work remain planned.

- **Depends on:** Phases 3 and 4.
- **Build:** ProgressEvidence from Git and GitHub (link key `Task: <project>/<id>` in a commit trailer, branch or PR body; PRs, reviews, checks and releases recorded from the user's own `gh` login by a person, under the capture-script exception in `AGENTS.md`); the evidence ladder; derived In Progress, Review, Implementing, Verified and Released; gap, stale and disconnected-work reports; comparison of the delivered result with the Feature's `outcome`.
- **Tests:** a fixture repository with scripted history and recorded `gh` JSON.
- **Done when:** each task and feature shows exactly the rungs its records prove and nothing more; a merged PR without `accepted_by` and `accepted_on` is shown in Review and not `done`; unimplemented, unverified and blocked requirements are listed; every completion claim links to a commit, PR, check, release or human acceptance, or reads `unverified`.

## Phase 6: optional integrations and hardening

**Status** — Read-only Planning and Fleet, recorded handoffs and in-memory refresh are implemented. An earlier local Alto pilot exercised those features. Deployment and verification of the current combined release, native existing-session round trips and authenticated Fleet actions remain pending. Portfolio, mobile views and deployment hardening remain planned.

- **Depends on:** Phases 2 to 5.
- **Meute:** display recorded reports as `generated` evidence when the recording identifies an existing project task. Meute owns Inbox, Run, write authentication and execution. Any future live Fleet control must be an allowlisted, explicit operator action authorized by Meute.
- **Codeman:** show recorded session links and let the opted-in native parent UI select an existing session after an explicit click and its access checks. Session launch is post-MVP. État-major never sets `envOverrides`.
- **Planning appearance in Codeman (after the MVP):** add an optional theme setting that follows Codeman's colors, typography, and spacing in light and dark modes. Render it through État-major's own styles so it works inside the sandboxed Web Tab. Check contrast and phone-width layouts.
- **Cross-repository portfolio and mobile refinement.**
- **Hardening:** large-repository limits, incremental reindex, freshness alerts, and the credential-isolation check for a second user (separate OS users with separate Codeman instances, or verified per-user config directories, plus account-eligibility confirmation with Anthropic).
- **Done when:** with all services stopped nothing else changes; with them running a task shows its ExecutionLink; no second queue or terminal exists; a large-repository run is documented; the isolation check result (pass, or fail with the reason) is recorded and the second user is added only on a pass.

## Proposed delivery milestones

The [delivery roadmap](DELIVERY-ROADMAP.md) maps these phases to proposed PRs,
dependencies, acceptance evidence and maintainer approvals. It covers the Alto
rollout, the Understand MVP and the order of the remaining integration work.

## Dependency order

Phase 1 → Slice 1 → Phase 2 and Phase 3 (Phase 3 uses Phase 2 for links) → Phase 4 → Phase 5 → Phase 6. The recorded Meute integration contributes to the `generated` evidence rung. The "module to why" query is tested in Phase 5.

## Recommended next steps

Follow the [Alto delivery workflow](ALTO-MVP-DELIVERY.md) in three separate PRs.

1. Stage the exact merged read-only release. With explicit rollout scope, deploy and verify it on Alto.
2. Design and implement native **Open session**. Keep the Planning iframe opaque and limited to nominating an existing session. The opted-in Codeman parent rechecks the active frame, access and session owner on an explicit native click. In multi-user mode require an exact owner match. In authenticated single-user mode an ownerless session is eligible. Verify return to the exact Planning task and denial cases at desktop and phone widths.
3. Keep Fleet actions and execution in Meute. Start with a private authenticated top-level link. Verify Host, Fetch Metadata, write Origin, tokens and explicit operator action on Alto before enabling iframe writes.

The [Understand MVP](UNDERSTAND-MVP.md) can proceed independently of Alto deployment. After the MVP, consider an optional Codeman theme with light and dark modes, accessible contrast and phone-width layouts.
