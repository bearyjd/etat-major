"""Shape of the release workflow, and its shell steps run against local fakes."""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"
BASH = shutil.which("bash")
GIT = shutil.which("git")
CHECK = "python scripts/release_check.py"
PYTHON = "3.12"
GATES = ['pip install -e ".[dev,web]"', "ruff check .", "ruff format --check .", "pytest"]
ON_MAIN = """if ! git merge-base --is-ancestor HEAD refs/remotes/origin/main; then
  echo "release check: the tagged commit is not on origin/main" >&2
  exit 1
fi
"""
# Commit of each tag, read from the action's repository when the pin was made.
PINS = {
    "actions/checkout": ("11d5960a326750d5838078e36cf38b85af677262", "v4.4.0"),
    "actions/setup-python": ("a26af69be951a213d495a4c3e4e4022e16d87065", "v5.6.0"),
}


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
        return {step["uses"].split("@")[0] for step in all_steps(workflow) if "uses" in step}

    assert used(release) <= used(load("ci.yml"))


def test_every_action_is_pinned_to_a_commit_with_its_version(release):
    text = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    lines = re.findall(r"uses: (\S+)(.*)", text)
    assert len(lines) == len([step for step in all_steps(release) if "uses" in step])
    for used, comment in lines:
        name, _, revision = used.partition("@")
        assert (revision, comment.strip()) == (PINS[name][0], f"# {PINS[name][1]}")


