import json
import os
import subprocess
from pathlib import Path

import pytest

from etat_major.cli import main

FIXTURES = Path(__file__).parent / "fixtures" / "progress"
TASK = "netlens/0042"


class History:
    def __init__(self, root):
        self.workspace = root / "workspace"
        self.workspace.mkdir()
        self.repo = root / "repo"
        self.repo.mkdir()
        self.env = {
            "PATH": os.defpath,
            "HOME": str(root),
            "XDG_CONFIG_HOME": str(root),
            "GIT_CONFIG_NOSYSTEM": "1",
        }
        self.git("init", "-b", "main")
        self.base = self.commit("Initial history")
        self.prs = root / "prs.json"
        self.releases = root / "releases.json"
        self.write(self.releases, json.loads((FIXTURES / "releases.json").read_text()))
        self.set_prs()
        self.task()

    @staticmethod
    def write(path, value):
        path.write_text(json.dumps(value), encoding="utf-8")

    def git(self, *args):
        return subprocess.run(  # noqa: S603
            ["git", "-c", "user.name=Example", "-c", "user.email=dev", *args],  # noqa: S607
            cwd=self.repo,
            env=self.env,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def commit(self, message):
        self.git("commit", "--allow-empty", "-m", message)
        return self.git("rev-parse", "HEAD")

    def record(self, relative, yaml):
        path = self.workspace / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"---\n{yaml}\n---\n", encoding="utf-8")
        return path

    def task(self, fields="", *, task_id="0042", status="ready"):
        return self.record(
            f"tasks/netlens/{task_id}-latency.md",
            f"id: '{task_id}'\nproject: netlens\ntitle: Latency\ninitiative: network\n"
            f"owner: maintainer\nstatus: {status}\n{fields}",
        )

    def feature(self, fields=""):
        self.record(
            "features/netlens/0031-latency.md",
            f"id: '0031'\nproject: netlens\ntitle: Latency\nstatus: proposed\n{fields}",
        )

    def set_prs(self, *prs):
        self.write(self.prs, prs)

    def pr(self, **updates):
        row = json.loads((FIXTURES / "prs.json").read_text())[0]
        return row | updates

    def args(self, output="json"):
        return [
            "progress",
            "--workspace",
            str(self.workspace),
            "--repo",
            str(self.repo),
            "--prs",
            str(self.prs),
            "--releases",
            str(self.releases),
            "--format",
            output,
            "--as-of",
            "2026-11-22",
        ]

    def report(self, capsys):
        status = main(self.args())
        out = capsys.readouterr()
        assert status == 0, out.err
        return json.loads(out.out)["data"]


@pytest.fixture
def history(tmp_path):
    return History(tmp_path)


def test_merged_pr_body_links_to_review_even_without_acceptance(history, capsys):
    merge = history.commit("Merge latency")
    history.set_prs(history.pr(mergeCommit={"oid": merge}))
    row = history.report(capsys)["tasks"][TASK]
    assert row["state"] == "review"
    assert row["merged"] == ["pr:7"]
    assert row["reviewed"] == ["pr:7"]
    assert row["accepted"] == row["tested"] == "unverified"
    assert row["generated"] == "unverified"
    assert row["committed"] == [f"commit:{merge}"]


def test_release_tags_must_contain_the_merge_commit(history, capsys):
    history.git("tag", "v0")
    merge = history.commit("Merge latency")
    history.commit("Follow-up")
    history.git("tag", "-a", "v1", "-m", "Release")
    history.set_prs(history.pr(mergeCommit={"oid": merge}))
    assert history.report(capsys)["tasks"][TASK]["shipped"] == ["tag:v1"]


def test_true_trailers_and_branch_only_commits_are_linked(history, capsys):
    history.git("switch", "-c", "task/netlens-0042-latency")
    via_branch = history.commit("Branch-only work")
    via_trailer = history.commit("Work\n\nTask: netlens/0042")
    history.git("switch", "main")
    misleading = history.commit("Task: netlens/0042\n\nA subject is not a trailer.")
    report = history.report(capsys)
    assert report["tasks"][TASK]["state"] == "in-progress"
    assert report["tasks"][TASK]["committed"] == sorted(
        [f"commit:{via_branch}", f"commit:{via_trailer}"]
    )
    assert set(report["disconnected_commits"]) == {misleading, history.base}


