# Phase 1 spike: Backlog.md task format and hook-to-SQLite events

Date: 2026-11-21. Scope: two of the three spike items in SPEC "Recommended architecture". Codeman is not covered here.

## Part 1: can Backlog.md carry acceptance criteria and owner?

**Evidence.** Backlog.md v1.57.0 (MIT, commit `444814b`, shallow clone to a temp dir, read-only). Sources: `backlog/tasks/*.md`, `src/markdown/parser.ts`, `src/markdown/serializer.ts`, `src/markdown/structured-sections.ts`, `backlog/config.yml`.

| Need | Backlog.md | Fit |
| --- | --- | --- |
| Markdown + frontmatter in git | Yes, one file per task under `backlog/tasks/` | Yes |
| Acceptance criteria | In the **body**, not frontmatter: a `## Acceptance Criteria` section between `<!-- AC:BEGIN -->` and `<!-- AC:END -->`, as numbered checkboxes (`- [ ] #1 text`) | Carries it, but as a checklist with checked state |
| Owner | `assignee`, a **list** of strings; `reporter` is separate | Close; SPEC wants one `owner` |
| Priority | `priority`, a free string (`high`/`medium`/`low` by default); `ordinal` for order | Differs from SPEC integer priority |
| Status | `status`, free string from `config.yml` `statuses` (default To Do / In Progress / Done) | Configurable, but one flat list; no intent-vs-derived split |
| initiative, budget, acceptance as data | No `initiative` field. `project` and `milestone` exist. Parser and serializer use a fixed field list; `serializeTask` rebuilds frontmatter from it | Extra keys like `budget_tokens` are not in the model. I did not run a rewrite to test whether they survive |

**Gaps against our hard constraints.**

1. Constraint 3: only humans write `done`, and `running`, `needs-you`, `review`, `failed` are never written to files. Backlog.md's CLI, web UI and agents write `status` freely, and its "In Progress" is a file-level runtime state.
2. Criteria checkboxes record done-ness in git, which an agent can tick. We want a human to check criteria, and `done` to be a human act.
3. The status lifecycle (`draft`, `ready`, `blocked`, `done`) is only expressible by renaming statuses in config. Backlog.md also keeps drafts in a separate folder.
4. Our hierarchy (initiative > project > task) has no native slot for `initiative`, `owner` or `budget_tokens`.

**Decision.** Define our own task file contract (SPEC "Example task file"), and borrow only Backlog.md's conventions: one markdown file per task, YAML frontmatter, a stable id in the filename, and a plain checklist for criteria. Do not depend on the Backlog.md tool or promise round-trip compatibility. Reasons: its format can carry criteria and an owner only approximately (body checklist, assignee list), and its status model conflicts with constraint 3. SPEC row "Task files: Backlog.md format if it can carry acceptance criteria and owner" resolves to **no, own contract**, so the SPEC table should be updated by the maintainer. Backlog.md stays usable as an optional read-only importer later.

Caveat: this was read from source, not exercised. A later check could run `backlog task edit` on a file with extra keys.

## Part 2: hook to SQLite

`scripts/hook_record.py --db <file>` reads one Claude Code hook JSON payload on stdin and inserts one row into `events`. Install it as a hook command, for example `python3 scripts/hook_record.py --db ~/.local/state/etat-major/events.db` (the path comes from config, never the repo). Exit 1 and a stderr message for bad JSON or a missing `session_id` or `hook_event_name`; nothing is written.

Stored columns: `ts`, `session_id`, `event`, `tool_name`, `cwd`, `notification_type`. **Deliberately not stored:** `tool_input`, prompts, `transcript_path` and the free-text notification `message`, so a secret can never reach the store (tests assert this). The database file is created with mode 0600; keep it in a private directory. Per SPEC, hook reports are hints, and the per-session hook token is not part of this spike.

### Roll-up: "what needs me"

State is derived from each session's latest state-relevant event and never written. A `permission_prompt` or `elicitation_dialog` `Notification` means the agent waits on a human (`needs-you`), `Stop` means the turn ended and awaits a look (`review`), and `StopFailure` means `failed`. Other notification types (`idle_prompt`, `auth_success`) are ignored. A later `UserPromptSubmit`, `PreToolUse` or `PostToolUse` clears the session from the list.

```sql
SELECT e.session_id,
       CASE e.event
            WHEN 'Notification' THEN 'needs-you'
            WHEN 'StopFailure' THEN 'failed'
            ELSE 'review'
       END AS state,
       e.ts
FROM events e
WHERE e.id = (
        SELECT MAX(id) FROM events s
        WHERE s.session_id = e.session_id
          AND ((s.event = 'Notification'
                AND s.notification_type IN ('permission_prompt', 'elicitation_dialog'))
               OR s.event IN ('Stop', 'StopFailure', 'UserPromptSubmit',
                              'PreToolUse', 'PostToolUse')))
  AND e.event IN ('Notification', 'Stop', 'StopFailure')
ORDER BY e.id;
```

It is exported as `NEEDS_ME_SQL` in the script and covered by `tests/test_hook_record.py` with sample payloads (running, waiting, finished and resolved sessions).

### Limits and open points

- Sessions map to tasks only by `session_id`. Binding a session to a task and worktree is phase 3.
- `StopFailure` and the `Notification` subtypes (permission prompt vs idle) should be confirmed against the Claude Code version in use. The script stores the event name as received.
- Latest-event logic ignores liveness. A killed session stays "review" until tmux liveness is joined in.
- SQLite vs JSONL: SQLite works well for this query, which supports the lean in SPEC. Still open for the maintainer.
- Codeman, the third spike item, is not run here.
