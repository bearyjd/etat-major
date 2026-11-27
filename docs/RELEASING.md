# Releasing

A release is a `vX.Y.Z` tag on a commit of `main`, plus a GitHub release made from that tag.
The maintainer creates and pushes the tag. No script, workflow or agent creates one.
The [versioning policy](../CHANGELOG.md#versioning-policy) says which number to raise.

## Before the first tag

Do this once, before any `v*` tag is pushed. The `Release` workflow and its check script are read
from the tagged commit, so whoever can push a tag can tag a side commit with an edited workflow
that skips every check and still has write access to releases. Only a repository setting stops
that.

In the repository's **Settings**, under **Rulesets**, create a **New tag ruleset**:

- enforcement status **Active** (a new ruleset starts disabled);
- target tags matching `v*`;
- the rules **Restrict creations**, **Restrict updates** and **Restrict deletions**;
- a bypass list holding only the people who release. Everyone else is then unable to create,
  move or delete a `v*` tag.

Optionally add a branch ruleset for `main` too: require a pull request and the CI status check,
and block force pushes, so that "the commit is on `main`" also means it was reviewed.

## Steps

1. Open a pull request that:
   - sets `__version__` in `src/etat_major/__init__.py`, the only place the version is written
     (`pyproject.toml` reads it from there);
   - makes the top release section of [CHANGELOG.md](../CHANGELOG.md) read
     `## [X.Y.Z] - YYYY-MM-DD`, with the release date in place of `unreleased`, and lists what
     changed. The text of that section becomes the release notes.
2. Check the result in that branch. This reads files and prints one line:

   ```sh
   RELEASE_TAG=vX.Y.Z python3 scripts/release_check.py
   ```

3. Merge the pull request once CI is green.
4. Tag the merge commit and push that one tag:

   ```sh
   git fetch origin
   git tag -a vX.Y.Z -m "vX.Y.Z" <merge commit>
   git push origin vX.Y.Z
   ```

5. Watch the `Release` workflow and read the release it creates.

## What the workflow checks

[`release.yml`](../.github/workflows/release.yml) runs only when a `v*` tag is pushed.

- `verify`, with read-only access: the tag is exactly `v` followed by the version in every
  source; the top release section of the changelog is that version, dated and not empty; the
  tagged commit is an ancestor of `origin/main`; and the CI gates pass.
- `release`, the only job that may write: it builds the notes from the verified commit, stops if
  the tag no longer points to that commit, stops if a release for the tag already exists, and
  creates the GitHub release. It does not create a missing tag.

Runs for the same tag do not overlap. A newer run never cancels the one that is running, but a
run that is still waiting can be cancelled and replaced by a newer one for the same tag; re-run
it from the Actions page if it is still wanted.

The actions are pinned to commit hashes; change a pin only after looking up the commit of the new
version tag in the action's repository, and update `tests/test_release_workflow.py` with it.

## If `verify` fails

Nothing is published. Fix the cause through a pull request, then delete the tag locally
(`git tag -d vX.Y.Z`) and on GitHub (`git push origin :refs/tags/vX.Y.Z`, which needs bypass
permission under the tag ruleset) and tag the new merge commit.

## If the `release` job fails

1. Read the failed step, then look for a release, drafts included: `gh release view vX.Y.Z`,
   or the repository's Releases page.
2. If the step says the tag no longer points to the verified commit, someone moved or deleted
   it. Find out who and why before doing anything else.
3. No release exists and the cause was temporary (network or GitHub API): choose **Re-run failed
   jobs** on the run. It uses the same commit and checks the tag again.
4. A draft was left behind: delete it (`gh release delete vX.Y.Z`, without `--cleanup-tag`) and
   re-run the failed jobs.
5. No release exists and the cause is in the workflow or the files: re-running repeats the same
   commit, so fix it through a pull request, then delete the tag and tag the new merge commit as
   above.
6. A release was published: the workflow will not overwrite it. Correct its notes by hand if
   that is all that is wrong; otherwise release a new patch version.

Never move or reuse a tag that has a published release.

## Limits

These checks catch mistakes. They are not a defense against someone allowed to push `v*` tags;
the tag ruleset above decides who that is. The tag can also move in the moment between the last
check and the creation of the release, which the ruleset's update restriction covers.
