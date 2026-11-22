# État-major: Product & Technical Spec

Last updated 2026-11-21. Working title. Status: pre-implementation. This file is the earlier agent-command-center design and is partly superseded; see the banner below and VISUALIZATION-ARCHITECTURE.md. It began as a Claude doc whose two diagrams (architecture and roadmap) are not reproduced here; the text below carries the same information.

> **Direction changed (2026-11-21).** The product is now a repository-intelligence and progress-visualization app, not an agent command center. See [VISUALIZATION-ARCHITECTURE.md](VISUALIZATION-ARCHITECTURE.md) and [VISUALIZATION-ROADMAP.md](VISUALIZATION-ROADMAP.md); they win over this file. Sections below carry a **Superseded** or **Kept** note. Superseded text is left for history, not as a plan.

## Vision

> **Partly superseded.** The strategic view and phone access survive as the Build and Progress views and Codeman's terminal. Planning agent, runner and sandboxed execution in "A day with the finished product" are out of scope.

État-major is a self-hosted command center that gives one person, or a small family, a strategic view over a fleet of coding agents running in tmux. It starts from goals (initiatives), not sessions, and shows what is moving, what is stuck and what needs a human decision.

**A day with the finished product**

- **Morning:** open one URL on a laptop or phone. Home shows initiatives with progress, blockers and token spend per initiative. A "needs you" strip at the top lists approvals, questions from agents and failed runs. Nothing else competes for attention.
- **Planning:** say "get the billing migration to a working prototype by Friday". A planning agent drafts tasks with acceptance criteria under that initiative. You edit and approve them.
- **Execution:** the runner takes ready tasks and starts each in its own git worktree and tmux session inside a sandboxed container, and updates the card from Claude Code hooks.
- **Intervention:** any card opens the real terminal for its session. Watch, type or take over without losing state.
- **Overnight:** the runner works the ready queue inside per-user budgets and sends a digest in the morning: shipped, blocked, needs a decision.
- **Phone:** approve, reprioritize, answer an agent's question, or open the terminal.

**Who it is for**

- First: the owner, working alone on one homelab. A second adult user comes later, with their own subscription.
- Later: anyone who runs coding agent CLIs and wants a strategic layer above their terminals. Published as an open-source repo.

## North stars

> **Superseded** by the three views and goals in the architecture document. Phone terminal and voice now belong to Codeman; unattended runs to Meute.

Four requirements every decision is judged against. Items 1 to 3 shape the first releases; item 4 is on the roadmap.

| # | North star | What it means | Roadmap | Status |
| --- | --- | --- | --- | --- |
| 1 | Coding on the go | Work from a phone through a web interface to tmux, with audio input and output as an option | Phases 3 and 6; voice added after | Not started |
| 2 | Strategic view per project | Each project's progress shown over a roadmap | Phase 2 | Not started |
| 3 | Unattended workflows | Unattended runs that tie into meute, with progress tracked on the board | Phase 5 | Not started |
| 4 | Multi-user | A second person works in the same environment under their own login | Roadmap, after 1 to 3 | Not started |

## Principles and hard constraints

> **Mixed.** Kept: 2 (no credentials), 3 (Git holds intent; derived state is not written to files), 7 (public AGPL, no personal data). Superseded: 1 (driving CLIs in tmux), 4, 5 (adapters and the four old contracts) and 6 (runner safety), because État-major no longer executes agents. See `CLAUDE.md` for the current constraints.

Seven rules decide every design question below.