def test_pr_prefers_commit_trailer_then_branch_then_body(history, capsys):
    history.task(task_id="0041")
    history.task(task_id="0043")
    merge = history.commit("Change\n\nTask: netlens/0041")
    history.set_prs(
        history.pr(mergeCommit={"oid": merge}, headRefName="task/netlens-0043-latency"),
        history.pr(
            number=8,
            state="OPEN",
            isDraft=True,
            mergedAt=None,
            mergeCommit=None,
            headRefName="task/netlens-0043-followup",
        ),
        history.pr(
            number=9,
            state="CLOSED",
            mergedAt=None,
            mergeCommit=None,
            body="",
            reviewDecision="",
            statusCheckRollup=[],
        ),
    )
    report = history.report(capsys)
    assert report["tasks"]["netlens/0041"]["merged"] == ["pr:7"]
    assert report["tasks"]["netlens/0043"]["state"] == "in-progress"
    assert report["tasks"][TASK]["state"] == "ready"
    assert report["disconnected_prs"] == [9]


@pytest.mark.parametrize(
    ("draft", "blocked", "state"),
    [(False, False, "review"), (True, False, "in-progress"), (False, True, "blocked")],
)
def test_open_pr_column_respects_draft_and_dependencies(history, capsys, draft, blocked, state):
    if blocked:
        history.task(task_id="0041")
        history.task("depends_on: ['0041']")
    history.set_prs(
        history.pr(
            state="OPEN",
            isDraft=draft,
            mergedAt=None,
            mergeCommit=None,
            statusCheckRollup=[{"__typename": "StatusContext", "state": "SUCCESS"}],
        )
    )
    task = history.report(capsys)["tasks"][TASK]
    assert task["state"] == state
    assert task["tested"] == ["pr:7/check:1"]


def test_accepted_task_can_be_done_with_other_rungs_unverified(history, capsys):
    history.task("accepted_by: reviewer\naccepted_on: 2026-01-03", status="done")
    row = history.report(capsys)["tasks"][TASK]
    assert row["state"] == "done"
    assert row["accepted"] == [f"task:{TASK}"]
    assert row["committed"] == row["merged"] == row["tested"] == "unverified"


def test_default_branch_trailer_proves_commit_and_merge(history, capsys):
    oid = history.commit("Direct delivery\n\nTask: netlens/0042")
    row = history.report(capsys)["tasks"][TASK]
    assert row["committed"] == row["merged"] == [f"commit:{oid}"]
    assert row["state"] == "review"


def test_feature_implementing_follows_linked_work(history, capsys):
    history.feature("tasks: [task:netlens/0042]")
    history.git("branch", "task/netlens-0042-latency")
    assert history.report(capsys)["features"]["netlens/0031"]["state"] == "implementing"


def test_feature_requires_merge_specific_check_and_acceptance(history, capsys):
    history.commit("Work\n\nTask: netlens/0042")
    merge = history.commit("Merge latency")
    check = {"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"}
    history.set_prs(history.pr(mergeCommit={"oid": merge}, statusCheckRollup=[check]))
    history.feature("tasks: [task:netlens/0042]\naccepted_by: reviewer\naccepted_on: 2026-01-03")
    report = history.report(capsys)
    assert report["tasks"][TASK]["tested"] == ["pr:7/check:1"]
    assert report["features"]["netlens/0031"]["state"] == "implementing"
    history.task("accepted_by: reviewer\naccepted_on: 2026-01-03", status="done")
    history.set_prs(
        history.pr(mergeCommit={"oid": merge}, statusCheckRollup=[check | {"commitOid": merge}])
    )
    assert history.report(capsys)["features"]["netlens/0031"]["state"] == "verified"
    history.git("tag", "v1")
    assert history.report(capsys)["features"]["netlens/0031"]["state"] == "released"


def test_progress_reports_overdue_milestones_and_architecture_gaps(history, capsys):
    history.record(
        "milestones/netlens/m3-latency.md",
        "id: m3\ntitle: Latency\nhorizon: now\noutcome: One graph\ntarget_date: 2000-01-01",
    )
    history.task("milestone: m3")
    history.feature(
        "architecture:\n"
        "  - {ref: 'fp:f:old.py', relation: modifies}\n"
        "  - {ref: 'fp:f:new.py', relation: new}\n"
        "  - {ref: 'trail:old.py#symbol', relation: uses}"
    )
    report = history.report(capsys)
    assert report["stale_milestones"] == ["milestone:netlens/m3"]
    feature = report["features"]["netlens/0031"]
    assert feature["architecture"] == {
        "fp:f:old.py": "stale",
        "fp:f:new.py": "gap",
        "trail:old.py#symbol": "unverified",
    }
    assert report["stale_links"] == [["feature:netlens/0031", "fp:f:old.py"]]
    assert report["unimplemented_requirements"] == [["feature:netlens/0031", "fp:f:new.py"]]
    history.task("milestone: m3\naccepted_by: reviewer\naccepted_on: 2026-01-03", status="done")
    assert history.report(capsys)["stale_milestones"] == []


