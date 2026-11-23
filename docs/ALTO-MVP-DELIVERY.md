# Alto MVP delivery

Deliver the three slices as separate, reviewable PRs in order. The merged
read-only Planning stack provides the deployment candidate. Give each PR a pinned baseline, an independent review,
green CI on its exact head, and a record of the checks run. Merge and live
rollout are separate decisions. Stage and deploy on Alto only within the scope
the maintainer explicitly authorizes, including the target revisions, services
and tabs. Keep machine-specific settings and credentials outside the repository.

Codeman is the operator entry point and owns sessions and their access checks.
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

[Planning pilot](PLANNING.md) · [Current work](NEXT.md)