1. **Drive the real CLIs.** Agents are `claude`, `codex` and similar, running inside tmux under the user's own login. État-major never calls a model API with a subscription login and never proxies subscription OAuth.
2. **Never hold credentials.** A profile stores a pointer (a config directory path or an environment variable name), never a secret.
3. **Git holds intent; a local store holds runtime state.** Initiatives, projects and tasks are markdown with frontmatter: title, acceptance criteria, priority, owner and intent. Runtime state (sessions, events, spend, approvals) lives in an uncommitted local store, and a running task is derived from session liveness, never written to a file. The UI is a view over both, and the files stay editable in Obsidian or any editor.
4. **Planning is the board's job; execution is tmux's.** A card links to a session and worktree. It does not run anything itself.
5. **Agent-agnostic from day one.** Claude Code is the first adapter; Codex follows, and the interface leaves room for others. Everything else is composed, not rebuilt: tmux, podman, a web terminal and ntfy are used as they are, and meute, atelier and Navette stay separate repos that connect through four contracts (the task file format, the event schema, the adapter interface and the runner API).
6. **Safe by default.** The runner defaults to dry-run. Merges, pushes and any destructive action need explicit approval from a human with the right role. Push credentials never enter a container; a host-side step pushes after approval. Unattended runs are opt-in per user.
7. **Public and AGPL-3.0.** No personal paths, hostnames or keys in the code. All of that lives in config files, with a seeded demo workspace in the repo.

## Users and isolation

> **Superseded** for the first deployment (trusted family, one machine). Credential isolation for a second user remains an open, verified-before-use item in the architecture document.

The design is multi-user from the start, but the first releases ship with one user. Every user is a separate security domain that shares one board. Nothing a user's agents touch is reachable by another user's agents unless a shared initiative says so.

| Layer | Mechanism | Why |
| --- | --- | --- |
| Identity | Per-user token over Tailscale; loopback-only by default | No auth system to build first; safe on a LAN |
| Sessions | One Unix user or VM per person; the tmux socket is a convenience, not the boundary (`tmux -L <user>`) | A user cannot list or attach to another's sessions |
| Processes | One container per user per project, built on atelier | Credentials, files and shell history stay separate |
| Credentials | Per-user profile pointing to that user's own Claude config directory or key variable | Each person authenticates with their own account |
| Files | Per-user worktrees and config directories | No cross-user writes |
| Visibility | Own work by default; shared initiatives are an explicit opt-in | Family can collaborate without exposing everything |

**Roles:** `owner` (manages users, budgets and the router policy) and `member` (own work plus shared initiatives). Approvals for merges and pushes belong to the task's owner. Terminal attach is owner-only, and no one can open another person's terminal. All users are adults with their own accounts.

**Out of scope at first:** operation with more than one user in the first releases (north star 4), SSO, organizations, billing, and any hosted multi-tenant mode.

## Data model

> **Partly kept.** The status lifecycle with `running`, `needs-you` and `failed` is superseded by the derived columns in the architecture document. The task-file contract and the stored-status rule are implemented (`docs/contracts/task-file.md`). The runtime store is superseded by a rebuildable cache; In Progress and Review are now derived from Git evidence.

Intent lives in markdown files in a git repo, in three levels. Runtime state lives in an uncommitted local store (SQLite or JSONL) that records hook events, spend and approvals. The strategic view is computed from both.

```text
workspace/
  initiatives/example-initiative.md
  projects/example-service.md
  tasks/example-service/0042-schema-mapper.md
  .etat-major/config.yaml     # users, profiles, router policy
```

Example task file:

```yaml
---
id: 0042
title: Schema mapper for the example service
initiative: example-initiative
project: example-service
owner: alice
status: ready
priority: 2
acceptance:
  - Maps all source tables listed in docs/sources.md
  - Unit tests pass in CI
# runtime state (session, spend) is kept outside git
budget_tokens: 400000
---
Free-form description and notes.
```

**Status lifecycle:** `draft` → `ready` → `running` → `needs-you` → `review` → `done`, plus `blocked` and `failed`. Only intent states (`draft`, `ready`, `blocked`, `done`) are written to the file, and only a human writes `done`. The states `running`, `needs-you`, `review` and `failed` are derived from session liveness and hook events in the runtime store.

**Hierarchy rules:**

- An **initiative** has an outcome, a target date and an owner. It owns projects.
- A **project** maps to one repo or workstream. It owns tasks.
- A **task** is the unit an agent can pick up: one worktree, one session, acceptance criteria a human can check.