@pytest.mark.parametrize(
    ("value", "field"),
    [
        ("[", "json"),
        ('[{"number":"7"}]', "0.number"),
        (
            '[{"number":7,"title":"ignored","body":"","state":"MERGED","isDraft":false,'
            '"mergedAt":null,"headRefName":"work","reviewDecision":"","statusCheckRollup":[],'
            '"mergeCommit":{"oid":"--help"}}]',
            "0.mergeCommit.oid",
        ),
    ],
)
def test_bad_recorded_pr_data_is_a_file_and_field_error(history, capsys, value, field):
    history.prs.write_text(value, encoding="utf-8")
    assert main(history.args()) == 2
    err = capsys.readouterr().out
    assert "prs.json" in err and field in err and str(history.repo) not in err


@pytest.mark.parametrize("source", ["file", "parent", "git"])
def test_progress_rejects_symlinks(history, tmp_path, capsys, source):
    if source == "file":
        history.prs.unlink()
        history.prs.symlink_to(history.releases)
        filename = "prs.json"
    elif source == "parent":
        alias = tmp_path / "alias"
        alias.symlink_to(tmp_path, target_is_directory=True)
        history.prs = alias / history.prs.name
        filename = "prs.json"
    else:
        (history.repo / ".git" / "extra").symlink_to(history.prs)
        filename = ".git"
    assert main(history.args()) == 2
    err = capsys.readouterr().out
    assert filename in err and str(tmp_path) not in err


def test_progress_text_omits_raw_pr_content(history, capsys):
    private_path = history.repo / "private-file"
    history.set_prs(
        history.pr(
            title="\x1b[1m",
            body=f"Task: netlens/0042\n{private_path}",
            state="OPEN",
            mergedAt=None,
            mergeCommit=None,
        )
    )
    assert main(history.args("text")) == 0
    output = capsys.readouterr().out
    assert "netlens/0042" in output and "review" in output and "unverified" in output
    assert "\x1b" not in output and str(private_path) not in output


def test_generated_requires_a_supplied_artifact(history):
    from etat_major import evidence

    report = evidence.load_progress(
        history.workspace,
        history.repo,
        history.prs,
        history.releases,
        artifacts=(evidence.GeneratedArtifact(TASK, "reports/netlens/0042.md"),),
    )
    assert report.tasks[0].evidence.generated == ("artifact:reports/netlens/0042.md",)


def test_checked_out_topic_without_task_name_is_not_default(history, capsys):
    history.git("switch", "-c", "topic")
    oid = history.commit("Work\n\nTask: netlens/0042")
    task = history.report(capsys)["tasks"][TASK]
    assert task["committed"] == [f"commit:{oid}"]
    assert task["merged"] == "unverified"


def test_resolve_branch_with_numeric_project_segment(history, capsys):
    history.record(
        "tasks/netlens-23/0042-latency.md",
        "id: '0042'\nproject: netlens-23\ntitle: Latency\ninitiative: network\n"
        "owner: maintainer\nstatus: ready",
    )
    history.git("switch", "-c", "task/netlens-23-0042-latency")
    oid = history.commit("Branch-only work")
    task = history.report(capsys)["tasks"]["netlens-23/0042"]
    assert task["state"] == "in-progress"
    assert task["committed"] == [f"commit:{oid}"]


def test_architecture_resolves_components_and_symbols_with_recorded_indexes(history, capsys):
    history.feature(
        "architecture:\n"
        "  - {ref: 'fp:n:ui.hostdetail', relation: modifies}\n"
        "  - {ref: 'fp:n:ui.retired', relation: modifies}\n"
        "  - {ref: 'trail:src/etat_major/taskfile.py#old', relation: new}"
    )
    fixtures = FIXTURES.parent
    assert (
        main(
            history.args()
            + [
                "--graph",
                str(fixtures / "floorplan" / "graph.json"),
                "--trail",
                str(fixtures / "trail" / "wiring.json"),
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)["data"]
    assert report["features"]["netlens/0031"]["architecture"] == {
        "fp:n:ui.hostdetail": "existing",
        "fp:n:ui.retired": "stale",
        "trail:src/etat_major/taskfile.py#old": "gap",
    }


def test_recorded_pr_diagnostic_does_not_echo_unknown_check_types(history, capsys):
    history.set_prs(history.pr(statusCheckRollup=[{"__typename": str(history.repo)}]))
    assert main(history.args()) == 2
    err = capsys.readouterr().out
    assert "prs.json" in err and "statusCheckRollup" in err
    assert str(history.repo) not in err


def test_git_trailer_separator_cannot_inject_a_link(history, capsys):
    oid = history.commit("Unrelated\n\nTask: malformed\x1fnetlens/0042")
    assert oid in history.report(capsys)["disconnected_commits"]


def test_raw_architecture_remotes_are_omitted_from_progress(history, capsys):
    remote = "ssh:" + "//" + "hidden" + "/workspace"
    history.feature(f"architecture:\n  - {{ref: 'fp:n:x{remote}', relation: new}}")
    assert main(history.args()) == 0
    assert remote not in capsys.readouterr().out


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
