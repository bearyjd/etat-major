# Alto read-only Planning and Fleet runbook

Use this runbook for the first [Alto delivery PR](ALTO-MVP-DELIVERY.md).
Before staging or switching services on Alto, record the approved revision,
services, tabs, window and rollback
scope. The saved tabs, session URLs and `CODEMAN_ORIGIN` in this runbook belong
to Codeman, the legacy session host, and apply only to it. Keep the run record
private. It can contain service identities, paths and tab destinations, while
credentials and refresh tokens stay out of it.

## Pin the candidate and record the baseline

Take the wheel from a trusted build of the exact merged commit. Record the
full commit, wheel SHA-256, dependency lock digest, Python version and CI
result. Verify the release provenance and digest against that build record.
Record checksums of the original inputs for the staging comparison. Capture
the prior verified release and its service configuration, active
services, loopback listeners, saved Codeman tab destinations, and one known
task and report per pilot. Confirm the prior release and configuration are
available for rollback before changing any service or tab.

## Stage an offline installation

Run the blocks in a fresh, dedicated Bash session. Keep staging as its only
background job. Set path variables to private absolute paths. Use a Python 3.12 interpreter, a fresh staging parent that you control,
outside all source inputs, and a distinct unused loopback port. Supply a wheel-only dependency directory
and a hash-pinned dependency lock that includes the web extra's dependencies.
Use package pins from that wheel directory, with no URLs or extra sources.
Set `PILOT_TASK_KEY` to an existing matched task. The Meute recording is
required. Add `REVIEW_RECORD` and `HANDOFF_RECORD` when approved recordings
exist. Set `CODEMAN_ORIGIN` only to check session URLs for a handoff. Keep
these inputs and the wheel directory stable while staging. Use canonical
paths without symlink components or trailing slashes.

