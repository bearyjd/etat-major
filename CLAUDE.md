# État-major (working title)

Self-hosted visual product-development workspace with four connected views: Discover (why we build: research, decisions, feature proposals), Understand (what exists: architecture and code maps), Design & Build (what should exist: features, roadmap, planned architecture) and Progress (how we are getting there, with evidence). The central chain is Research → Decision → Feature → Design → Code → Evidence, navigable both ways. It is useful with no agent running. It is not a terminal, a coding-agent runner, a scheduler or a general project-management platform. Public repo, AGPL-3.0, French naming for projects. Owner: the repo maintainer.

Governing documents: [docs/VISUALIZATION-ARCHITECTURE.md](docs/VISUALIZATION-ARCHITECTURE.md) (design, contracts, trust model), [docs/TRACEABILITY.md](docs/TRACEABILITY.md) (research-to-delivery model, ChatGPT handoff), [docs/TOOL-EVALUATION.md](docs/TOOL-EVALUATION.md) (Floorplan, Trail, Understand Anything) and [docs/VISUALIZATION-ROADMAP.md](docs/VISUALIZATION-ROADMAP.md) (phases). They win over [docs/SPEC.md](docs/SPEC.md), whose control-plane, router, runner and phase plans are superseded. If this file and the architecture document disagree, the architecture document wins; tell the maintainer.

## Product goals (judge every decision against these)
1. Discover: persistent, attributable research and decisions (including rejected ones) linked to features, so evaluated ideas are not proposed again.
1b. Understand: a verifiable map of how each repository works, with provenance and coverage limits always visible.
2. Build: a Git-backed roadmap and board linked to the code it touches.
3. Progress: completion shown only through evidence (commits, PRs, checks, tests, releases, human acceptance), otherwise `unverified`.
4. A second user later, under their own logins, once credential isolation is verified in the Codeman deployment (see the architecture document). État-major itself handles no credentials.

## Hard constraints
1. Never store, proxy, harvest or pool Claude or Codex credentials. Never switch accounts to dodge limits. Configuration refers to secrets by pointer (an env var name or path), never by value.
2. Git holds durable intent (Markdown + YAML frontmatter, Mermaid). Derived data lives in a rebuildable cache that is never authoritative. Stored task statuses are only `draft`, `ready`, `blocked`, `done`; In Progress and Review are derived from Git and PR evidence. Only a human records acceptance for `done`.
3. Every completion claim links to a commit, PR, check, release or human acceptance. Without proof it is `unverified`. Never use an agent's self-estimate as progress.
4. Never run, schedule or queue agent work. Codeman owns interactive sessions and Meute owns unattended runs. Exactly one scheduler owns any job. État-major itself starts and queues nothing. A later optional hand-off (roadmap Phase 6) may call their documented interfaces (roadmap Phase 6) only on an explicit human click per action, stores nothing about the request beyond an ExecutionLink, and never sets credential-bearing environment overrides.
5. The core must work with no Codeman, no Meute, no live Floorplan service and no running agent.
5b. Research and decisions live in Git as Markdown. AI-produced research is `ai-generated` and `unreviewed` until a person checks its sources; a finding without a source URL and date is `unsourced`. Never invent threads or citations. Only a human records a Decision. Check `decisions/` before proposing a feature.
5c. ChatGPT is the preferred external research partner, especially for Reddit. The handoff is manual: État-major writes a brief, the human reviews and pastes it, and brings the answer back for review. No automatic sending, no scraping of ChatGPT sessions, no undocumented API, no background research agent.
6. Reuse existing analysis tools; do not build or run a second engine without a demonstrated gap. Floorplan (architecture layer) and Trail (symbol layer) are read through versioned, read-only adapters with pinned versions and checked schema markers; never fork or modify them, never run their model-backed steps, and never run `trail init`. Understand Anything is not an indexer here. Index a copy or worktree, never write into a source repository, and never run `trail init`.
7. Untrusted content (repo Markdown, Mermaid, AI-generated text) is sanitized before rendering and labelled by provenance.
8. Public repo hygiene: no personal paths, hostnames or keys in code or docs; config files plus a seeded demo workspace.

## Trust model
First deployment is a trusted family on one machine over loopback or a private network. No per-user containers or Unix accounts at first. Open risk: Codeman's multi-user mode shares one OS account and one Claude login by default. Do not add a second user until credential isolation is verified end to end and account eligibility is confirmed. See "Security and trust" in the architecture document.

## Phases
See the roadmap: Phase 1 tool evaluation (done); Slice 1, the thinnest research-to-code trace (next); Phase 2 repository visualization; Phase 3 research and feature model; Phase 4 planning visualization; Phase 5 progress and traceability; Phase 6 optional integrations and hardening. Each ends at its acceptance criteria before the next starts.

## Build vs adopt (as of 2026-11-21; verify each license in its own repo)
- Architecture maps and blueprints: Floorplan (MIT, pre-1.0, `graph.json` is not a documented contract). Function-level graph: Trail. Understand Anything: skip. See `docs/TOOL-EVALUATION.md`.
- Graph UI: start from Floorplan's generated viewer for architecture; Cytoscape.js (lean) over React Flow for overlays and the function layer; Mermaid for diagrams. Confirm in roadmap Phase 2.
- Phone terminal and voice: Codeman (separate). Herdr is a candidate only if needed later.
- Task format: our own contract (see `docs/spikes/phase1-spike.md`); Backlog.md is a reference only.
- Avoid: Vibe Kanban (maintainer status doubtful, unverified), amux (Commons Clause), Agent Kanban (FSL), account switching or pooling.

## Open questions
Quality and cost of an LLM-written Floorplan architecture layer; Floorplan schema stability; cache format (SQLite or JSON); language coverage beyond Python; large-repository limits; the Codeman deep link that works on a phone; the live schema of Meute's `inbox.py dump`; the second user's CLI, account eligibility and credential isolation; repo name, license header and demo workspace. Re-read Anthropic's current terms before any release; they changed several times in 2026.

## Related projects (separate; connect through the four contracts)
Codeman (interactive sessions), Meute (unattended runs), Floorplan (architecture maps), Trail (code index), ChatGPT (manual research), Git and GitHub (source of truth). Contracts: RepoIndex, ProjectIntent, ProgressEvidence, ExecutionLink, ResearchArtifact, Decision, Feature, ArchitectureLink.

## How to work in this repo
- Small, reviewable steps; tests first with every contract change.
- Reddit research must go through ChatGPT (manual handoff) or Codex, not Claude's own search (it cannot reach Reddit). See the `reddit-via-codex` skill.
- Keep secrets, hostnames and personal paths out of the repo.
