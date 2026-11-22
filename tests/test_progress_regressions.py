import pytest

from etat_major.cli import main
from test_progress import TASK, History


@pytest.fixture
def history(tmp_path):
    return History(tmp_path)


@pytest.mark.parametrize("state", ["FAILURE", "PENDING"])
@pytest.mark.parametrize("on_merge", [False, True])
def test_mixed_checks_do_not_prove_tested_or_verified(history, capsys, state, on_merge):
    head = history.commit("Latency work")
    merge = history.commit("Merge latency")
    oid = merge if on_merge else head
    history.task("accepted_by: reviewer\naccepted_on: 2026-01-03", status="done")
    history.feature("tasks: [task:netlens/0042]\naccepted_by: reviewer\naccepted_on: 2026-01-03")
    history.set_prs(
        history.pr(
            headRefOid=head,
            mergeCommit={"oid": merge},
            statusCheckRollup=[
                {"__typename": "StatusContext", "state": "SUCCESS", "commitOid": oid},
                {"__typename": "StatusContext", "state": state, "commitOid": oid},
            ],
        )
    )
    report = history.report(capsys)
    assert report["tasks"][TASK]["tested"] == "unverified"
    assert report["features"]["netlens/0031"]["state"] != "verified"


def test_feature_remains_implementing_until_linked_task_is_accepted(history, capsys):
    merge = history.commit("Merge latency")
    history.set_prs(
        history.pr(
            mergeCommit={"oid": merge},
            statusCheckRollup=[
                {"__typename": "StatusContext", "state": "SUCCESS", "commitOid": merge}
            ],
        )
    )
    history.feature("tasks: [task:netlens/0042]\naccepted_by: reviewer\naccepted_on: 2026-01-03")
    report = history.report(capsys)
    assert report["tasks"][TASK]["state"] == "review"
    assert report["features"]["netlens/0031"]["state"] == "implementing"


def test_workspace_validate_names_task_file_with_unknown_milestone(history, capsys):
    history.task("milestone: m3")
    status = main(["workspace", "validate", "--workspace", str(history.workspace)])
    assert status == 1
    assert "tasks/netlens/0042-latency.md: field 'milestone':" in capsys.readouterr().err


def test_closed_approved_pr_does_not_prove_review(history, capsys):
    history.set_prs(history.pr(state="CLOSED", mergedAt=None, mergeCommit=None))
    assert history.report(capsys)["tasks"][TASK]["reviewed"] == "unverified"


def test_release_matching_uses_one_tag_query_per_merge(history, capsys, monkeypatch):
    from etat_major import evidence_git

    merge = history.commit("Merge latency")
    tags = [f"rel-{i}" for i in range(5)]
    for tag in tags:
        history.git("tag", tag)
    history.write(
        history.releases, [dict(tagName=t, publishedAt="2026-01-03T00:00:00Z") for t in tags]
    )
    history.set_prs(history.pr(mergeCommit={"oid": merge}))
    calls = []
    git_result = evidence_git._git_result

    def record(fd, args, limit, **kwargs):
        calls.append(args)
        return git_result(fd, args, limit, **kwargs)

    monkeypatch.setattr(evidence_git, "_git_result", record)
    assert history.report(capsys)["tasks"][TASK]["shipped"] == [f"tag:{tag}" for tag in tags]
    assert sum("refs/tags/" in " ".join(args) or args[0] == "merge-base" for args in calls) == 1


def test_progress_text_lists_stale_links_and_unimplemented_requirements(history, capsys):
    history.feature(
        "architecture:\n"
        "  - {ref: 'fp:f:old.py', relation: modifies}\n"
        "  - {ref: 'fp:f:new.py', relation: new}"
    )
    assert main(history.args("text")) == 0
    out = capsys.readouterr().out
    assert "stale link  feature:netlens/0031  fp:f:old.py" in out
    assert "unimplemented requirement  feature:netlens/0031  fp:f:new.py" in out
