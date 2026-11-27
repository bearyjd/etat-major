# Releasing

A release is a `vX.Y.Z` tag on a commit of `main`, plus a GitHub release made from that tag.
The maintainer creates and pushes the tag. No script, workflow or agent creates one.
The [versioning policy](../CHANGELOG.md#versioning-policy) says which number to raise.

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
- `release`, the only job that may write: it creates the GitHub release with the changelog
  section as notes. It stops if a release for the tag already exists, and it does not create a
  missing tag.

## If it fails

Nothing is published when `verify` fails. Fix the cause through a pull request, then delete the
tag locally (`git tag -d vX.Y.Z`) and on GitHub (`git push origin :refs/tags/vX.Y.Z`) and tag
the new merge commit. Never move or reuse a tag that has a release.

## Limits

The workflow and the script run from the tagged commit, so these checks catch mistakes. They do
not stop someone who is allowed to push tags; restrict that with a repository tag ruleset.
