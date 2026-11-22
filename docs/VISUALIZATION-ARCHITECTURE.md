# État-major: visualization architecture

Status: pre-implementation design. Written 2026-11-21. This document governs wherever it conflicts with [SPEC.md](SPEC.md) (see [What is superseded](#what-is-superseded)).

## Purpose

État-major is a living visual map of three things for each repository:

1. **Understand:** how the code works.
2. **Build:** what we are building toward.
3. **Progress:** how we are getting there, with evidence.

It is useful with no agent running. It is not a terminal, a runner, a scheduler or a general project-management platform.

## Non-goals

- Running or supervising coding agents. Codeman owns interactive sessions; Meute owns unattended runs.
- A scheduler, queue or runner of any kind.
- A terminal or tmux subsystem.
- Handling Claude or Codex authentication in any way: no subscription proxy, token pooling or account switching.
- A proprietary planning database. Git is the source of truth for intent.
- Enterprise identity, per-user containers or per-user Unix accounts in the first deployment (see [Security and trust](#security-and-trust)).

## What is superseded

The first SPEC.md described a control plane that supervised agents. That direction is replaced. Nothing in it had been built beyond the task-file validator.

| Earlier plan (SPEC.md / CLAUDE.md) | Status |
| --- | --- |
| Control plane that runs sessions, router, runner API | **Superseded.** Codeman and Meute own execution. |
| Model router, profiles, fallback policy, routing-policy test | **Superseded.** No agent launching here. |
| Runtime store for sessions, hook events, spend, approvals | **Superseded.** Progress evidence is derived from Git/CI; a rebuildable cache replaces it. |
| Event schema, adapter interface, runner API contracts | **Superseded** by the four contracts below. |
| One Unix user or VM per person, per-user containers | **Superseded** for the first deployment; see trust model. |
| Phases 1 to 6 | **Superseded** by [VISUALIZATION-ROADMAP.md](VISUALIZATION-ROADMAP.md). |
| Git holds intent; derived state never written to files; evidence-based progress | **Kept.** |
| Never store, pool or proxy credentials; no account switching | **Kept.** |
| Public repo, AGPL-3.0, no personal paths or secrets | **Kept.** |
| Licensing and Anthropic-terms notes, build-vs-adopt research | **Kept** (re-verify before each release). |

## Component ownership

| Component | Owns | État-major's relationship |
| --- | --- | --- |
| **État-major** | Visualization, cross-repository aggregation, project intent files, progress evidence, links to sessions and jobs | The product. Works alone. |
| **Trail** | Parsing code into a symbol graph | First source for `RepoIndex`, through a versioned adapter. Replaceable. |
| **Git and GitHub** | Durable intent (Markdown, YAML, Mermaid), history, PRs, checks, releases | Source of truth. Read through `git` and `gh`. |
| **Codeman** | Interactive Claude Code and Codex sessions, tmux, mobile terminal, voice, notifications, logins | Separate. Link out; optionally launch a session for an approved task. |
| **Meute** | Unattended scheduling and execution, run reports | Separate. Read its artifacts; submit approved work only through its own CLI. |
| **Backlog.md** | A task-file format | Reference only. The spike decided to define our own contract (see `docs/spikes/phase1-spike.md`). |

Exactly one scheduler owns any job. Meute owns the job queue and run logic; its time triggers are external cron or systemd timers set up for Meute. État-major never writes Meute's state files.

## Verified facts about the neighbours

Findings below come from reading each project's code and docs on 2026-11-21. "Verified" means observed in code or by running a read-only command. Items marked unverified were not tested.

### Trail 0.30.5 (MIT)

- **Documented by Trail, not reproduced here:** tree-sitter parsing for 28 languages, incremental reindexing by content hash, and the full-fidelity language list below.
- **Verified:** it writes `graft/.graph/wiring.json`, schema `GraphV1`, `meta.version` 1. Nodes are files, classes, functions and methods with path and line span. Edges carry a `relation` and a `confidence`. The type definitions list the relations `contains`, `calls`, `imports`, `references`, `implements`, `extends` and the confidences `extracted`, `inferred`, `lsp_resolved`, `lsp_dispatch`; only the subset below was seen in practice.
- **Verified on this repo (Python):** 66 nodes and 167 edges from 5 files in about 2 seconds. Relations seen: `calls`, `contains`, `imports`, `extends`. Confidences seen: `extracted`, `inferred`. `references`, `implements` and the `lsp_*` confidences were not observed.
- **Verified:** the graph is function-level, not only file-level.
- **Gaps:** call edges are name-resolved outside the full-fidelity languages (TypeScript/JavaScript, Python, Go, Java, Kotlin, PHP, Swift, R). Some languages (Bash among them) have symbols only. There is no module-level graph, only directory and file clustering in `trail map`. No data-flow analysis.
- **Risks:** pre-1.0; renamed from "graft" (old names still appear); no documented schema-compatibility promise; `wiring.json` embeds body text, so it may be large on big repos (unverified). `trail build` writes `graft/`, `.gitignore` and `.ignore` into its target, so index a copy or a worktree. `trail init` edits agent configuration in the home directory and must not be used here. Telemetry is on by default; disable it with `trail telemetry disable`.
- **Adapter rule:** pin the Trail version, reject any `meta.version` other than 1, read the edge type from `relation`, keep `confidence` as provenance. Keep `web-tree-sitter` or `universal-ctags` as the fallback indexer.

### Meute (commit `6b4253b`)

- **Verified:** Bash plus Python, no daemon, no database. Scheduling is external (cron or systemd user timers). One `run.sh <slot>` call does one unit of work and exits. It is single-user and uses the host's own `claude` and `codex` logins.
- **Verified read paths:** `state/log` (tab-separated, one line per invocation, key=value fields); run reports at `reports/<repo>/<task>-<date>.md` with YAML front matter and `### [SEVERITY]` findings; write-tier runs leave a local `meute/<task>-<date>` branch that is never pushed; `lib/inbox.py dump` prints one JSON object.
- **Caution:** the per-report form of `lib/inbox.py` shells out to `bin/meute show`, which marks a report as read. Read files and `state/log` directly instead.
- **Verified submit paths:** there is no generic submit interface. The real ones are `meute promote` (a finding becomes a tier-3 ticket) and `meute plan --enqueue` (read-only runs). Shell out to these; never write `state/tickets.yaml` or the plan queue.
- **Overlap risk: high.** Meute's repository contains a web UI and a TUI (files and routes found in its source; their behaviour was not run) with an inbox and a Run tab. État-major must not rebuild them. Its README still says "no web UI", which is stale.
- **Unverified:** the exact JSON schema of `inbox.py dump` against live state; how the feature branch with the web UI differs from `main`.

### Codeman 1.51.1 (MIT)

- **Verified in code and docs:** Node 22, Fastify, tmux, xterm.js PWA. A stable `/api/v1` prefix with an `{success, data}` envelope. `GET /api/sessions` lists sessions. `POST /api/sessions` creates one (`workingDir`, `mode` for the agent CLI, `name`, optional `envOverrides`). There is no initial-prompt field on create; send it with `POST /api/sessions/:id/input`. SSE at `GET /api/events` and a WebSocket terminal exist.
- **Session links:** the API returns no URL. `/session/:id` serves a single-session window, and the SPA reads a `#session=<id>` fragment. Which of these a phone browser honours is unverified.
- **Auth:** optional HTTP Basic plus a cookie. No bearer or API-key scheme. With no password configured, nothing is enforced.
- **Multi-user:** opt-in. It separates workspaces and filters sessions by owner. **It does not isolate credentials.** By its own documentation all sessions run as one OS account and share one tmux socket, one `~/.claude`, and therefore one Claude login and subscription. A per-launch `CLAUDE_CONFIG_DIR` or `CODEX_HOME` override is the only lever, and it is a privileged key (admin or granted users only). Whether it survives restart for non-granted users is unverified, and it was not tested end to end.
- **Voice (unverified):** a design document says dictation streams audio to Anthropic's speech endpoint using the server's own Claude login, which would send a second user's speech through the owner's login. Only the design document was read, so the implementation is unverified.

## Data contracts

Four small, tool-neutral contracts. Each is a documented file or JSON shape with a version field. None depends on Trail, Codeman or Meute being installed.

Provenance values used throughout: `verified` (derived by a deterministic tool), `inferred` (heuristic), `ai-generated` (a model wrote it), `human` (a person asserted it). The UI always shows provenance and never upgrades it.

### RepoIndex

A derived, rebuildable snapshot of one repository at one revision. A cache, never authoritative.

```yaml
version: 1
repository: example-service        # repo id
revision: <git sha>                # the commit indexed
indexed_at: 2026-11-21T12:00:00Z
indexer: { name: trail, version: 0.30.5 }
coverage: { languages: [python], files_indexed: 5, files_skipped: 0 }
symbols:
  - id: src/example/mapper.py#map_row
    kind: function                 # file | class | function | method | module
    path: src/example/mapper.py
    range: [203, 219]              # start and end line
edges:
  - from: src/example/mapper.py#map_row
    to: src/example/util.py#clean
    relation: calls                # contains | imports | calls | references | extends | implements
    provenance: verified           # verified | inferred
    confidence: extracted          # indexer's own label, kept verbatim
```

Symbol IDs are `path#qualified.name`, which survives re-indexing when the symbol does not move. Module-level nodes are computed by État-major from directories and import edges and are marked `inferred`.

### ProjectIntent

Git-backed Markdown with YAML frontmatter. It extends the merged task-file contract (`docs/contracts/task-file.md`).

- **Vision file:** vision, goals and links to architecture diagrams (`diagrams/*.mmd`).
- **Milestones:** id, title, target date, `horizon` (`now`, `next`, `later`), outcome.
- **Tasks:** id, title, optional `milestone`, owner, priority, acceptance criteria (list), `depends_on` (task ids), `targets` (file paths, module paths or symbol IDs), and an intent status.
- **Diagrams:** Mermaid files and wireframes (image or Mermaid) linked from a milestone or task.

The hierarchy stays initiative, project, task as in the merged contract; `milestone` is an added optional link, and `budget_tokens` (a runner-era field) is dropped in M2. Task ids are unique within a project, so the link key is `<project>/<id>`. Stored statuses are only `draft`, `ready`, `blocked`, `done`, as the merged validator enforces. The Kanban columns In Progress and Review are derived (see below). `done` needs a recorded human acceptance: `accepted_by` and `accepted_on` fields written together with `status: done` (added to the contract in M2). Trust assumption: Git author metadata cannot prove a human wrote a change; in the trusted-family setup that is accepted, and no approval mechanism is designed here.

A `targets` entry that no longer resolves in the current RepoIndex is shown as a stale mapping, not hidden.

### ProgressEvidence

A derived record linking a task to proof. Evidence is gathered from Git and GitHub and cached; the claim "done" never comes from an agent's own assertion. An `evidence` list in a task file (see the task-file contract) is a set of declared references, i.e. hints to look up. It counts as proof only after the referenced PR, check or release is confirmed in Git or GitHub.

Linking key, in order of preference: a commit trailer `Task: <project>/<id>`, a branch named `task/<project>-<id>-...`, a PR body line `Task: <project>/<id>`. Work with none of these is **disconnected work**.

Each task carries an evidence ladder. A rung is shown only if a record proves it; otherwise it is `unverified`:

| Rung | Proof |
| --- | --- |
| generated | A Meute run report or a `meute/*` branch linked to the task (not an agent's claim) |
| committed | A commit with the link key |
| tested | A passing CI check or test result on that commit or PR head |
| reviewed | A PR review approval, or a recorded human review |
| merged | A merged PR or a commit on the default branch |
| shipped | A release or tag containing the merge commit |
| accepted | `accepted_by` and `accepted_on` present alongside `status: done` |

Derived columns: **In Progress** is a linked branch or open draft PR with no merged PR. **Review** is an open, non-draft PR, or a merged PR whose task has no acceptance yet. **Blocked** is the stored status or an unmet `depends_on`.

### ExecutionLink

An optional pointer from a task to something running elsewhere:

```yaml
task: 0042
kind: codeman-session            # or meute-job
ref: <session id or job id>
url: <deep link, if known>       # Codeman: /session/<id>
seen_at: 2026-11-21T12:00:00Z
```

It is a link and a last-seen time, never a lifecycle owner. If the target disappears the link is shown as stale.

## The three views

1. **Understand.** Repository selector, file tree, symbol search, module and function graph, source navigation. Select a node to see its symbol, references and source location; zoom between modules and functions. A coverage panel shows languages, files skipped, index freshness (revision against current `HEAD`) and edge provenance. Explanations are labelled `ai-generated` and kept apart from verified relationships. No claim of a complete dynamic call graph is made.
2. **Build.** Vision, milestones, Now/Next/Later, a Kanban with Draft, Ready, In Progress, Review, Done, Blocked, task dependencies, and Mermaid diagrams and wireframes linked to milestones and tasks. A task's `targets` link it to nodes in the Understand graph.
3. **Progress.** Commits, PRs, checks and releases mapped to milestones through the evidence ladder. Blocked tasks, stale plans (targets that no longer resolve, milestones past their date) and disconnected work are surfaced. A portfolio page shows each project's movement across repositories. An optional morning summary reads Meute run artifacts.

The views are connected: a task highlights its target nodes; a module shows its dependent tasks and their evidence. A project overview shows vision, current architecture, next milestones and completion evidence without raw logs.

## Integration boundaries

- **Codeman:** read `GET /api/sessions`; open a session through a deep link; launch one for an approved task with `POST /api/sessions` followed by `POST /api/sessions/:id/input`. Basic auth credentials come from configuration by reference (an environment variable name), never stored. Launching is an optional later hand-off, always behind explicit human approval, and État-major never sets `envOverrides` at all: any per-person credential directory is configured in Codeman, outside État-major. Each launch is one explicit human click; nothing is queued or retried.
- **Meute:** read `state/log` and `reports/**` directly; submit only through `meute promote` or `meute plan --enqueue`, after human approval. No competing queue.
- **Git and CI:** `git log` and `gh` for PRs, reviews, checks and releases. Read-only, using the user's existing `gh` login; État-major stores no token.
- **Trail:** through the RepoIndex adapter, behind an interface so another indexer can replace it.

## Security and trust

- **First deployment:** a trusted family on one machine, reachable over loopback or a private network such as Tailscale. No public exposure. Codeman's passwordless default is not acceptable beyond loopback; configure its password.
- **Credentials:** État-major stores none. It reads no Claude or Codex login files. It never proxies, pools or switches accounts.
- **Critical open uncertainty:** Codeman's multi-user mode shares one OS account and one subscription login by default, and its voice dictation uses the server's login. Before the second user is added, either run a separate OS user with its own Codeman instance, or verify per-user config directories end to end and confirm account eligibility with Anthropic. Until then, treat a shared Codeman as single-subscription.
- **Indexing safety:** `trail build` writes into its target, so index a worktree or copy. Repositories are read-only inputs; État-major never edits indexed source.
- **Rendering:** Markdown and Mermaid from repositories are untrusted. Sanitize HTML and use Mermaid's strict mode.
- **Telemetry:** disable Trail telemetry in the adapter's environment.
- **Provenance:** every completion claim links to a commit, PR, check, release or human acceptance, otherwise it is `unverified`.

## Technology (recommendation, to confirm in the first UI milestone)

- **Backend:** Python, reusing the merged validator (`pydantic`, `PyYAML`). FastAPI to serve a read-only JSON API and static assets. The derived cache is SQLite or JSON files, rebuildable from Git and the indexer.
- **Frontend:** a thin, server-rendered UI with HTMX, plus Cytoscape.js for the graph. Cytoscape.js needs no UI framework, supports compound nodes for module nesting and handles large graphs; React Flow would commit the project to a React single-page app for little gain here. Mermaid renders diagrams client-side.
- **Mobile:** responsive layout; no native app. The phone terminal is Codeman's job.
- **Before adopting any library,** verify its license in its own repository.

## Open questions

- Which file extensions the first release supports beyond Python, and whether to enable Trail's optional LSP mode where servers exist.
- Repository size limits for `wiring.json` and a pagination or on-demand loading strategy for large graphs.
- Cache format: SQLite or JSON.
- The Codeman session deep link that works on a phone (`/session/:id` or the `#session=` fragment).
- The exact schema of Meute's `inbox.py dump` against live state.
- Second user's agent CLI and account eligibility, and the credential-isolation approach above.
- Whether the repo keeps the working title "État-major".