def keys(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from keys(value)
    elif isinstance(node, list):
        for value in node:
            yield from keys(value)


def test_nothing_can_skip_or_forgive_a_step(release):
    assert {"if", "continue-on-error", "shell", "defaults"} & set(keys(release)) == set()


def test_a_running_release_of_a_tag_is_never_cancelled(release):
    assert release["concurrency"] == {
        "group": "release-${{ github.ref }}",
        "cancel-in-progress": False,
    }


def test_the_check_commands_are_exact(release):
    assert run_line(release, "verify", "release_check.py")["run"] == CHECK
    notes = f'{CHECK} --notes-out "$RUNNER_TEMP/release-notes.md"'
    assert run_line(release, "release", "release_check.py")["run"] == notes


def test_no_expression_is_interpolated_into_a_shell(release):
    runs = [step["run"] for step in all_steps(release) if "run" in step]
    assert runs
    assert [run for run in runs if "${{" in run] == []


def test_checkouts_keep_no_credential(release):
    checkouts = [s for s in all_steps(release) if s.get("uses", "").startswith("actions/checkout")]
    assert len(checkouts) == 2
    assert all(step["with"]["persist-credentials"] is False for step in checkouts)
    assert all(step["with"]["ref"] == "${{ github.sha }}" for step in checkouts)


def test_the_write_token_reaches_one_step_only(release):
    holders = [s for s in all_steps(release) if "GH_TOKEN" in s.get("env", {})]
    assert holders == [run_line(release, "release", "gh release create")]


def pinned(name: str) -> str:
    return f"{name}@{PINS[name][0]}"


def test_verify_is_exactly_these_steps_in_this_order(release):
    checkout = {"ref": "${{ github.sha }}", "fetch-depth": 0, "persist-credentials": False}
    assert steps(release, "verify") == [
        {"uses": pinned("actions/checkout"), "with": checkout},
        {"uses": pinned("actions/setup-python"), "with": {"python-version": PYTHON}},
        {
            "name": "Require the tag to match the versions and the changelog",
            "env": {"RELEASE_TAG": "${{ github.ref_name }}"},
            "run": CHECK,
        },
        {"name": "Require the tagged commit to be on main", "run": ON_MAIN},
        *({"run": gate} for gate in GATES),
    ]


def test_no_job_or_workflow_setting_can_change_a_step(release):
    # An `env`, `container` or `defaults` entry here would reach the gates unseen.
    assert set(release) == {"name", True, "permissions", "concurrency", "jobs"}
    assert set(release["jobs"]["verify"]) == {"runs-on", "steps"}
    assert set(release["jobs"]["release"]) == {"needs", "runs-on", "permissions", "steps"}
    assert {job["runs-on"] for job in release["jobs"].values()} == {"ubuntu-latest"}


def test_ci_runs_exactly_the_gates():
    ci = load("ci.yml")
    assert set(ci) == {"name", True, "permissions", "jobs"}
    assert set(ci["jobs"]) == {"test"}
    assert set(ci["jobs"]["test"]) == {"runs-on", "steps"}
    assert steps(ci, "test") == [
        {"uses": "actions/checkout@v4"},
        {"uses": "actions/setup-python@v5", "with": {"python-version": PYTHON, "cache": "pip"}},
        *({"run": gate} for gate in GATES),
    ]


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


def git(repo: Path, *args: str) -> str:
    identity = ["-c", "user.name=t", "-c", "user.email=t", "-c", "commit.gpgsign=false"]
    done = subprocess.run(  # noqa: S603
        [GIT, *identity, *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env=git_env(),
    )
    return done.stdout.strip()


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


def tagged_origin(root: Path, *, annotated: bool) -> tuple[Path, Path, dict[str, str]]:
    """An `origin` with `v1.2.3` on its first of two commits, and a checkout that names it."""
    origin, checkout = root / "origin", root / "checkout"
    for repo in (origin, checkout):
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
    git(origin, "commit", "-q", "--allow-empty", "-m", "one")
    git(origin, "tag", *(["-a", "-m", "release"] if annotated else []), "v1.2.3")
    git(origin, "commit", "-q", "--allow-empty", "-m", "two")
    git(checkout, "remote", "add", "origin", str(origin))
    shas = {
        "commit": git(origin, "rev-parse", "v1.2.3^{commit}"),
        "ref": git(origin, "rev-parse", "refs/tags/v1.2.3"),
        "other": git(origin, "rev-parse", "main"),
        "empty": "",
    }
    return origin, checkout, shas


def recheck(release: dict, checkout: Path, sha: str):
    env = {**git_env(), "RELEASE_TAG": "v1.2.3", "VERIFIED_SHA": sha}
    return shell(run_line(release, "release", "ls-remote")["run"], checkout, env)


@pytest.mark.parametrize("annotated", [False, True])
@pytest.mark.parametrize(("name", "code"), [("commit", 0), ("ref", 0), ("other", 1), ("empty", 1)])
def test_the_tag_must_still_name_the_verified_commit(release, tmp_path, annotated, name, code):
    _, checkout, shas = tagged_origin(tmp_path, annotated=annotated)
    done = recheck(release, checkout, shas[name])
    assert done.returncode == code, done.stderr


@pytest.mark.parametrize("change", [("tag", "-f", "v1.2.3", "main"), ("tag", "-d", "v1.2.3")])
def test_a_moved_or_deleted_tag_is_refused(release, tmp_path, change):
    origin, checkout, shas = tagged_origin(tmp_path, annotated=False)
    git(origin, *change)
    done = recheck(release, checkout, shas["commit"])
    assert done.returncode == 1
    assert "no longer points" in done.stderr


def test_the_tag_is_rechecked_before_the_release_is_created(release):
    step = run_line(release, "release", "ls-remote")
    assert step["env"] == {
        "RELEASE_TAG": "${{ github.ref_name }}",
        "VERIFIED_SHA": "${{ github.sha }}",
    }
    order = steps(release, "release")
    assert order.index(step) == order.index(run_line(release, "release", "gh release create")) - 1


def fake_gh(directory: Path, *, exists: bool, create: int = 0) -> Path:
    """A `gh` that logs one bracketed argument list per call and answers `release view`."""
    log = directory / "calls.log"
    view = 0 if exists else 1
    body = (
        "#!/bin/sh\n"
        f"printf '[%s]' \"$@\" >> '{log}'\n"
        f"printf '\\n' >> '{log}'\n"
        f'if [ "$2" = view ]; then exit {view}; fi\n'
        f"exit {create}\n"
    )
    path = directory / "gh"
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)
    return log


def publish(release: dict, tmp_path: Path, tag: str, *, exists: bool, create: int = 0):
    log = fake_gh(tmp_path, exists=exists, create=create)
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


def test_a_failed_creation_fails_the_job(release, tmp_path):
    done, _ = publish(release, tmp_path, "v1.2.3", exists=False, create=1)
    assert done.returncode != 0


def test_a_hostile_tag_stays_one_argument(release, tmp_path):
    tag = "v1.0.0;touch$(touch pwned)"
    _, calls = publish(release, tmp_path, tag, exists=False)
    assert calls[0] == f"[release][view][{tag}]"
    assert not (tmp_path / "pwned").exists()