## Model router

> **Superseded.** État-major launches no agents, so it has no router, profiles or fallback policy.

The router chooses which agent CLI, model and credential profile runs a task. It works at the agent level, not the HTTP level: a subscription login cannot be proxied, so the only thing it can safely choose is which locally logged-in CLI to start.

**Three parts**

1. **Adapters.** One interface per agent CLI: `start(task, workspace, profile)`, `resume`, `send`, `status`, `usage`, `capabilities`. Status comes from hooks first and log parsing second.
2. **Profiles.** Each user has one or more. A profile has a kind (`cli-login` or `api-key`), a pointer to its credential (a config directory or an environment variable name) and optional limits. No secret is stored.
3. **Policy.** A YAML file maps task attributes to an ordered list of choices.

```yaml
roles:
  planner:  { prefer: [claude-code/opus],  fallback: [codex/default] }
  worker:   { prefer: [claude-code/sonnet], fallback: [api/cheap-model] }
  reviewer: { prefer: [codex/default],     fallback: [claude-code/sonnet] }
windows:
  overnight: { use: spare-capacity, stop_at: 90% }
on_limit_reached: wait_for_reset   # or: next_choice
```

**The two profile kinds**

| Kind | Runs through | Typical use |
| --- | --- | --- |
| `cli-login` | The user's own `claude` / `codex` login inside tmux | Strong models for planning and coding |
| `api-key` | Any OpenAI-compatible endpoint (an OmniRoute gateway is one option) | Cheap or free models for bulk work, summaries, digests |

OmniRoute is a backend for `api-key` profiles only. Claude and Codex subscriptions stay on their native CLI logins.

**Invariant, enforced in code and tested:** routing never crosses users. A task owned by a user may only use that user's profiles, and every fallback must also belong to that user. A policy that would violate this fails validation at load time.

**First release:** one profile per task and no fallback chain. Roles, windows and fallbacks arrive with the runner in phase 5. The no-cross-user invariant ships from the start. The launcher shows the auth mode (subscription or metered API key) at every launch, because a stray `ANTHROPIC_API_KEY` in the environment can override a subscription login and bill silently.

## Architecture

> **Superseded** by the component ownership and contracts in the architecture document.

The browser reaches the board and the web terminal over Tailscale. The runner starts work through the router, inside the user's container. Hooks in each session report status back to the board. Nine components in three layers: clients (browser, optional phone client), control plane (board, API, router, runtime store) and execution (runner, tmux sessions, containers).

**Integration points**

- **Navette:** optional client of the same API; a responsive web page covers the phone first.
- **meute:** becomes the runner, a client of the board's API.
- **atelier:** supplies the container images and entry script.
- **OmniRoute:** serves `api-key` profiles only.

**Four contracts:** components connect through the task file format, the event schema that hooks and webhooks post, the adapter interface and the runner API. tmux, podman, a web terminal (ttyd or Agentboard) and ntfy are used as they are and need no integration.

**Security rules:** the web terminal is a remote shell, so attach is owner-only and lands inside the container, websocket origins are checked and agent-written markdown is sanitised. Push credentials never enter a container. An egress allowlist is mandatory for unattended runs. Each session gets its own hook token, and hook reports are treated as hints.

**Voice (north star 1, after phase 6):** the browser captures speech and plays replies. The speech-to-text and text-to-speech engines are pluggable and chosen later. Voice is a client feature and does not touch the contracts.

## Recommended architecture

> **Superseded** (control plane, runner and events). The Python and thin-frontend lean carries over; see the architecture document, "Technology".

One small control-plane service, with everything else adopted. This is a lean from the research in [RESEARCH.md](RESEARCH.md), not a final decision; a one-weekend spike (below) confirms or overturns it.

