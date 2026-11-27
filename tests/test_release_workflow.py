"""Shape of the release workflow, and its shell steps run against local fakes."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"
BASH = shutil.which("bash")
GIT = shutil.which("git")


def load(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def release() -> dict:
    return load("release.yml")


def steps(workflow: dict, job: str) -> list[dict]:
    return workflow["jobs"][job]["steps"]


def all_steps(workflow: dict) -> list[dict]:
    return [step for job in workflow["jobs"] for step in steps(workflow, job)]


def run_line(workflow: dict, job: str, needle: str) -> dict:
    found = [step for step in steps(workflow, job) if needle in step.get("run", "")]
    assert len(found) == 1, f"expected one {job} step containing {needle}"
    return found[0]


def test_only_pushed_version_tags_trigger_it(release):
    # YAML 1.1 reads the bare key `on` as true.
    assert release[True] == {"push": {"tags": ["v*"]}}


def test_only_the_release_job_may_write(release):
    assert release["permissions"] == {"contents": "read"}
    assert "permissions" not in release["jobs"]["verify"]
    assert release["jobs"]["release"]["permissions"] == {"contents": "write"}
    assert release["jobs"]["release"]["needs"] == "verify"
    assert set(release["jobs"]) == {"verify", "release"}


def test_no_action_beyond_those_ci_uses(release):
    def used(workflow):
        return {step["uses"] for step in all_steps(workflow) if "uses" in step}

    assert used(release) <= used(load("ci.yml"))


def test_no_expression_is_interpolated_into_a_shell(release):
    runs = [step["run"] for step in all_steps(release) if "run" in step]
    assert runs
    assert [run for run in runs if "${{" in run] == []


def test_checkouts_keep_no_credential(release):
    checkouts = [s for s in all_steps(release) if s.get("uses", "").startswith("actions/checkout")]
    assert len(checkouts) == 2
    assert all(step["with"]["persist-credentials"] is False for step in checkouts)


def test_the_write_token_reaches_one_step_only(release):
    holders = [s for s in all_steps(release) if "GH_TOKEN" in s.get("env", {})]
    assert holders == [run_line(release, "release", "gh release create")]


def test_verify_runs_the_ci_gates_with_the_ci_python(release):
    ci_steps = steps(load("ci.yml"), "test")
    verify = steps(release, "verify")
    ci_runs = [step["run"] for step in ci_steps if "run" in step]
    assert [step["run"] for step in verify if step.get("run") in ci_runs] == ci_runs

    def python(found):
        return [s["with"]["python-version"] for s in found if "python-version" in s.get("with", {})]

    assert python(verify) == python(ci_steps)
    assert verify[0]["with"]["fetch-depth"] == 0


@pytest.mark.parametrize("job", ["verify", "release"])
def test_each_job_checks_the_tag(release, job):
    step = run_line(release, job, "scripts/release_check.py")
    assert step["env"]["RELEASE_TAG"] == "${{ github.ref_name }}"


def test_verify_checks_the_tag_and_main_before_installing(release):
    order = [step.get("run", "") for step in steps(release, "verify")]

    def position(needle):
        return next(i for i, run in enumerate(order) if needle in run)

    assert position("release_check.py") < position("pip install")
    assert position("merge-base") < position("pip install")


def git(repo: Path, *args: str) -> None:
    identity = ["-c", "user.name=t", "-c", "user.email=t", "-c", "commit.gpgsign=false"]
    subprocess.run(  # noqa: S603
        [GIT, *identity, *args], cwd=repo, check=True, capture_output=True, env=git_env()
    )


def git_env() -> dict[str, str]:
    return {"PATH": os.defpath, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}


def shell(script: str, cwd: Path, env: dict[str, str]):
    return subprocess.run(  # noqa: S603
        [BASH, "-e", "-c", script], cwd=cwd, env=env, capture_output=True, text=True, timeout=60
    )


@pytest.mark.parametrize(("revision", "code"), [("main~1", 0), ("main", 0), ("side", 1)])
def test_only_a_commit_on_main_passes(release, tmp_path, revision, code):
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "commit", "-q", "--allow-empty", "-m", "one")
    git(tmp_path, "commit", "-q", "--allow-empty", "-m", "two")
    git(tmp_path, "update-ref", "refs/remotes/origin/main", "main")
    git(tmp_path, "checkout", "-q", "-b", "side")
    git(tmp_path, "commit", "-q", "--allow-empty", "-m", "side")
    git(tmp_path, "checkout", "-q", "--detach", revision)
    done = shell(run_line(release, "verify", "merge-base")["run"], tmp_path, git_env())
    assert done.returncode == code, done.stderr


def fake_gh(directory: Path, *, exists: bool) -> Path:
    """A `gh` that logs one bracketed argument list per call and answers `release view`."""
    log = directory / "calls.log"
    view = 0 if exists else 1
    body = (
        "#!/bin/sh\n"
        f"printf '[%s]' \"$@\" >> '{log}'\n"
        f"printf '\\n' >> '{log}'\n"
        f'if [ "$2" = view ]; then exit {view}; fi\n'
    )
    path = directory / "gh"
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)
    return log


def publish(release: dict, tmp_path: Path, tag: str, *, exists: bool):
    log = fake_gh(tmp_path, exists=exists)
    # PATH holds only the fake, so a real `gh` can never run.
    env = {"PATH": str(tmp_path), "RELEASE_TAG": tag, "RUNNER_TEMP": str(tmp_path)}
    done = shell(run_line(release, "release", "gh release create")["run"], tmp_path, env)
    return done, log.read_text(encoding="utf-8").splitlines()


def test_a_new_release_is_created_from_the_existing_tag(release, tmp_path):
    done, calls = publish(release, tmp_path, "v1.2.3", exists=False)
    assert done.returncode == 0, done.stderr
    assert calls == [
        "[release][view][v1.2.3]",
        "[release][create][v1.2.3][--verify-tag][--title][v1.2.3]"
        f"[--notes-file][{tmp_path}/release-notes.md]",
    ]


def test_an_existing_release_is_never_overwritten(release, tmp_path):
    done, calls = publish(release, tmp_path, "v1.2.3", exists=True)
    assert done.returncode == 1
    assert "already exists" in done.stderr
    assert calls == ["[release][view][v1.2.3]"]


def test_a_hostile_tag_stays_one_argument(release, tmp_path):
    tag = "v1.0.0;touch$(touch pwned)"
    _, calls = publish(release, tmp_path, tag, exists=False)
    assert calls[0] == f"[release][view][{tag}]"
    assert not (tmp_path / "pwned").exists()
