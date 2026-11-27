# Alto MVP delivery

Deliver the three slices as separate, reviewable PRs in order. The merged
read-only Planning stack provides the deployment candidate. Give each PR a pinned baseline, an independent review,
green CI on its exact head, and a record of the checks run. Merge and live
rollout are separate decisions. Stage and deploy on Alto only within the scope
the maintainer explicitly authorizes, including the target revisions, services
and tabs. Keep machine-specific settings and credentials outside the repository.

Codeman, the legacy session host, is the operator entry point and owns sessions
and their access checks. Every Codeman statement in this plan is specific to it.
Meute owns Inbox, Run, execution and write authentication. État-major owns the
roadmap, task presentation and recorded evidence. Each service keeps its own
credentials. The handoffs carry only the task or execution link needed by the
destination.

## PR 1 — Read-only Planning and Fleet deployment

**Scope.** Use the [Alto read-only runbook](ALTO-READ-ONLY-RUNBOOK.md) for
release staging and operator verification of the merged Planning stack. Establish the service and Web Tab baseline before changing it.
Record the exact merged candidate and the prior verified Alto revision, active
services, saved tab destinations and rollback target in the operator's private
run record. The earlier local pilot is rehearsal evidence. Verify the new
candidate separately.

**Stage.** Build the candidate from its pinned revision and install it in an
isolated staging release. Start a separate loopback instance using copies of
the recorded workspace and artifacts. Use the existing NetLens and Relais
pilot checks where their inputs are available.

- Confirm Planning and Fleet render, the recorded report appears on the exact
  task, unrelated tasks omit its evidence, and the Fleet link lands on the
  task anchor. Check the Planning sources and diagnostic privacy.
- Confirm the session link and return-to-task URL are copyable text. Verify
  the opaque sandbox, fragment navigation and no page-wide horizontal
  scrolling at desktop and phone widths.
- Check both update controls. Valid nonce requests replace only the shared
  in-memory snapshot. Missing or invalid nonces are denied. Invalid input
  leaves the last good Planning, Fleet and JSON snapshots available. Confirm
  the service rejects workspace and evidence writes.

**Deploy and roll back.** With explicit rollout scope, switch one pilot service
at a time and retain the saved Web Tab destinations. Verify the service is
active and repeat the applicable read-only checks in the live Codeman browser.
Stop on an unhealthy service, changed routing or failed smoke check. Restore
the captured release and service configuration and verify the prior views
before continuing. Record the revision, browser widths and observed outcomes.

## PR 2 — Open an existing Codeman session

**Scope.** Implement the native **Open session** action at the Codeman boundary.
The opaque iframe can nominate a candidate session. Selection requires an
explicit click in the native Codeman UI. At that click, the trusted parent
rechecks that the nomination came from the active frame of the opted-in
Planning tab and applies Codeman's existing session access checks. In
multi-user mode the session's owner must exactly match the authenticated
operator, even when the operator can inspect other sessions. In authenticated single-user
mode an ownerless session is eligible. The action selects an existing session.
Session launch stays outside this PR.

**Acceptance.** Start from a recorded link on a Planning task. One click
selects the linked Codeman session and the native return action restores the
same Planning project and exact task anchor. Verify on desktop and phone
widths against the authorized Alto baseline. Cover denied requests from
unapproved tabs, missing sessions, unauthenticated operators and a different
owner. Keep copyable URLs available as the fallback.

**Rollback.** Disable the tab's opt-in or restore the prior Codeman revision.
Confirm that Planning still displays the recorded links and the native action
is disabled.

**Decision (2026-11-24).** Planning keeps its current content security policy
(`default-src 'none'`, no script) and its copyable links. Native selection is
tried first as a plain link to Codeman's existing `#session=<id>` deep link,
with no script on the Planning page. A browser test of the sandboxed Web Tab
decides whether that works: the tab's sandbox allows popups but not top
navigation, and a popup inherits the sandbox, so it may not. A hash-pinned
script and a nomination message handler in Codeman are not approved. Reopen that
option only if the link test fails and the maintainer chooses it.

**Result of the link test (2026-11-24).** A headless Chromium simulation put a
copy of the six test links in an iframe with the Web Tab sandbox flags read from
the Codeman fork (`allow-scripts allow-forms allow-popups allow-downloads
allow-modals`) and pointed them at a stand-in target. A `_blank` link and
`window.open` open a new window that inherits the sandbox: its origin is `null`
and storage throws `SecurityError`, so a real Codeman there could not hold a
login. `_top` and `_parent` navigation is blocked. A link with no target
navigates the frame itself, still sandboxed. So a plain `#session=` link cannot
select a session in the existing Codeman window, and the plain-link option is
not viable with these flags. Copyable links stay.

Two sandbox changes in Codeman would make a click work, and each widens the
sandbox for every page in every Web Tab. `allow-popups-to-escape-sandbox` opens a
working but separate window. `allow-top-navigation-by-user-activation` lets a
click navigate the whole window to Codeman, which reloads it. Neither is
approved. The alternative to evaluate is the script and nomination message
described above, which keeps the sandbox strict. Reopening it is a maintainer
decision.

This result has limits. It used Chromium only and a stand-in target, not the
real Codeman deep link, and the flags come from the fork's source, not from a
running deployment. Confirm the `sandbox` attribute of the Web Tab iframe in the
deployed Codeman before relying on it. The simulation is kept with the local
test kit and can be rerun.

## PR 3 — Authenticated Meute Fleet controls

**Scope.** Introduce a narrow allowlist of explicit operator actions through
Meute's existing Inbox and Run interfaces. Agree on the allowed action and its
effect before implementation. Keep the recorded Fleet view read-only and start
with a private authenticated top-level Meute link. Meute authenticates and
authorizes the operator, validates each action and owns the execution state.
Autonomous job configuration and scheduling stay outside this PR.

**Acceptance.** Check the intended action on an approved test item and verify
that the resulting state is visible in Meute. Verify denial for an
unauthenticated operator, unauthorized action and invalid routing. Treat iframe
writes as a separate enablement gate within this slice. Check the actual
sandboxed browser request against Meute's Host, Fetch Metadata, write Origin
and token checks. Stop on authorization or routing failure and retain the
top-level link. Credentials and tokens stay with Meute, including during the
browser checks.

**Rollback.** Disable the Fleet action surface and restore the prior
read-only view. Check that the private Meute link and recorded evidence
remain available. Record any Meute action already accepted and use Meute's
own operator controls if intervention is needed.

**Decision (2026-11-24).** The one allowlisted action is `dismiss`. It records a
single decision on one finding with a required reason and starts nothing.
`promote`, `resolve`, run start and stop, enqueue and plan start are not
allowlisted. A read-only check found that `promote` queues work that a scheduled
run later picks up, and that it has no undo. Meute's per-route allowlist and
operator authentication must be merged and deployed before État-major adds the
top-level link. The test item is a disposable finding that is named only in a
private record.

[Planning pilot](PLANNING.md) · [Current work](NEXT.md)