| Layer | Choice | Status |
| --- | --- | --- |
| Execution | tmux, one Unix user per person, git worktrees (workmux), rootless containers (atelier) | Adopt |
| Access | Tailscale; ntfy for notifications | Adopt |
| Web terminal | Codeman first, ttyd as fallback, as a separate process; native `tmux attach` always works | Adopt, test |
| Task files | Markdown with frontmatter in git, Backlog.md format if it can carry acceptance criteria and owner | Borrow |
| Events | Claude Code and Codex hooks post to a local API that writes to SQLite; schema borrowed from agents-observe | Borrow |
| Control plane | One service: reads task files and the store, computes roll-ups, serves the web UI and API. Python backend (FastAPI, SQLite), thin frontend (HTMX or a small Svelte or React app) | Build |
| Runner | meute, a separate Python repo and client of the control-plane API; systemd timers, bounded retries, dry-run by default, fresh sessions from a handoff note, approval before merge, host-side push | Build |
| Router | First release: one profile per task, plus the no-cross-user check | Build |
| Voice | Phone dictation into an editable field first; engines chosen later | Later |

**Why Python for the backend:** the service is mostly glue (frontmatter, SQLite in the standard library, subprocess and tmux calls, git, systemd), and the runner, hook scripts and any voice engines are Python-first. The reusable MIT projects (tmux-kanban, Lumbergh) and the overnight-runner references are Python. Components such as Codeman run as separate processes, so their language does not constrain this one. A web UI needs some JavaScript either way; a board with roll-ups, an approval inbox and terminal links does not need a heavy single-page app. No Rust daemon at first, because ttyd and Codeman already handle the PTYs; Navette stays an optional client. TypeScript end to end is defensible if a rich frontend turns out to be needed.

**What is built here:** the roll-up and strategic view, the control plane, the runner glue and the multi-user isolation. Nothing found in the research does these.

**Spike before committing (about a weekend):** run Codeman, create a Backlog.md-style task folder, and write a hook script that records events into SQLite. If the three fit together and one roll-up query answers "what needs me", the stack is settled.

## Strategic view

> **Partly superseded.** It becomes the Progress view and portfolio page, but its inputs (`running`, `needs-you`, `failed`, hook events, spend) no longer exist; "needs attention" is recomputed from Git, PR and check evidence. The morning digest becomes an optional summary of Meute run artifacts.

The home screen answers four questions without opening a single session. Every number is computed from the task files and hook events.

| View | Answers | Computed from |
| --- | --- | --- |
| Initiative roll-up | How far along is each outcome, and is its date still realistic? | Task status counts and the initiative's target date |
| Needs you | What is waiting on a human right now? | Tasks in `needs-you`, `review`, `failed`; pending approvals |
| Idle projects | Where are agents sitting idle because nothing is ready? | Projects with zero `ready` tasks and no running sessions |
| Spend and capacity | What did each initiative and each user consume, and what is left? | Adapter usage reports, per profile and per initiative |

**Morning digest:** one card generated overnight. It lists what shipped, what is blocked and why, and the decisions waiting for each user. It is a summary of task events, not a log dump.

**Phone flows (the first release is read-mostly):**

- Glance at the home roll-up and the needs-you strip.
- Approve or reject a review, reprioritize a task, answer an agent's question.
- Open a session's terminal when something goes wrong.

Creating or deeply editing tasks stays a desktop job until the rest is solid.

## Milestones

> **Superseded** by [VISUALIZATION-ROADMAP.md](VISUALIZATION-ROADMAP.md).

The order is the reverse of the finished product: the data model and roll-ups come first because every later layer reads them, and the phone polish comes last because it depends on all of them. Each phase ends at its gate, and none starts before the previous gate passes.

1. **Foundation:** data model, task files, event schema.
2. **Roll-ups:** the initiative, project and task views, derived from evidence (merged pull requests, test results, releases), never from agent self-estimates.
3. **Session binding:** cards linked to tmux sessions and worktrees through hooks; the web terminal.
4. **Planning agent:** drafts tasks with acceptance criteria under an initiative.
5. **Runner and router:** meute becomes the runner. Adds one more exit test: a routing-policy test proving no task can fall back to another user's profile.
6. **Digest and phone:** the morning digest, the approval inbox and phone polish.