```bash
set -euo pipefail
umask 077
unset PYTHONPATH PYTHONHOME
: "${CANDIDATE_COMMIT:?}" "${CANDIDATE_WHEEL:?}" "${WHEEL_SHA256:?}" "${PYTHON312:?}"
: "${WHEELHOUSE:?}" "${DEPENDENCY_LOCK:?}" "${LOCK_SHA256:?}" "${STAGING_PARENT:?}"
: "${PILOT_WORKSPACE:?}" "${PROJECT:?}" "${STAGE_PORT:?}" "${PILOT_TASK_KEY:?}"
: "${MEUTE_RECORD:?}"
[[ "$CANDIDATE_WHEEL" == *.whl && "$STAGE_PORT" =~ ^[1-9][0-9]{3,4}$ ]]
(( STAGE_PORT <= 65535 ))
listeners=$(ss -H -ltn "sport = :$STAGE_PORT")
[[ -z "$listeners" ]]
run_dir=$(mktemp -d -- "$STAGING_PARENT/etat-alto.XXXXXX")
regular_input() {
  [[ "$1" = /* && -f "$1" && ! -L "$1" && "$(realpath -e -- "$1")" == "$1" ]]
}
regular_input "$CANDIDATE_WHEEL"
regular_input "$DEPENDENCY_LOCK"
wheel="$run_dir/${CANDIDATE_WHEEL##*/}"
lock="$run_dir/dependencies.lock"
cp -P -- "$CANDIDATE_WHEEL" "$wheel"
cp -P -- "$DEPENDENCY_LOCK" "$lock"
[[ -f "$wheel" && ! -L "$wheel" && -f "$lock" && ! -L "$lock" ]]
[[ "$(sha256sum < "$wheel")" == "$WHEEL_SHA256  -" ]]
[[ "$(sha256sum < "$lock")" == "$LOCK_SHA256  -" ]]
printf '%s\n' "$CANDIDATE_COMMIT" "$WHEEL_SHA256" "$LOCK_SHA256" > "$run_dir/release.txt"
"$PYTHON312" --version >> "$run_dir/release.txt"
"$PYTHON312" -m venv "$run_dir/venv"
python="$run_dir/venv/bin/python"
PIP_CONFIG_FILE=/dev/null "$python" -m pip --isolated install --no-index --find-links "$WHEELHOUSE" \
  --only-binary=:all: --require-hashes -r "$lock"
PIP_CONFIG_FILE=/dev/null "$python" -m pip --isolated install --no-index --no-deps "$wheel"
"$python" -m pip check
cli="$run_dir/venv/bin/etat-major"
"$cli" serve --help
safe_tree() {
  [[ "$1" = /* && -d "$1" && ! -L "$1" && "$(realpath -e -- "$1")" == "$1" ]] || return 1
  find -P "$1" ! -type d ! -type f -print0 > "$run_dir/unsafe.entries"
  [[ ! -s "$run_dir/unsafe.entries" ]]
}
tree_manifest() (
  cd -- "$1"
  find -P . -type d -print0 | LC_ALL=C sort -z
  find -P . -type f -print0 | LC_ALL=C sort -z | xargs -0 -r sha256sum -z --
)
safe_tree "$PILOT_WORKSPACE"
[[ "$run_dir" != "$PILOT_WORKSPACE/"* ]]
tree_manifest "$PILOT_WORKSPACE" > "$run_dir/source.before"
cp -R -P -- "$PILOT_WORKSPACE" "$run_dir/workspace"
safe_tree "$run_dir/workspace"
tree_manifest "$run_dir/workspace" > "$run_dir/staged.before"
cmp -s -- "$run_dir/source.before" "$run_dir/staged.before"

original_records=()
staged_records=()
stage_record() {
  regular_input "$1"
  cp -P -- "$1" "$2"
  regular_input "$2"
  cmp -s -- "$1" "$2"
  original_records+=("$1")
  staged_records+=("$2")
}
record_manifest() {
  local record
  for record in "$@"; do sha256sum -z < "$record"; done
}
stage_record "$MEUTE_RECORD" "$run_dir/meute.json"
serve_args=(--workspace "$run_dir/workspace" --project "$PROJECT" --port "$STAGE_PORT"
  --meute "$run_dir/meute.json")
if [[ -n "${REVIEW_RECORD:-}" ]]; then
  stage_record "$REVIEW_RECORD" "$run_dir/review.yaml"
  serve_args+=(--manual-review "$run_dir/review.yaml")
fi
if [[ -n "${HANDOFF_RECORD:-}" ]]; then
  stage_record "$HANDOFF_RECORD" "$run_dir/handoff.yaml"
  serve_args+=(--execution-links "$run_dir/handoff.yaml")
  [[ -z "${CODEMAN_ORIGIN:-}" ]] || serve_args+=(--codeman-origin "$CODEMAN_ORIGIN")
fi
record_manifest "${original_records[@]}" > "$run_dir/records.before"
cp -P -- "$run_dir/meute.json" "$run_dir/meute.baseline.json"
"$cli" serve "${serve_args[@]}" \
  > "$run_dir/staging.log" 2>&1 &
stage_pid=$!
trap 'kill %1 2>/dev/null || true; wait %1 2>/dev/null || true' EXIT
```

The Meute loader accepts JSON as well as YAML. Use JSON for the staged
update below. If the pilot needs additional file inputs, use `stage_record`
and add the corresponding flags before taking the manifests and starting
the server. See [Planning setup](PLANNING.md).

## Verify staging and its read-only boundaries

```bash
base="http://127.0.0.1:$STAGE_PORT"
request() { curl -q --noproxy '*' --max-time 5 --silent --show-error "$@"; }
status() { request --output /dev/null --write-out '%{http_code}' "$@"; }
owned_listener() {
  local listeners
  kill -0 "$stage_pid" 2>/dev/null || return 1
  listeners=$(ss -H -ltnp "sport = :$STAGE_PORT") || return 1
  awk -v address="127.0.0.1:$STAGE_PORT" -v owner="pid=$stage_pid," \
    '$4 == address && index($0, owner) { owned++ } END { exit !(NR == 1 && owned == 1) }' \
    <<< "$listeners"
}
ready=0
for ((attempt = 0; attempt < 20; attempt++)); do
  kill -0 "$stage_pid" 2>/dev/null || break
  if owned_listener && [[ "$(status --max-time 1 "$base/planning")" == 200 ]] && owned_listener; then
    ready=1
    break
  fi
  sleep 0.25
done
if (( ! ready )); then
  printf '%s\n' 'Staging failed readiness or listener ownership. Inspect the private staging log.' >&2
  exit 1
fi
for path in /planning /fleet /project.json; do
  [[ "$(status "$base$path")" == 200 ]]
done
for path in /refresh /fleet-refresh; do
  [[ "$(status "$base$path")" == 403 ]]
  [[ "$(status "$base$path?token=invalid")" == 403 ]]
  [[ "$(status --request POST "$base$path")" == 405 ]]
done
[[ "$(status --request PUT "$base/project.json")" == 405 ]]
[[ "$(status -H 'Host: outside.invalid' "$base/planning")" == 400 ]]
```

