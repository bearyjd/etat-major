# Research notes: what people run today

Compiled 2026-11-21 from Reddit threads (searched by ChatGPT, not independently re-verified) plus GitHub and web searches. Treat every item as a candidate to test. Evidence labels: **firsthand** (a user describing their own use), **author** (the tool's author describing it), **unverified** (could not confirm).

Three distinctions drive the design:

- Session persistence is not task autonomy. tmux keeps a process alive after a phone disconnects; it does not resolve permission prompts, exhausted quotas or failing tests.
- A session dashboard is not a project roadmap. Most dashboards show what is running, not whether projects are moving toward their goals.
- Subscription access is not a general API entitlement. How agents are launched and authenticated matters, especially for third-party orchestration.

## 1. Phone access to tmux

| Setup | Evidence | Notes |
| --- | --- | --- |
| Tailscale + tmux + Termius | Firsthand, strong | The most common baseline. Breaks on phone backgrounding, reconnects, modifier keys, and navigating many sessions. [Feb discussion](https://www.reddit.com/r/ClaudeCode/comments/1r6dnrl/the_claude_code_for_mobile_youve_been_looking_for/), [commuter reports drops](https://www.reddit.com/r/ClaudeCode/comments/1v63sj8/vibe_coding_from_my_iphone_on_the_train_whats/) |
| Tailscale + mosh + tmux | Firsthand | Better on unreliable mobile networks. One user moved to a remote server instead of keeping a laptop awake. [Hetzner setup](https://www.reddit.com/r/ClaudeAI/comments/1w5bx9x/why_i_moved_claude_code_off_my_laptop_and_onto_a/), [mosh comparison](https://www.reddit.com/r/ClaudeCode/comments/1t5svi9/see_my_terminal_claude_code_session_from_on_my/) |
| ttyd + tmux (NomadTTY, AgentDeck) | Author | Closest to a browser terminal. Issues: keyboard handling, websocket recovery, ownership, security. AgentDeck's author says it has no built-in authentication. [NomadTTY](https://www.reddit.com/r/SideProject/comments/1vbzuw7/nomadtty_a_selfhosted_terminal_that_survives_your/), [AgentDeck](https://www.reddit.com/r/ClaudeCode/comments/1wf3vux/i_put_claude_code_behind_a_browser_ui_where/) |
| Claude Code Remote Control | Mixed | Convenient natively, but not a substitute for arbitrary tmux sessions or Codex. Some report flaky continuation or trouble spawning side sessions. [Side sessions](https://www.reddit.com/r/ClaudeCode/comments/1xk5662/issue_with_creating_side_sessions_when_using/) |
| Happy | Mixed, individual reports | Worth testing; some tmux users prefer direct terminal access. [Comparison](https://www.reddit.com/r/ClaudeAI/comments/1ro9ktm/i_built_a_mobile_tmux_client_so_i_can_run_claude/) |

Voice has little field evidence. A workable design is phone dictation into an editable field, with optional spoken playback of only the agent's final reply. Keep native `tmux attach` as an escape hatch so a dashboard is never the only way to recover a live agent.

## 2. Dashboards and boards

| Tool | Evidence | Notes |
| --- | --- | --- |
| [Codeman](https://github.com/Ark0N/Codeman) | Author | Serves real tmux sessions to browsers for Claude Code and Codex, with notifications. Multi-user isolation unconfirmed. [Thread](https://www.reddit.com/r/ClaudeCode/comments/1vasnh5/i_built_mission_control_for_claude_code_open/) |
| [Backlog.md](https://github.com/MrLesk/Backlog.md) | Firsthand | Plain markdown tasks in git; one user kept it after trying many helpers. No supervision or terminals. [Thread](https://www.reddit.com/r/ClaudeCode/comments/1sdgwp4/tools_that_have_proven_useful_over_time/) |
| [Herdr](https://herdr.dev/) | Unverified (vendor page only) | Native app (macOS, Linux, Windows; iOS and Android) that runs agents in its own server, herdr-core, and shows working/done/waiting status. Phone app opens the real terminal and takes typed or spoken replies; remote machines over SSH or Tailscale. Open status protocol (OSC 7501) and an `hc` command for agent-to-agent helpers. Apache-2.0. Not tmux-based (status is not reported through tmux), no web UI, no multi-user isolation mentioned, no roadmap layer. |
| [Cline Kanban](https://cline.bot/kanban) | Mixed | Worktree per task, diff review, several CLI backends. Reports of install problems and an agent deleting design docs. [Launch](https://www.reddit.com/r/CLine/comments/1s4catz/introducing_cline_kanban/), [issue](https://www.reddit.com/r/CLine/comments/1s76d1c/cant_connect_claude_to_cline_kanban/) |
| [Vibe Kanban](https://github.com/BloopAI/vibe-kanban) | Unverified status | A May 2026 comment says its company shut down; not independently confirmed. Earlier reports of merges marked successful with uncommitted changes. |
| [workmux](https://workmux.dev/guide/status-tracking/) | Docs only | Branch and tmux window per task; agent state from hooks, which differ per CLI. |
| Claude Squad | Ambiguous name | A parallel-session manager and a separate "multiplayer" project share the name. [Multiplayer thread](https://www.reddit.com/r/ClaudeAI/comments/1svmpkv/built_claude_squad_a_multiplayer_coding_session/) |
| Agentboard | Unverified | Several similarly named dashboards exist. |

A recurring complaint: running four or five agents is easy; finding the right terminal, task, worktree and blocker is hard. [Discussion](https://www.reddit.com/r/ClaudeAI/comments/1sye8bs/i_built_a_kanban_board_for_claude_code_so_i_can/)

## 3. Overnight and unattended runners

| Tool | Evidence | Notes |
| --- | --- | --- |
| [unsnooze](https://github.com/saaranshM/unsnooze) | Firsthand bug report | Resumes sessions after a limit reset. The first release misread a reset time (fixed). Resuming a large session can burn a lot of the window (one user: about 30% of five hours). [Thread](https://www.reddit.com/r/ClaudeAI/comments/1uv1qjj/unsnooze_autoresumes_claude_codex_and_other_ai/) |
| claude-overnight | Repo only | Two unrelated projects share the name: [a coding swarm](https://github.com/Fornace/claude-overnight) and [a research queue](https://github.com/rohanprichard/claude-overnight). |
| [claude-code-queue](https://github.com/JCSnap/claude-code-queue) | Repo only | Durable markdown queue with retries; at-least-once semantics, so a crashed worker may repeat a task. |
| tmux + systemd + SQLite ([5dive](https://github.com/5dive-ai/5dive)) | Author | Separate Linux users, systemd-supervised agents, shared SQLite queue. Closest published architecture to this design. [Thread](https://www.reddit.com/r/SelfHostedAI/comments/1xva4re/i_run_claude_code_and_codex_agents_as_one_team/) |

What overnight users report:

- **Autonomy gap:** anything beyond narrowly defined tasks needs intervention and repair. [Thread](https://www.reddit.com/r/AI_Agents/comments/1x8zcex/agents_running_247_on_your_laptop/)
- **Headless cost:** one user measured `claude -p` draining the five-hour limit about 1.49x faster across four Max accounts. A single measurement, not an established multiplier. [Thread](https://www.reddit.com/r/ClaudeCode/comments/1xdk3cn/heads_up_headless_claude_p_eats_your_5hour_limit/)
- **Destructive agents:** an agent removed a user's design documents, so isolate in worktrees and require review before merge.

Safety model: worktree and branch per task; rootless containers or per-user VMs; no host-wide sudo, Docker socket or production secrets; per-user quota thresholds; bounded retries with a persisted failure reason; check git state and task identity before resuming; tests and diff review; human approval to merge; a morning summary of completed, blocked, failed and unreviewed work. A runner should stop when it cannot make safe progress.

## 4. Roadmap and strategic progress

No tool found that connects long-term goals to tasks, commits, tests and releases across repositories. That is the gap this project targets.

| Approach | Notes |
| --- | --- |
| Markdown in git | Best low-complexity base. Risks: concurrent edits, stale summaries, agents treating unverified docs as facts. One developer moved from richer memory systems to [three git repos of markdown](https://www.reddit.com/r/ClaudeCode/comments/1xnji7s/my_claude_code_memory_is_3_git_repos_of_markdown/). |
| Backlog.md | See section 2. |
| Linear | Good for queues and milestones; adds an external dependency; parallel agents may pick conflicting tasks. [Workflow thread](https://www.reddit.com/r/ClaudeCode/comments/1tgfm1x/i_didnt_think_this_was_possible/) |
| GitHub Issues and Projects | Natural when work is on GitHub; a closed issue does not prove a feature works. |
| Obsidian | Good for human planning; weaker as an execution database. |
| Plane | Self-hostable, AGPL-3.0; no verified use with an agent fleet. |

Design direction: repository state (goals, decisions, acceptance criteria, task specs) in markdown in git; command-center state (sessions, worktrees, test results, commits, PRs) in a small local database. Progress is derived from observable evidence, not agent estimates.

## 5. Subscription terms and headless use

Anecdotal reports only; terms changed several times in 2026 and must be re-read before each release.

- `claude -p` is a documented headless interface, but that does not mean every third-party orchestrator may consume subscription capacity. Threads: [June](https://www.reddit.com/r/ClaudeCode/comments/1u6vs74/has_anyone_experienced_the_agent_sdk_claude_p_api/), [August](https://www.reddit.com/r/ClaudeCode/comments/1vpdclr/is_claude_p_still_usable/), [October](https://www.reddit.com/r/ClaudeCode/comments/1xbdj0k/october_2026_does_claude_p_consume_subscription/).
- A self-hosted tool that launches the user's own installed CLI is materially different from one that extracts credentials or impersonates the client. [April discussion](https://www.reddit.com/r/ClaudeAI/comments/1sc1620/anthropic_updated_terms_and_conditions_on_using/)
- An `ANTHROPIC_API_KEY` in the environment can take precedence over a subscription login and bill silently, so show the auth mode at every launch.
- Reports of restricted accounts exist but do not show that ordinary CLI automation triggers bans. [Thread](https://www.reddit.com/r/Anthropic/comments/1x7968k/i_got_restricted_within_30minutes_of_using_claude/)

Approach: each person's own installed CLI under their own OS account; no pooling, token harvesting, client impersonation or automatic account switching; let agents hit and report official limits and pause until reset.

## 6. Multi-user with separate subscriptions

- Separate Linux users with native CLI login per person is the best foundation (own UID, home, config, Git identity, processes). Risks: shared repo permissions, worktree ownership, credentials leaking through environment variables, port conflicts.
- Teams paying for individual subscriptions is a reported pattern, but is different from sharing one account. [Thread](https://www.reddit.com/r/ClaudeCode/comments/1rblbhc/claude_code_for_a_team_of_5/)
- Account switching and pooling: avoid as a foundation. [Thread](https://www.reddit.com/r/ClaudeCode/comments/1xhyz18/how_are_you_all_managing_your_multi_accounts/)

Layering: a shared control plane (web auth, project registry, roadmap, queue, notifications, audit); a per-user execution plane (own tmux, CLI config, subscription login, worktrees, processes); a shared collaboration layer (repos, roadmaps, tasks, PRs) with explicit permissions.

## What people say they wish existed

Synthesized from the threads, not verbatim requests: one phone interface for Claude Code and Codex; mobile-to-desktop handoff; a unified approval inbox; a dependable overnight runner; telling real progress from agent activity; cross-repo strategic planning; a source of truth that survives tool changes (markdown in git); safe parallel work; recovery after failure; clear subscription and API billing visibility; first-class mobile voice; real multi-user support; meaningful morning summaries; less maintenance; agent independence; one coherent command center.

## 7. Verified findings on the neighbouring tools (2026-11-21)

Read from each project's code and docs; see [VISUALIZATION-ARCHITECTURE.md](VISUALIZATION-ARCHITECTURE.md) for how they are used. "Verified" means observed in code or by a read-only command.

| Tool | Verified | Unverified |
| --- | --- | --- |
| Trail 0.30.5 (MIT) | Function-level graph in `wiring.json` (`GraphV1`, version 1) with `contains`, `calls`, `imports`, `references`, `implements`, `extends` edges and a confidence label. On this repo (Python): 66 nodes, 167 edges, about 2 s; relations seen were `calls`, `contains`, `imports`, `extends`. Writes into its build target; telemetry on by default. Documented but not reproduced: 28 tree-sitter languages, content-hash incremental reindexing. | Accuracy on large repos and other languages; `references`, `implements` and `lsp_*` edges in practice; graph size at scale; a schema-compatibility promise (none documented). |
| Meute `6b4253b` | Bash and Python, no daemon or database; external scheduling; files and CLI as the interface (`state/log`, `reports/**`, `meute promote`, `meute plan --enqueue`); single-user on the host's own logins; a web UI and TUI exist in its source (not run). | Live schema of `lib/inbox.py dump`; differences on its web-inbox feature branch. |
| Codeman 1.51.1 (MIT) | `/api/v1` REST, SSE and WebSocket terminal; create session then send input; Basic auth, passwordless by default; multi-user separates workspaces but shares one OS account, `~/.claude` and subscription. | Phone-friendly session deep link; whether a per-launch `CLAUDE_CONFIG_DIR` override survives restart for non-granted users; voice implementation completeness; Docker-case credential handling. |
| Floorplan 0.11.0 (MIT) | Zero-dependency Node scripts; scan and build need no model; 5-file Python repo about 0.4 s, 271-file multi-language repo 13 nodes and 547 import edges in about 1.3 s; `graph@1` JSON (undocumented shape), `architecture@1` and `plan@1` documented; blueprint graph contains only planned files, no call edges. | LLM-written architecture quality and cost; viewer; multi-repo behaviour. See `TOOL-EVALUATION.md`. |
| Understand Anything 2.9.8 (MIT) | Claude Code plugin; final graph is LLM-assembled; its deterministic scripts only feed the agents. | Full run and token cost. |
| Herdr (vendor page only) | Nothing. | Everything; see the dashboards table above. |
