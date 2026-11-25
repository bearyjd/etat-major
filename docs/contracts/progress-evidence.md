# ProgressEvidence v1

Derive a report from an intent workspace, local Git history and recorded GitHub JSON.

```sh
etat-major progress --workspace workspace --repo checkout --prs prs.json --releases releases.json
etat-major progress --workspace workspace --repo checkout --prs prs.json --releases releases.json --format json
```

## Recorded inputs

Capture the inputs by hand with these GitHub CLI commands in the target repository, or with the capture script described below. The report command reads the two local files offline. Supply `[]` for an empty recording.

```sh
gh pr list --state all --limit 1000 --json number,title,body,state,isDraft,mergedAt,headRefName,reviewDecision,statusCheckRollup,mergeCommit > prs.json
gh release list --limit 1000 --json tagName,publishedAt > releases.json
```

### Capture script (implemented)

`scripts/record_github.py` runs the two commands above for the maintainer and writes `prs.json` and `releases.json`. It is not part of `src/` and the report command never calls it. Its behavior is bounded by the capture-script exception in `AGENTS.md`.

- **Arguments.** The two `gh` argument lists above, unchanged, with no `--repo`, no shell and no extra fields. One further fixed command, `gh repo view --json nameWithOwner,url`, is used only to show the resolved target. The script refuses to run if `GH_HOST` or `GH_REPO` is set, or if stdin is not an interactive terminal.
- **Target.** `gh` runs with its working directory set to a checkout the human names. Its remotes decide which host and repository `gh` queries, and they are untrusted, so the script prints the resolved host and `owner/repo` and waits for the human to confirm before writing anything. It sets `GIT_CONFIG_NOSYSTEM=1`, `GIT_CONFIG_GLOBAL=/dev/null`, `GIT_TERMINAL_PROMPT=0` and `GIT_OPTIONAL_LOCKS=0`, resolves `gh` to an absolute path first and refuses a relative or `.` entry in `PATH`. The checkout's own Git configuration is treated as the human's, which is why the confirmation step exists. A fake `gh` tests all of this.
- **Environment.** Only `PATH`, `HOME`, `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `XDG_STATE_HOME`, `XDG_RUNTIME_DIR`, `DBUS_SESSION_BUS_ADDRESS`, `GH_CONFIG_DIR`, `LANG` and `LC_ALL` reach `gh`; the runtime-directory and session-bus variables only let `gh` reach a system keyring. Every other variable is dropped, including `GH_TOKEN`, `GITHUB_TOKEN`, `GH_ENTERPRISE_TOKEN` and `GITHUB_ENTERPRISE_TOKEN`. Authentication comes from `gh`'s own login (config directory or keyring). The script never opens, copies or logs that credential, although `gh` itself may read a plaintext config file under `HOME`. The script also sets `GH_PROMPT_DISABLED=1`, `GH_NO_UPDATE_NOTIFIER=1`, `NO_COLOR=1` and `GH_PAGER=cat`, closes stdin and takes stdout only, treating stderr as untrusted. Token-only environments, and users behind a proxy that `gh` needs from the environment, are unsupported and fail with `gh`'s own error.
- **Truncation.** `--limit 1000` is a hard bound. A result with 1000 or more entries prints a truncation warning to stderr without failing the run, because older pull requests or releases may be missing.
- **Enrichment deferred.** The script does not add `headRefOid` or `commitOid`. The recorded standard rollup stays scoped to the PR head, so the `tested` rung remains conservative by design.
- **Output.** Output is capped at 4 MiB per file. If it exceeds the cap the script fails and records nothing; it never truncates JSON. Before publishing, the script validates the output through `load_prs` or `load_releases` themselves, from a private temporary file (mode 0600, deleted on every exit path) inside the human-named directory, so anything it publishes the report command can load. The final file is created only after validation passes. The script may import from `src/`; `src/` never imports the script. Invalid output fails and records nothing. The bytes are never executed or echoed, and are written atomically into a directory the human names without following symlinks. On any failure no file is created. Errors name the file and field and print no traceback, remote, absolute path or token.
- **Testing.** Tests use a fake `gh`. The maintainer runs the real command once on a real repository before the script is considered verified.

Each JSON file is capped at 4 MiB. The Git reader uses a local checkout with a regular `.git` directory. It rejects indirect Git metadata such as linked Git directories, metadata symlinks and Git config includes. Only local commits and tags available at report time can supply Git proof. A missing tag or merge object leaves the corresponding release unverified.

Optional `--graph` and `--trail` accept recorded Floorplan and Trail indexes. Use snapshots from the revision being reported. Without a Floorplan graph, `fp:f` links are resolved against regular tracked files in Git `HEAD`. Without the corresponding index, component and symbol references stay `unverified`.

Optional `--meute FILE` reads one [recorded Meute snapshot](meute-recording.md)
offline. A configured input that is unreadable or invalid gives exit code 2.

## Linking and proofs

- Commit trailers take precedence over a task branch name, which takes precedence over a standalone `Task: <project>/<id>` line in a PR body. Several valid trailers can link one commit to several tasks. Branch names with multiple possible project/id splits resolve when exactly one split matches a workspace task. A PR's merge SHA or explicitly recorded head SHA can supply its trailer link.
- The Git history includes commits reachable from local refs and `HEAD`. Branch-derived commits are scoped to history ahead of the observed default branch. The default tip comes from `origin/HEAD` when available, then an unambiguous local `main` or `master`, then a sole non-task local branch. Without a default signal, only the task branch tip contributes branch-derived commit evidence. A linked PR can associate a locally observed head or merge commit that lacks its own trailer or branch link.
- Each task rung is a sorted array of proof references or the string `unverified`. References use `commit:<sha>`, `pr:<number>`, `pr:<number>/check:<one-based index>`, `tag:<name>` and `task:<project>/<id>`. The report omits raw PR titles and bodies, check URLs, and repository remotes. Declared task evidence cannot establish a rung by itself.
- A successful completed CheckRun or successful StatusContext proves the `tested` rung. The standard rollup is scoped to the PR head. A locally enriched recording may add `headRefOid` on a PR and `commitOid` on a check. A check proves testing on the merge commit only when its explicit SHA, or its recorded PR head SHA for a head rollup, equals `mergeCommit.oid`. A check explicitly scoped to an unrelated commit contributes no proof.
- A merged PR or linked commit on the default branch proves `merged`. A published recorded release proves `shipped` when its local tag contains the linked PR's merge commit. Both annotated and lightweight tags work. An approved PR proves `reviewed`.
- A Meute report with an explicit key matching an existing task in the snapshot's
  project supplies `artifact:<ref>` on the `generated` rung. The Python
  `artifacts` argument to `load_progress` also accepts `GeneratedArtifact`
  descriptors as before.
- Done requires task acceptance. Blocked follows stored status or an unmet dependency. Review takes precedence over In Progress when work is merged without acceptance or has an open non-draft PR. An open draft PR or task branch can put a task In Progress.

## Feature and report states

Implementing requires a linked task in the In Progress column. Verified requires feature `accepted_by` and `accepted_on`, a nonempty set of resolved task links, and a passing merge-commit check for each linked merged PR, with at least one such PR per task. Released also requires release containment for those merge commits. Feature acceptance remains explicit in the feature file.

The report includes disconnected commits and PRs, overdue milestones, stale architecture links and unimplemented requirements. A dated milestone is overdue after its target date in UTC. A milestone is complete when it has linked work and all assigned tasks are Done and all linked features are Verified or Released. Absent `new` architecture links count as gaps, and absent `modifies` or `uses` links count as stale when the relevant snapshot is available.

The CLI exits 0 for a produced report, including findings, 1 for workspace validation issues, and 2 for invalid arguments or unreadable or invalid input files. The [CLI JSON envelope](cli-json.md) carries the report under `data`, which includes `version`, `tasks`, `features`, `disconnected_commits`, `disconnected_prs`, `stale_milestones`, `stale_links` and `unimplemented_requirements`.

For deterministic overdue checks in JSON, pass `--as-of YYYY-MM-DD`. The report records that date in `data.as_of`.

With a valid Meute snapshot, `data.meute` includes its `version`, `project`,
`exported_at` and `reports`. Each row includes the original `ref`,
`recorded_at`, `outcome`, the explicit `task` key or `null`, and a boolean
`linked` indicating whether it contributes generated proof. Both timestamps
describe the recording. The snapshot supplies all the displayed Meute metadata.