- Capture `/project.json` privately. Find `PILOT_TASK_KEY` and an
  unrelated task. Verify that only the matched task carries the recorded
  evidence, and that a report alone cannot establish acceptance. Check
  selected-project diagnostics and redacted shared counts. Verify that
  responses and logs omit private input paths, credentials and remote URLs
  from record content. The trusted configured Codeman URL is expected.
- Open the Planning and Fleet tabs at desktop and phone widths. Keep each
  frame opaque. Check keyboard navigation and no page-wide horizontal
  scrolling. Follow the Fleet report link to the exact Planning task. If a
  handoff is configured, check its copyable reference. With a handoff and an
  origin, check the copyable session URL and exact return fragment. Check
  saved tab identity when service ports differ. A locally simulated proxy
  and sandbox are rehearsal evidence.
- Make a valid change to the matched report's outcome in the staged JSON
  file. Reload through **Update Planning**, then check both views and JSON.
  Make a second valid change and repeat through **Update Fleet**. Save the
  last good status time privately and capture its JSON with the command
  below. Corrupt the staged recording and click Update again. Confirm the
  status reads **Update unavailable. Showing the previous snapshot.** and
  compare its displayed load time to the last good update. Confirm the JSON
  matches the saved copy. Use the browser controls so the nonce stays out
  of shell history and shared logs. For each deliberate edit, compare the
  recording's checksum before and after the update.

```bash
# After each deliberate edit, before and after clicking Update:
sha256sum -z < "$run_dir/meute.json" > "$run_dir/meute.edited"
# Click Update in the browser.
cmp -s "$run_dir/meute.edited" <(sha256sum -z < "$run_dir/meute.json")

# After the last good update, and again after the deliberately failed update:
request --fail "$base/project.json" > "$run_dir/last-good.json"
# Corrupt only the staged recording and click Update in the browser.
cmp -s "$run_dir/last-good.json" <(request --fail "$base/project.json")
```

Stop staging and restore the deliberately edited copy before checking the
manifests. Each tree manifest records sorted NUL-delimited directory names
and file digests with relative paths. Keep it and the descriptor digests private.

```bash
kill %1
wait %1 || true
regular_input "$run_dir/meute.json"
cp -P -- "$run_dir/meute.baseline.json" "$run_dir/meute.json"
safe_tree "$PILOT_WORKSPACE"
safe_tree "$run_dir/workspace"
tree_manifest "$PILOT_WORKSPACE" > "$run_dir/source.after"
tree_manifest "$run_dir/workspace" > "$run_dir/staged.after"
cmp -s -- "$run_dir/source.before" "$run_dir/source.after"
cmp -s -- "$run_dir/staged.before" "$run_dir/staged.after"
for record in "${original_records[@]}" "${staged_records[@]}"; do regular_input "$record"; done
record_manifest "${original_records[@]}" > "$run_dir/records.source.after"
record_manifest "${staged_records[@]}" > "$run_dir/records.staged.after"
cmp -s -- "$run_dir/records.before" "$run_dir/records.source.after"
cmp -s -- "$run_dir/records.before" "$run_dir/records.staged.after"
```

A mismatch fails the staging gate. Record the outcome privately. Once the
run record is complete, remove the stopped staging release and its copied
inputs, logs and snapshots under the approved retention policy.

## Switch, verify and roll back

Use the authorized service procedure captured in the private run record.
Switch one pilot at a time. Keep the current loopback port and saved tab
destinations. Check the running revision, service health, listener, route
statuses and actual sandboxed Codeman tabs on Alto. Repeat the applicable
read-only evidence, link, refresh and browser checks using unchanged live
inputs. Record the revision, artifact digest, service and tab identities,
viewports, outcomes and gaps privately.

Stop on an unhealthy service, changed routing, an authorization error or a
failed smoke check. Restore the previous release and captured service
configuration, then confirm its health and original Planning and Fleet views.
Leave subsequent pilots on the prior release until recovery is verified.
Keep investigation and any expanded rollout within separately authorized scope.
