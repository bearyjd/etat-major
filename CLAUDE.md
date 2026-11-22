# État-major (working title)

Self-hosted, living visual map of repositories: how each works (Understand), what we are building toward (Build), and how we are getting there with evidence (Progress). It is useful with no agent running. It is not a terminal, a coding-agent runner, a scheduler or a general project-management platform. Public repo, AGPL-3.0, French naming for projects. Owner: the repo maintainer.

Governing documents: [docs/VISUALIZATION-ARCHITECTURE.md](docs/VISUALIZATION-ARCHITECTURE.md) (design, contracts, trust model) and [docs/VISUALIZATION-ROADMAP.md](docs/VISUALIZATION-ROADMAP.md) (milestones). They win over [docs/SPEC.md](docs/SPEC.md), whose control-plane, router, runner and phase plans are superseded. If this file and the architecture document disagree, the architecture document wins; tell the maintainer.

## Product goals (judge every decision against these)
1. Understand: a verifiable map of how each repository works, with provenance and coverage limits always visible.
2. Build: a Git-backed roadmap and board linked to the code it touches.
3. Progress: completion shown only through evidence (commits, PRs, checks, tests, releases, human acceptance), otherwise `unverified`.
4. A second family user later, under their own logins, once credential isolation is verified (see the architecture document).

## Hard constraints
1. Never store, proxy, harvest or pool Claude or Codex credentials. Never switch accounts to dodge limits. Configuration refers to secrets by pointer (an env var name or path), never by value.
2. Git holds durable intent (Markdown + YAML frontmatter, Mermaid). Derived data lives in a rebuildable cache that is never authoritative. Stored task statuses are only `draft`, `ready`, `blocked`, `done`; In Progress and Review are derived from Git and PR evidence. Only a human records acceptance for `done`.
3. Every completion claim links to a commit, PR, check, release or human acceptance. Without proof it is `unverified`. Never use an agent's self-estimate as progress.
4. Never run, schedule or queue agent work. Codeman owns interactive sessions and Meute owns unattended runs. Exactly one scheduler owns any job. Launching or submitting work happens only through their own interfaces and only after explicit human approval.
5. The core must work with no Codeman, no Meute and no running agent.
6. Treat the indexer as replaceable: Trail through a versioned adapter, pinned version, `meta.version` checked. Index a copy or worktree, never write into a source repository, and never run `trail init`.
7. Untrusted content (repo Markdown, Mermaid, AI-generated text) is sanitized before rendering and labelled by provenance.
8. Public repo hygiene: no personal paths, hostnames or keys in code or docs; config files plus a seeded demo workspace.

## Trust model
First deployment is a trusted family on one machine over loopback or a private network. No per-user containers or Unix accounts at first. Open risk: Codeman's multi-user mode shares one OS account and one Claude login by default. Do not add a second user until credential isolation is verified end to end and account eligibility is confirmed. See "Security and trust" in the architecture document.

## Milestones
See the roadmap: M0 reconcile design; M1 RepoIndex adapter for Trail; M2 ProjectIntent loader; M3 ProgressEvidence from Git and GitHub; M4 Understand UI; M5 Build view; M6 Progress view and portfolio; M7 optional Meute and Codeman integrations; M8 hardening and the second user. Each ends at its acceptance criteria before the next starts.

## Build vs adopt (as of 2026-11-21; verify each license in its own repo)
- Repository structure: Trail first; supplement with tree-sitter or universal-ctags only where a gap is documented.
- Graph UI: Cytoscape.js (lean) over React Flow; Mermaid for diagrams. Confirm in M4.
- Phone terminal and voice: Codeman (separate). Herdr is a candidate only if needed later.
- Task format: our own contract (see `docs/spikes/phase1-spike.md`); Backlog.md is a reference only.
- Avoid: Vibe Kanban (maintainer status doubtful), amux (Commons Clause), Agent Kanban (FSL), account switching or pooling.

## Open questions
Cache format (SQLite or JSON); language coverage beyond Python; large-repository limits; the Codeman deep link that works on a phone; the live schema of Meute's `inbox.py dump`; the second user's CLI, account eligibility and credential isolation; repo name, license header and demo workspace. Re-read Anthropic's current terms before any release; they changed several times in 2026.

## Related projects (separate; connect through the four contracts)
Codeman (interactive sessions), Meute (unattended runs), Trail (code index), Git and GitHub (source of truth). Contracts: RepoIndex, ProjectIntent, ProgressEvidence, ExecutionLink.

## How to work in this repo
- Small, reviewable steps; tests first with every contract change.
- Reddit research must go through Codex or ChatGPT, not Claude's own search (it cannot reach Reddit). See the `reddit-via-codex` skill.
- Keep secrets, hostnames and personal paths out of the repo.
