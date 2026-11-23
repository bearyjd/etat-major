# Comparing CLI results on recorded repository data

Run the smoke from a trusted État-major checkout with its development dependencies installed. The checked-in baseline covers the trimmed real Floorplan and Kotlin Trail exports and Gradle scripts. The counts describe those extracts.

```sh
PYTHONPATH=src python scripts/real_data_smoke.py docs/examples/real-data-smoke.json \
  --partial --root tests/fixtures/gradle-real \
  --graph tests/fixtures/floorplan/graph-real.json \
  --trail tests/fixtures/trail/wiring-kotlin.json
```

Each line reports a CLI operation as `PASS`, `FAIL`, or `SKIP`. The script returns 0 when every selected result matches, 1 for mismatches and 2 for invalid configuration. The default requires an expectation for every operation. Use `--partial` to select a subset. Keep private baselines next to their inputs, and record the repository commit and the source of each expected value. Update expectations only after reviewing a difference.

## Running against a full repository

Use the recorded artifacts, intent workspace, Git repository, research answer and component-owned path from the same evaluation. The workspace should contain its component model under `components/PROJECT.yaml`. Use a regular checkout for Git evidence. Pin `--as-of YYYY-MM-DD` when comparing deadline-sensitive progress data. The optional `--meute FILE` adds a recorded Meute snapshot.

```sh
PYTHONPATH=src python scripts/real_data_smoke.py "$BASELINE" \
  --root "$GRADLE_ROOT" --repo "$GIT_CHECKOUT" --workspace "$WORKSPACE" \
  --graph "$GRAPH" --trail "$WIRING" --prs "$PRS" --releases "$RELEASES" \
  --project "$PROJECT" --feature "$FEATURE_REF" --path "$OWNED_PATH" \
  --answer "$RESEARCH_ANSWER" --as-of "$AS_OF" \
  --source "$PINNED_FLOORPLAN_SOURCE" --copy "$DISPOSABLE_COPY"
```

Baseline keys are the operation names printed by the script. Each contains a mandatory integer `status` (0 or 1) and at least one result field. The serve operation requires a field below `data.project`. Use a dot to descend into an object, a numeric index to select a list element, and `#` to count elements. Comparisons use the exact JSON type and value. For example, `"data.summary.unused_candidate": 4` checks a Gradle drift tier. CLI JSON commands expose their original envelopes. The progress check also exposes `revision` from a bounded read of the selected Git checkout’s HEAD. The full NetLens baseline pins that revision. Generate both index artifacts from the same revision. The other commands expose these observations:

| Operation | Fields to pin |
| --- | --- |
| research brief | `data.written` |
| research import | `data.status`, `data.provenance`, `data.findings.#` |
| serve | `data.planning`, `data.fleet` (HTTP statuses), fields below `data.project` from GET /project.json |
| floorplan scan, build, refresh | `data.lines.0` for the recorded artifact, `data.lines.1` for refresh retention |

Research and component seed outputs go into a fresh temporary directory. The serve check exercises the CLI startup and read-only GET routes in process using the web and development extras. Add `--understand` when verifying a build with that route. It requires a successful GET and exposes `data.understand` for pinning.

The three Floorplan operations run in order through the existing pinned wrapper. Supply a disposable copy prepared for deterministic build and refresh, including its architecture input. The wrapper modifies that copy. Before running any operation, the script checks that the resolved copy path is separate from each supplied input, including the baseline file, workspace and source checkout. For a read-only run, omit those three expectations and both wrapper paths and use `--partial`. See the [Floorplan runner instructions](FLOORPLAN-RUNNER.md).

## NetLens snapshot

The [full NetLens baseline](examples/netlens-real-data-smoke.json) covers all 17 CLI leaves on revision `5188ca6725007bd663ce0eaa5ad2de9e460d26a0`. For reproduction:

- Generate Trail wiring from a disposable copy of that revision. Supply the same recorded wiring to the index, Gradle and seed operations.
- For Floorplan, use the pinned deterministic runner with this architecture input in `floorplan/architecture.json`. Generate the read-only graph first, then prepare a separate disposable copy containing the same architecture input for the three wrapper checks.

  ```json
  {"$schema":"floorplan/architecture@1","project":{"name":"NetLens"},"nodes":[{"id":"app","label":"Android application","kind":"ui","paths":["app"]}]}
  ```

- Copy `tests/fixtures/demo-workspace` into a temporary workspace. Seed `components/netlens.yaml` there with `components seed`, the NetLens root and its Trail wiring. This model consists of unreviewed proposals. Use `netlens`, `feature:netlens/0031` and `core/network/build.gradle.kts` for the project, feature and map inputs.
- Use the two recorded JSON files in `tests/fixtures/progress/`, the date `2026-11-23` and a temporary copy of `tests/fixtures/research/sample.md` with the `SOURCE_URL` placeholder replaced by `https://example.org/topic/1`. The intent, answer and GitHub records in this exercise are demonstration inputs. The Git history, scanned files, Gradle declarations, Trail symbols and Floorplan scan come from the named revision.
