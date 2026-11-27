# Delivery roadmap

The maintainer authorized the Understand and real-data smoke work and the
read-only rollout of `9baf429` to the two existing deployment-host pilots.
The runbook merged in [PR #21](https://github.com/bearyjd/etat-major/pull/21).
Isolated staging passed for both pilots. Live acceptance is pending access to
both saved tabs through the current authenticated Codeman frontend.
This plan builds on the [visualization phases](VISUALIZATION-ROADMAP.md),
[deployment-host delivery workflow](DEPLOYMENT-MVP-DELIVERY.md)
([docs at `9baf429`](https://github.com/bearyjd/etat-major/tree/9baf429/docs))
and [Understand MVP contract](https://github.com/bearyjd/etat-major/blob/9baf429/docs/UNDERSTAND-MVP.md).

The [Understand inspector](https://github.com/bearyjd/etat-major/pull/23) and
[smoke runner](https://github.com/bearyjd/etat-major/pull/24) merged after
independent review and CI. The NetLens browser proof used seeded components
and a simulated Codeman proxy. A human-reviewed component and live Codeman
verification remain open for full Understand acceptance.

Codeman, named in this plan, is the legacy session host. The saved tabs, Web Tab
behavior, session opening and upstream findings are specific to it.

## Milestones and proposed PRs

| Milestone | Proposed PR or delivery step | Depends on | Exit evidence |
| --- | --- | --- | --- |
| 1. Read-only Planning and Fleet on the deployment host | État-major #21 runbook, followed by the approved live rollout | Merged Planning stack, verified `9baf429` artifact and isolated staging | Each pilot serves the pinned release and passes health, evidence, handoff and refresh checks in its saved Codeman tab at phone and desktop sizes. Capture rollback inputs before switching a pilot. Verify NetLens before switching Relais. |
| 2. Understand MVP | État-major PR A adds the configured-project inspector and Planning component links | Reviewed component model and recorded Trail and Floorplan adapters. Excerpts also require an immutable source snapshot. | Real NetLens component → file → symbol → caller and callee, recorded confidence, bounded excerpts, pagination and deferred links. Check artifact presence and freshness independently. Verify keyboard and phone navigation in both an ordinary browser and a Codeman Web Tab. |
| 2. Understand MVP | État-major PR B adds the real-data smoke runner | Existing CLI contracts and maintainer-provided recordings. Add the Understand check after PR A. | A repeatable smoke run exercises every supported CLI command on a pinned real repository and recordings, compares expected counts and provenance where applicable, and fails on drift. Record fixture revisions and expected counts. |
| 3. Native Codeman session opening | Codeman PR adds opt-in selection of an existing session and return to the exact Planning task. Add a companion État-major PR if the agreed nomination contract requires a producer change. | Milestone 1 and review of the Codeman revision deployed on the deployment host | An explicit native click selects the existing session. Codeman checks current authentication, the active opted-in frame and exact ownership in multi-user mode. Authenticated single-user mode may select an ownerless session. Verify denials and exact return navigation on phone and desktop. |
| 4. Authenticated Fleet controls | Meute and État-major changes as needed to expose one allowlisted action through a private authenticated top-level link | Milestone 3 in the existing delivery order, verified Meute revision and maintainer approval of the action and test item | Meute validates the operator, action and destination and owns the resulting state. Record one successful action on the approved test item and verify denial for unauthenticated operators, unauthorized actions and invalid routing. |
| 5. Operational hardening and wider use | Separate État-major PRs for freshness and measured large-repo limits, then portfolio or mobile refinements based on pilot findings | Milestone 2 for Understand measurements. Milestones 1, 3 and 4 for integration refinements. | Publish data-size and latency observations from real recordings, stale and missing input behavior, and regression checks. Require verified credential isolation and account eligibility before approving a second user. |

The deployment-host rollout and Understand are independent tracks. Understand and the CLI
smoke runner can proceed alongside the deployment-host sequence. For
Understand, keep the first slice server-rendered with paginated lists and the
existing dependency set. Use the agreed NetLens recording to measure the need
for a graph before proposing a dependency. A later graph PR requires a pinned
dependency decision, bounded rendering and keyboard-accessible access to the
same evidence. The Codeman theme is post-MVP.

The Codeman session PR covers existing sessions only. Disable the opt-in to
roll back to the copyable links. The recorded Fleet view stays read-only. If
the Fleet action surface needs to be disabled, retain the recorded view and
the approved private Meute link.

## Approval and verification

| Gate | Required decision or evidence |
| --- | --- |
| Before implementation | The maintainer approves the proposed scope and owners for each slice. The Codeman owner approves the nomination contract. The Meute owner approves the exact action, its effects, and the test item. A new dependency, additional user or broader rollout needs its own approval. |
| Before merge | Record the pinned baseline, independent review and green CI on the current PR head. Run the repository's pytest coverage and Ruff gates for code changes. Include real-artifact verification where an adapter changes. The maintainer authorizes the merge. |
| Before live verification | Capture the exact release and rollback target, approved services and saved tabs in the private run record. Verify the first pilot in the actual authenticated browser before moving to the next. Roll back the changed pilot if its acceptance checks fail. |
| Before optional Fleet iframe enablement | Obtain a separate enablement decision after the actual sandboxed browser request passes Meute's Host, Fetch Metadata, write Origin and token checks. Keep the approved top-level link available. |
| Before a second user | Record passing end-to-end isolation and account eligibility for the selected deployment configuration, then obtain maintainer approval. |

## Upstream findings that affect delivery

- Codeman's Web Tab **Test** checks upstream reachability. Its sandbox and proxy
  authentication affect real browser behavior, so the deployment-host and optional Fleet
  iframe gates require a browser check in the saved tab. Record the deployed
  Codeman and Meute revisions privately and verify their behavior there.
  [Codeman Web Tabs](https://github.com/Ark0N/Codeman/blob/master/docs/web-tabs.md)
- Opaque origins serialize to `null`. In the native session PR, bind nominations
  to the active opted-in frame, validate the message shape and recheck ownership
  when the operator clicks. Codeman documents admin visibility across users and
  shared OS identity in its default setup. [HTML Standard](https://html.spec.whatwg.org/multipage/browsers.html#concept-origin-opaque) ·
  [Codeman multi-user mode](https://github.com/Ark0N/Codeman#multi-user-mode-opt-in)
- Verify the Meute top-level flow through its actual route and redirect chain.
  An optional iframe flow must preserve Meute's existing CSRF checks and treat
  the proxy capability URL as sensitive in logs and verification records.
  [W3C Fetch Metadata](https://www.w3.org/TR/fetch-metadata/#redirects) ·
  [OWASP CSRF prevention](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)
- Use keyboard operation, visible focus and reflow as explicit browser
  acceptance checks for Understand. Keep the widths specified in its existing
  acceptance contract. [WCAG 2.2](https://www.w3.org/TR/WCAG22/)
- Capture the reviewed head SHA and current CI result with each proposed merge.
  GitHub can enforce these requirements if repository rules are configured.
  [GitHub required status checks](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks)
