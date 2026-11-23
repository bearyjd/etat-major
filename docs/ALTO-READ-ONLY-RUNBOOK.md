# Alto read-only Planning and Fleet runbook

Use this runbook for the first [Alto delivery PR](ALTO-MVP-DELIVERY.md).
A merge does not authorize an Alto rollout. Before staging or switching services
on Alto, record the approved revision, services, tabs, window and rollback
scope. Keep the run record private. It can contain service identities, paths
and tab destinations, while credentials and refresh tokens stay out of it.

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
and a distinct unused loopback port. Supply a wheel-only dependency directory
and a hash-pinned dependency lock that includes the web extra's dependencies.
Use package pins from that wheel directory, with no URLs or extra sources.
Set `PILOT_TASK_KEY` to an existing matched task. The Meute recording is
required. Add `REVIEW_RECORD` and `HANDOFF_RECORD` when approved recordings
exist. Set `CODEMAN_ORIGIN` only to check session URLs for a handoff.

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
[[ "$(sha256sum < "$CANDIDATE_WHEEL")" == "$WHEEL_SHA256  -" ]]
[[ "$(sha256sum < "$DEPENDENCY_LOCK")" == "$LOCK_SHA256  -" ]]
printf '%s\n' "$CANDIDATE_COMMIT" "$WHEEL_SHA256" "$LOCK_SHA256" > "$run_dir/release.txt"
"$PYTHON312" --version >> "$run_dir/release.txt"
"$PYTHON312" -m venv "$run_dir/venv"
python="$run_dir/venv/bin/python"
PIP_CONFIG_FILE=/dev/null "$python" -m pip --isolated install --no-index --find-links "$WHEELHOUSE" \
  --only-binary=:all: --require-hashes -r "$DEPENDENCY_LOCK"
PIP_CONFIG_FILE=/dev/null "$python" -m pip --isolated install --no-index --no-deps "$CANDIDATE_WHEEL"
"$python" -m pip check
cli="$run_dir/venv/bin/etat-major"
"$cli" serve --help
cp -a -- "$PILOT_WORKSPACE" "$run_dir/workspace"
cp -- "$MEUTE_RECORD" "$run_dir/meute.json"
serve_args=(--workspace "$run_dir/workspace" --project "$PROJECT" --port "$STAGE_PORT"
  --meute "$run_dir/meute.json")
if [[ -n "${REVIEW_RECORD:-}" ]]; then
  cp -- "$REVIEW_RECORD" "$run_dir/review.yaml"
  serve_args+=(--manual-review "$run_dir/review.yaml")
fi
if [[ -n "${HANDOFF_RECORD:-}" ]]; then
  cp -- "$HANDOFF_RECORD" "$run_dir/handoff.yaml"
  serve_args+=(--execution-links "$run_dir/handoff.yaml")
  [[ -z "${CODEMAN_ORIGIN:-}" ]] || serve_args+=(--codeman-origin "$CODEMAN_ORIGIN")
fi
"$cli" serve "${serve_args[@]}" \
  > "$run_dir/staging.log" 2>&1 &
stage_pid=$!
trap 'kill %1 2>/dev/null || true; wait %1 2>/dev/null || true' EXIT
```

Use a Meute export in JSON format for the staging update below. If other
source options are required by the matching live pilot, copy those inputs and
supply the corresponding flags listed in [Planning setup](PLANNING.md).
Keep staging on its own port. Wait until it responds, then verify the staging
PID is still running and owns that loopback listener before running checks.

## Verify staging and its read-only boundaries

```bash
base="http://127.0.0.1:$STAGE_PORT"
request() { curl -q --noproxy '*' --max-time 5 --silent --show-error "$@"; }
status() { request --output /dev/null --write-out '%{http_code}' "$@"; }
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
  handoff is configured, check the copyable reference and exact return
  fragment. With an origin, also check the copyable session URL. Check saved tab identity when service ports
  differ. A locally simulated proxy and sandbox are rehearsal evidence.
- Make a valid change to the matched report's outcome in the staged JSON
  file. Reload through **Update Planning**, then check both views and JSON.
  Make a second valid change and repeat through **Update Fleet**. Save the
  last good status time privately. Save its JSON with `request --fail "$base/project.json" >
  "$run_dir/last-good.json"`. Corrupt the staged recording, click Update
  again. Confirm the status reads **Update unavailable. Showing the previous
  snapshot.** and its displayed load time exactly matches the status time
  recorded after the last good update. Compare JSON using `cmp -s "$run_dir/last-good.json"
  <(request --fail "$base/project.json")`. Restore the staged input. Use the
  browser controls so the nonce stays out of shell history and shared logs.
  Check that the original inputs' checksums match the baseline and that
  only your deliberate edits touched the staged copies.

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
