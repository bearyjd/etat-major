# ProgressEvidence v1

Derive a report from an intent workspace, local Git history and recorded GitHub JSON.

```sh
etat-major progress --workspace workspace --repo checkout --prs prs.json --releases releases.json
etat-major progress --workspace workspace --repo checkout --prs prs.json --releases releases.json --format json
```

## Recorded inputs

A future live adapter can capture the inputs with these GitHub CLI commands in the target repository. The report command reads the two local files offline. Supply `[]` for an empty recording.

```sh
gh pr list --state all --limit 1000 --json number,title,body,state,isDraft,mergedAt,headRefName,reviewDecision,statusCheckRollup,mergeCommit > prs.json
gh release list --limit 1000 --json tagName,publishedAt > releases.json
```

Each JSON file is capped at 4 MiB. The Git reader uses a local checkout with a regular `.git` directory. It rejects indirect Git metadata such as linked Git directories, metadata symlinks and Git config includes. Only local commits and tags available at report time can supply Git proof. A missing tag or merge object leaves the corresponding release unverified.

Optional `--graph` and `--trail` accept recorded Floorplan and Trail indexes. Use snapshots from the revision being reported. Without a Floorplan graph, `fp:f` links are resolved against regular tracked files in Git `HEAD`. Without the corresponding index, component and symbol references stay `unverified`.

## Linking and proofs

- Commit trailers take precedence over a task branch name, which takes precedence over a standalone `Task: <project>/<id>` line in a PR body. Several valid trailers can link one commit to several tasks. Branch names with multiple possible project/id splits resolve when exactly one split matches a workspace task. A PR's merge SHA or explicitly recorded head SHA can supply its trailer link.
- The Git history includes commits reachable from local refs and `HEAD`. Branch-derived commits are scoped to history ahead of the observed default branch. The default tip comes from `origin/HEAD` when available, then an unambiguous local `main` or `master`, then a sole non-task local branch. Without a default signal, only the task branch tip contributes branch-derived commit evidence. A linked PR can associate a locally observed head or merge commit that lacks its own trailer or branch link.
- Each task rung is a sorted array of proof references or the string `unverified`. References use `commit:<sha>`, `pr:<number>`, `pr:<number>/check:<one-based index>`, `tag:<name>` and `task:<project>/<id>`. The report omits raw PR titles and bodies, check URLs, and repository remotes. Declared task evidence cannot establish a rung by itself.
- A successful completed CheckRun or successful StatusContext proves the `tested` rung. The standard rollup is scoped to the PR head. A locally enriched recording may add `headRefOid` on a PR and `commitOid` on a check. A check proves testing on the merge commit only when its explicit SHA, or its recorded PR head SHA for a head rollup, equals `mergeCommit.oid`. A check explicitly scoped to an unrelated commit contributes no proof.
- A merged PR or linked commit on the default branch proves `merged`. A published recorded release proves `shipped` when its local tag contains the linked PR's merge commit. Both annotated and lightweight tags work. An approved PR proves `reviewed`.
- The optional Python argument `artifacts` to `load_progress` accepts `GeneratedArtifact` descriptors with a task key and workspace-relative artifact reference. They supply `artifact:<ref>` proofs. The CLI requires only the recorded GitHub files and local Git history.
- Done requires task acceptance. Blocked follows stored status or an unmet dependency. Review takes precedence over In Progress when work is merged without acceptance or has an open non-draft PR. An open draft PR or task branch can put a task In Progress.

## Feature and report states

Implementing requires a linked task in the In Progress column. Verified requires feature `accepted_by` and `accepted_on`, a nonempty set of resolved task links, and a passing merge-commit check for each linked merged PR, with at least one such PR per task. Released also requires release containment for those merge commits. Feature acceptance remains explicit in the feature file.

The report includes disconnected commits and PRs, overdue milestones, stale architecture links and unimplemented requirements. A dated milestone is overdue after its target date in UTC. A milestone is complete when it has linked work and all assigned tasks are Done and all linked features are Verified or Released. Absent `new` architecture links count as gaps, and absent `modifies` or `uses` links count as stale when the relevant snapshot is available.

The CLI exits 0 for a produced report, including findings, 1 for workspace validation issues, and 2 for invalid arguments or unreadable or invalid input files. JSON output includes top-level `version`, `tasks`, `features`, `disconnected_commits`, `disconnected_prs`, `stale_milestones`, `stale_links` and `unimplemented_requirements`.
