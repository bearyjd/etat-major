# État-major (working title)

Self-hosted command center for coding agents running in tmux. It gives a strategic view (initiative > project > task) over agents, and composes existing tools instead of rebuilding them. Public repo, AGPL-3.0, French naming for projects. Owner: the repo maintainer. Full spec: docs/SPEC.md (exported from the Claude doc "État-major — Product & Technical Spec"). If this file and the spec disagree, the spec wins; tell the maintainer.

## North stars (judge every decision against these)
1. Coding on the go: web interface to tmux from a phone, with audio input and output as an option. Phases 3 and 6; voice after.
2. Strategic view per project: each project's progress overlaid on a roadmap. Phase 2.
3. Unattended workflows that tie into meute, with progress tracked. Phase 5.
4. Multi-user (roadmap, after 1 to 3): a second user (family member), under their own login and their own subscription.

## Hard constraints
1. Drive the real CLIs (`claude`, `codex`) inside tmux under each user's own login. Never call a model API with a subscription login. Never proxy, harvest or pool OAuth credentials. Never switch accounts to dodge limits.
2. Never store credentials. A profile holds a pointer (config dir path or env var name), not a secret.
3. Git holds intent (markdown + frontmatter: title, acceptance criteria, priority, owner, draft/ready/blocked/done). A local uncommitted store (SQLite or JSONL, undecided) holds runtime state: sessions, hook events, spend, approvals. `running`, `needs-you`, `review`, `failed` are derived, never written to files. Only a human writes `done`.
4. Planning is the board's job; execution is tmux's. A card links to a session and worktree and runs nothing itself.
5. Agent-agnostic: Claude Code first adapter, Codex next. Four contracts connect components: task file format, event schema, adapter interface, runner API.
6. Safe by default: runner defaults to dry-run; merges and pushes need human approval; push credentials never enter containers (host-side step pushes after approval); unattended runs are opt-in per user, with an egress allowlist.
7. Public repo hygiene: no personal paths, hostnames or keys in code; config files plus a seeded demo workspace.

## Users and isolation
One Unix user or VM per person (tmux sockets are not a boundary). Per-user containers built on atelier. Terminal attach is owner-only. Roles: `owner`, `member`. Identity: per-user token over Tailscale, loopback-only by default. Routing never crosses users: a task may only use its owner's profiles, including every fallback; policies that violate this fail validation at load. First release ships with one user; multi-user comes after phase 6.

## Model router
Works at the agent-CLI level, not HTTP. Profiles are `cli-login` or `api-key`. OmniRoute (or any OpenAI-compatible endpoint) backs `api-key` profiles only. First release: one profile per task, no fallback chain; roles, windows and fallbacks arrive with the runner in phase 5. Show the auth mode (subscription or metered API key) at every launch: a stray `ANTHROPIC_API_KEY` can override a subscription login and bill silently.

## Milestones (reverse from the finished product)
1. Foundation: data model, task files, event schema.
2. Roll-ups: initiative/project/task strategic view, derived from evidence (merged PRs, test results, releases), never agent self-estimates.
3. Session binding: cards to tmux sessions and worktrees via hooks; web terminal.
4. Planning agent (may move after 5).
5. Runner and router: meute becomes the runner; routing-policy test proving no cross-user fallback.
6. Digest and phone: morning digest, approval inbox, phone polish.
Each phase ends at a gate; none starts before the previous gate passes.

## Build vs adopt (field reports as of 2026-11-21; candidates to test, not settled)
- Phone to tmux: Tailscale + tmux + ttyd; Termius or mosh fallback. Keep native `tmux attach` as an escape hatch.
- Web dashboard: test Codeman first (check license and one-Unix-user-per-person handling).
- Task files: Backlog.md, unless its format cannot carry acceptance criteria and owner.
- Worktrees: workmux (or Worktrunk). Events and usage: agents-observe schema, ccusage (counts are approximate).
- Overnight runner: build thin. Borrow queue design from claude-code-queue and reset parsing from unsnooze. Start fresh sessions from a handoff note instead of resuming large ones (resume can burn a large share of the window). Never encode a headless cost multiplier; measure.
- Voice: phone dictation into an editable field, optional spoken final reply. Never auto-read terminal logs.
- Roadmap view: build. No existing tool ties goals to tasks, commits, tests and releases.
- Avoid: Vibe Kanban (maintainer status doubtful), amux (Commons Clause), Agent Kanban (FSL), account switching or pooling.
- Verify every license in the component's own repo before adopting.

## Recommended architecture (lean, not final; confirm with a weekend spike)
One small control-plane service; adopt everything else. Execution: tmux, one Unix user per person, git worktrees (workmux), rootless containers (atelier). Access: Tailscale, ntfy. Web terminal: Codeman first (ttyd fallback) as a separate process; native `tmux attach` always works. Task files: markdown + frontmatter in git, Backlog.md format if it fits. Events: hooks post to a local API writing to SQLite (schema borrowed from agents-observe). Control plane (build): Python backend (FastAPI, SQLite) computing roll-ups and serving a thin web UI (HTMX or small Svelte/React) and the API. Runner (build): meute, separate Python repo, a client of the API; systemd timers, bounded retries, fresh sessions from a handoff note. No Rust daemon at first. Spike: run Codeman, a Backlog.md-style task folder, and a hook-to-SQLite script; one roll-up query should answer "what needs me". See docs/SPEC.md, "Recommended architecture".

## Open questions
Web terminal (Agentboard, ttyd or embedded xterm.js); fork tmux-kanban or Lumbergh vs start fresh; stack (lean: Python backend with a thin frontend; TypeScript end to end is the alternative); meute inside this repo or separate (lean: separate, talking to the API); second user's agent CLI and account eligibility; per-profile usage measurement; voice engines; runtime store (lean: SQLite); repo name, license header, demo workspace. Re-read Anthropic's current terms on `claude -p` and third-party tools before building the overnight runner; they changed several times in 2026.

## Related projects (separate repos, connect via the four contracts)
meute (fleet runner), atelier (rootless podman images, agent-enter.sh), Navette (RN + Rust PTY daemon, optional client). Infra: homelab on Tailscale; OmniRoute gateway for api-key profiles.

## How to work in this repo
- Small, reviewable steps; tests with every contract change.
- Reddit research must go through Codex or ChatGPT, not Claude's own search (it cannot reach Reddit). See the `reddit-via-codex` skill.
- Keep secrets, hostnames and personal paths out of the repo.
