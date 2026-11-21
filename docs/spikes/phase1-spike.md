# Phase 1 spike: Backlog.md task format and hook-to-SQLite events

Closes the open question in `docs/SPEC.md` ("Confirm Backlog.md's file format can carry acceptance criteria and owner, or define the task contract on top of it") and gives a minimal hook recorder.

## Part 1: Backlog.md task format

**Inspected:** `MrLesk/Backlog.md`, shallow clone to a temp dir outside this repo, commit `8319797bdf5f5f011a247a9bf3dc2693ec1b1c80` (package version 1.57.0).

### Evidence

- **Layout:** one markdown file per task in `backlog/tasks/`, named `<id> - <Title>.md`. Drafts live in `backlog/drafts/`, and project settings in `backlog/config.yml`.
- **Frontmatter fields written by the serializer** (`src/markdown/serializer.ts`): `id`, `title`, `status`, `assignee` (a list), `reporter`, `created_date`, `updated_date`, `due_date`, `labels`, `milestone`, `dependencies`, `references`, `documentation`, `modified_files`, `parent_task_id`, `subtasks`, `priority`, `type`, `project`, `ordinal`, `onStatusChange`.
- **Acceptance criteria:** a body section `## Acceptance Criteria` holding a checkbox list between `<!-- AC:BEGIN -->` and `<!-- AC:END -->`, with numbered items such as `- [ ] #1 ...`. This is parsed into structured items.
- **Owner:** the closest field is `assignee`. It is a list of strings, which `normalizeAssignee` coerces.
- **Status is free-form and written to the file.** `backlog/config.yml` defines `statuses: ["To Do", "In Progress", "Done"]` by default. There is no `draft`, `ready` or `blocked` in the status list. Drafts are a separate folder and type.
- **Unknown frontmatter keys are preserved** on rewrite (`preserveUnknownFrontmatter` in `src/markdown/frontmatter.ts`), so extra fields of ours would survive Backlog.md edits.

### Decision

**Define our own task contract on top of the Backlog.md layout. Do not adopt its format unchanged.** Backlog.md can carry acceptance criteria and an owner, so the spec's fallback condition is not triggered on those two points. It fails on a different one, the status model:

1. CLAUDE.md hard constraint 3 says only `draft`, `ready`, `blocked` and `done` are written to files, and only a human writes `done`. Backlog.md writes `In Progress` into the file, which is a state we derive. It also has no `ready` or `blocked`.
2. `owner` is a single accountable person for us. `assignee` is a list.

So the contract (to be specified in a later unit) is:

- Keep the folder layout, the `## Acceptance Criteria` block with its `AC:BEGIN`/`AC:END` markers, and the `id`, `title`, `priority` and `labels` fields. A Backlog.md viewer can then still open the files.
- Use our own status vocabulary `draft | ready | blocked | done`.
- Add a scalar `owner` field. It maps to `assignee: [owner]` if tooling needs that.
- Validate with pydantic and never write derived states.
- Treat Backlog.md as optional tooling. We do not depend on its CLI to write files.

Risk: if Backlog.md rewrites a file, it may reset or reject our status values. This is untested, so run it against a sample file before recommending the viewer.

## Part 2: hook-to-SQLite recorder

`scripts/hook_record.py --db PATH` reads one Claude Code hook JSON payload from stdin and inserts one row into `hook_events`.

- It validates that the payload is a JSON object and that `session_id` and `hook_event_name` are strings, and that `tool_name` is a string when present. This happens before SQLite is touched. On any failure it exits with code 2 and creates no DB file.
- It stores an allowlist only: `session_id`, `hook_event_name`, `tool_name` (nullable) and a UTC ISO `timestamp`. It never stores `cwd`, paths, prompts or tool input. Extra fields are ignored.
- The DB file is created with mode 0600 (`os.open` with `O_CREAT` and mode `0o600`, before SQLite opens it).
- Tests are in `tests/test_hook_record.py` and cover a valid payload, invalid JSON, wrong field types (no DB file created), unknown extra fields and the 0600 mode. Coverage of the script is 100%. Note that `pyproject.toml` only measures `etat_major`, so this was checked with `--cov=scripts`.
- To run the tests, put `src` on the path: `PYTHONPATH=src pytest`.

### Out of scope here (belongs to unit u4)

This spike deliberately does **not** include a roll-up or "what needs me" query, and it does not model alert resolution. Both belong to unit u4. The spec's spike criterion that one roll-up query answers "what needs me" is therefore **not** verified by this unit.

The schema is minimal. It does not yet borrow from agents-observe, and a session-level key and an index are left for u4.