Phase 4 can move after phase 5, since hand-written tasks are enough to prove execution. North stars map to phases as follows: north star 1 to phases 3 and 6, north star 2 to phase 2, north star 3 to phase 5, and north star 4 after phase 6.

## Build vs adopt

> **Kept** as research, with updates in `CLAUDE.md`. The runner, session-binding and router rows no longer apply.

Adopt or borrow for every layer except the cross-project roadmap, the multi-user control plane and the glue between them. Field reports below come from Reddit threads as of 21 Nov 2026; most are author or single-user accounts, so each pick is a candidate to test, not a settled choice.

| Layer | Use | Why | Caveat |
| --- | --- | --- | --- |
| Phone to tmux | Tailscale + tmux + ttyd; Termius or mosh as fallback | The most-reported setup; native `tmux attach` always works | Dropped connections on trains; AgentDeck's author says it has no authentication |
| Web dashboard | Test [Codeman](https://github.com/Ark0N/Codeman) first | Serves real tmux sessions for Claude Code and Codex, with notifications | Author-reported daily use; multi-user isolation unconfirmed |
| Phone client (candidate) | [Herdr](https://herdr.dev/) | Phone app opens real terminals and shows who needs you; OSC 7501 status protocol could feed the event schema | Vendor page only; agents run in its own server, not tmux, which conflicts with principle 1; no web UI or multi-user mentioned. Test at phase 3 beside Codeman and ttyd |
| Task files | [Backlog.md](https://github.com/MrLesk/Backlog.md) | Plain files in git; one user kept it after trying many helpers | No supervision, terminals or cross-repo roadmap |
| Worktrees | [workmux](https://workmux.dev/guide/status-tracking/) | Branch and tmux window per task, agent state from hooks | Hook coverage differs between Claude Code and Codex |
| Events and usage | agents-observe schema, ccusage | Hook events into SQLite; local usage numbers | Token counts are approximate |
| Overnight runner | Build thin; borrow queue design from claude-code-queue and reset parsing from [unsnooze](https://github.com/saaranshM/unsnooze) | Durable markdown queue, bounded retries | Two unrelated projects share the name claude-overnight; unsnooze's first release misread a reset time |
| Voice | Phone dictation into an editable field; optional spoken reply | Little field evidence for full two-way voice | Never auto-read terminal logs; test background audio |
| Roadmap view | Build | No tool found that ties goals to tasks, commits, tests and releases | This is the product's differentiator |
| Avoid | Vibe Kanban; account switching or pooling | A May 2026 comment says its company shut down (unverified); switching accounts to dodge limits is a policy risk | |

**Rules taken from field reports**

1. Resuming a large session after a limit reset can cost a large share of the window (one user reported about 30% of five hours). The runner starts a fresh session from a handoff note by default.
2. Show the auth mode at every launch: subscription or metered API key. A stray `ANTHROPIC_API_KEY` can override a subscription login and bill silently.
3. Progress is derived from evidence (merged pull requests, test results, releases), never from an agent's own estimate.
4. One approval inbox lists every agent waiting on a human, with what each approval would permit.
5. Agents run in a worktree per task with human approval before merge; one reported agent deleted a user's design docs.
6. No cost model assumes a headless multiplier. One user measured `claude -p` draining the five-hour limit about 1.49× faster; treat that as a reason to measure, not as a constant.
7. Each person's own installed CLI under their own Unix user. The command center never proxies OAuth credentials, pools subscriptions or switches accounts.

The closest published architecture to this design is a [Reddit write-up](https://www.reddit.com/r/SelfHostedAI/comments/1xva4re/i_run_claude_code_and_codex_agents_as_one_team/) of separate Linux users, systemd and a shared SQLite queue. It is self-reported, not audited. Other threads: [tools that survived daily use](https://www.reddit.com/r/ClaudeCode/comments/1sdgwp4/tools_that_have_proven_useful_over_time/), [headless usage measurement](https://www.reddit.com/r/ClaudeCode/comments/1xdk3cn/heads_up_headless_claude_p_eats_your_5hour_limit/), [unsnooze bug report](https://www.reddit.com/r/ClaudeAI/comments/1uv1qjj/unsnooze_autoresumes_claude_codex_and_other_ai/).

## Licensing and compliance

> **Kept.** Re-check Anthropic terms before each release.

The repo is AGPL-3.0. That fixes what code can be reused and how Claude accounts may be used. Components run as separate processes, so their licenses do not combine with the AGPL code.

**Reusable code (verify each license in the repo before forking; these come from search listings)**

| Project | License | Verdict |
| --- | --- | --- |
| [tmux-kanban](https://pypi.org/project/tmux-kanban/) | MIT | Usable |
| [Lumbergh](https://pypi.org/project/pylumbergh/) | MIT | Usable |
| [Codeman](https://github.com/Ark0N/Codeman) | MIT | Usable |
| [Vibe Kanban](https://github.com/BloopAI/vibe-kanban) | Apache-2.0 | Compatible with AGPL-3.0, but community-maintained since the company shut down |
| [amux](https://raw.githubusercontent.com/mixpeek/amux/main/README.md) | MIT + Commons Clause | Not usable: the Commons Clause restricts resale |
| [Agent Kanban](https://github.com/saltbo/agent-kanban) | FSL-1.1-ALv2 | Not usable: functional source license |
| [Herdr](https://herdr.dev/) | Apache-2.0 (per its page) | Compatible with AGPL-3.0; verify in its repo before adopting |
| [Kanvibe](https://github.com/rookedsysc/kanvibe), [Agentboard](https://github.com/gbasin/agentboard/wiki) | Not confirmed | Check before use |

**Anthropic terms, as design constraints**

- Accounts and keys are not shared. The [Consumer Terms](https://www.anthropic.com/legal/consumer-terms) say you may not share your login or API key with anyone else or make your account available to anyone else. Every user logs in with their own account.
- The minimum age is 18, or the local age of consent if higher. A user who cannot hold their own account needs a different supported path; confirm it with Anthropic before building for it.
- Subscription credentials are not proxied. Anthropic's [legal and compliance page](https://code.claude.com/docs/en/legal-and-compliance) says third-party developers may not route requests through Free, Pro or Max plan credentials on behalf of their users. État-major only launches the user's own CLI.

These terms changed several times in 2026. Re-check them before each release.

## Open questions

> **Mostly superseded.** The current list is in the architecture document.

- [ ] Web terminal: adopt Agentboard or ttyd as is, or embed xterm.js directly in the board?
- [ ] Base: fork tmux-kanban or Lumbergh, or start fresh and borrow ideas?
- [ ] Stack: current lean is a Python backend (FastAPI, SQLite) with a thin frontend; confirm with the spike. TypeScript end to end is the alternative.
- [ ] Runner: current lean is to keep meute separate and talk to the board over its API.
- [ ] Second user: which agent CLI and account path, and do they meet the account requirements?
- [ ] Budgets: how to measure per-profile subscription usage when CLIs expose little usage data?
- [ ] Repo name, license header and the demo workspace to ship with the first release.
- [ ] Voice: which speech-to-text and text-to-speech engines, and local or cloud?
- [ ] Overnight runs: confirm they are opt-in, and re-read the current subscription terms before phase 5.
- [ ] Runtime store: current lean is SQLite, because roll-ups need queries; JSONL is the alternative.
- [ ] Try Codeman as the web terminal layer before writing one; confirm its license and how it handles one Unix user per person.
- [ ] Confirm Backlog.md's file format can carry acceptance criteria and owner, or define the task contract on top of it.
- [ ] Re-read Anthropic's current terms on `claude -p` and third-party tools before building the overnight runner.
