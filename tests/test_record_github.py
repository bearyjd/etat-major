"""The capture script against a fake gh: no network, no real GitHub call."""

import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from runpy import run_path

import pytest

from etat_major.evidence_records import load_prs, load_releases

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/record_github.py"
FIXTURES = ROOT / "tests/fixtures/progress"
REPO = '{"nameWithOwner": "octo/demo", "url": "https://github.example/octo/demo"}'
PR_FIELDS = (
    "number,title,body,state,isDraft,mergedAt,headRefName,reviewDecision,"
    "statusCheckRollup,mergeCommit"
)
FAKE = """\
#!{python}
import json, os, subprocess, sys, time
behavior = json.load(open({behavior!r}))
record = {{"argv": sys.argv[1:], "env": dict(os.environ), "cwd": os.getcwd()}}
record["stdin"] = sys.stdin.read()
with open({log!r}, "a") as log:
    log.write(json.dumps(record) + "\\n")
time.sleep(behavior.get("sleep", 0))
if behavior.get("grandchild"):
    subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"])
if behavior.get("swap") and sys.argv[1] == "release":
    os.rename(behavior["swap"], behavior["swap"] + ".real")
    os.symlink(behavior["swap"] + ".real", behavior["swap"])
key = {{"repo": "repo", "pr": "pr", "release": "release"}}[sys.argv[1]]
sys.stdout.write(behavior[key])
sys.exit(behavior.get("exit", 0))
"""
GOOD = {
    "repo": REPO,
    "pr": (FIXTURES / "prs.json").read_text(),
    "release": (FIXTURES / "releases.json").read_text(),
}
ALLOWED = {
    "PATH", "HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME",
    "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS", "GH_CONFIG_DIR", "LANG", "LC_ALL",
}  # fmt: skip
PINNED = {
    "GH_PROMPT_DISABLED": "1",
    "GH_NO_UPDATE_NOTIFIER": "1",
    "NO_COLOR": "1",
    "GH_PAGER": "cat",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_OPTIONAL_LOCKS": "0",
}
TOKENS = ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN")


@pytest.fixture(scope="module")
def script():
    return run_path(str(SCRIPT))


class Setup:
    def __init__(self, root: Path, behavior: dict) -> None:
        self.bin = root / "bin"
        self.bin.mkdir()
        self.log = root / "calls.log"
        self.checkout = root / "checkout"
        self.checkout.mkdir()
        self.out = root / "out"
        self.out.mkdir()
        (root / "behavior.json").write_text(json.dumps({**GOOD, **behavior}))
        gh = self.bin / "gh"
        gh.write_text(
            FAKE.format(
                python=sys.executable, behavior=str(root / "behavior.json"), log=str(self.log)
            )
        )
        gh.chmod(0o755)
        self.environ = {
            "PATH": str(self.bin),
            "HOME": str(root),
            "LC_ALL": "C.UTF-8",
            "GH_TOKEN": "secret-one",
            "GITHUB_TOKEN": "secret-two",
            "GH_ENTERPRISE_TOKEN": "secret-three",
            "GITHUB_ENTERPRISE_TOKEN": "secret-four",
            "HTTPS_PROXY": "http://proxy.invalid",
            "EDITOR": "vi",
        }

    @property
    def calls(self) -> list[dict]:
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def run(self, script, capsys, *, answer="yes", interactive=True, timeout=30.0, environ=None):
        def confirm(_prompt: str) -> str:
            if isinstance(answer, BaseException):
                raise answer
            return answer

        code = script["main"](
            [str(self.checkout), str(self.out)],
            environ=self.environ if environ is None else environ,
            interactive=interactive,
            confirm=confirm,
            timeout=timeout,
        )
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    def written(self) -> list[str]:
        return sorted(os.listdir(self.out))


@pytest.fixture
def setup(tmp_path):
    def make(**behavior):
        return Setup(tmp_path, behavior)

    return make


def test_runs_only_the_three_fixed_commands_without_shell_or_repo_flag(script, setup, capsys):
    s = setup()
    code, _, _ = s.run(script, capsys)
    assert code == 0
    assert [c["argv"] for c in s.calls] == [
        ["repo", "view", "--json", "nameWithOwner,url"],
        ["pr", "list", "--state", "all", "--limit", "1000", "--json", PR_FIELDS],
        ["release", "list", "--limit", "1000", "--json", "tagName,publishedAt"],
    ]
    assert all(c["stdin"] == "" for c in s.calls)


def test_child_environment_is_the_allow_list_plus_pinned_values(script, setup, capsys):
    s = setup()
    s.environ.update({"XDG_CONFIG_HOME": "/cfg", "GH_CONFIG_DIR": "/ghcfg", "LANG": "C.UTF-8"})
    code, _, _ = s.run(script, capsys)
    assert code == 0
    for call in s.calls:
        env = call["env"]
        assert set(env) == (ALLOWED & set(s.environ)) | set(PINNED)
        assert not set(TOKENS) & set(env)
        assert {k: env[k] for k in PINNED} == PINNED
        assert env["GH_CONFIG_DIR"] == "/ghcfg"


def test_runs_gh_in_the_named_checkout_and_prints_the_resolved_target(script, setup, capsys):
    s = setup()
    code, out, _ = s.run(script, capsys)
    assert code == 0
    assert {c["cwd"] for c in s.calls} == {str(s.checkout.resolve())}
    assert "github.example" in out
    assert "octo/demo" in out
    assert s.written() == ["prs.json", "releases.json"]


@pytest.mark.parametrize("answer", ["no", "", "y", "YES ", EOFError()])
def test_declined_or_unanswered_confirmation_writes_and_fetches_nothing(
    script, setup, capsys, answer
):
    s = setup()
    code, _, err = s.run(script, capsys, answer=answer)
    assert code == 2
    assert "not confirmed" in err
    assert s.written() == []
    assert [c["argv"][0] for c in s.calls] == ["repo"]


@pytest.mark.parametrize("name", ["GH_HOST", "GH_REPO"])
def test_refuses_when_host_or_repo_override_is_set(script, setup, capsys, name):
    s = setup()
    s.environ[name] = "elsewhere"
    code, _, err = s.run(script, capsys)
    assert code == 2
    assert name in err
    assert s.calls == []
    assert s.written() == []


def test_refuses_without_an_interactive_stdin(script, setup, capsys):
    s = setup()
    code, _, err = s.run(script, capsys, interactive=False)
    assert code == 2
    assert "interactive" in err
    assert s.calls == [] and s.written() == []


@pytest.mark.parametrize("extra", [".", "relative/bin", "", "bin"])
def test_refuses_relative_or_dot_path_entries(script, setup, capsys, extra):
    s = setup()
    s.environ["PATH"] = os.pathsep.join([str(s.bin), extra])
    code, _, err = s.run(script, capsys)
    assert code == 2
    assert "PATH" in err
    assert s.calls == [] and s.written() == []


def test_refuses_when_gh_is_not_found(script, setup, capsys, tmp_path):
    s = setup()
    s.environ["PATH"] = str(tmp_path)
    code, _, err = s.run(script, capsys)
    assert code == 2
    assert "gh" in err
    assert s.written() == []


def test_missing_checkout_or_output_directory_is_an_error(script, setup, capsys):
    s = setup()
    s.out.rmdir()
    code, _, err = s.run(script, capsys)
    assert code == 2
    assert "Traceback" not in err
    assert s.calls == []


@pytest.mark.parametrize(
    ("which", "text", "field"),
    [
        ("pr", "[" + " " * (4 * 1024 * 1024), "exceeds"),
        ("pr", "not json", "json"),
        ("pr", '[{"number": 1, "number": 2}]', "json"),
        ("pr", "[NaN]", "json"),
        ("pr", "{}", "json"),
        ("release", "{}", "json"),
        ("release", "[1]", "0"),
    ],
)
def test_invalid_output_fails_with_file_and_field_and_writes_nothing(
    script, setup, capsys, which, text, field
):
    s = setup(**{which: text})
    code, _, err = s.run(script, capsys)
    assert code == 2
    name = "prs.json" if which == "pr" else "releases.json"
    assert name in err
    assert field in err
    assert "Traceback" not in err
    assert str(s.out) not in err and "secret" not in err and "github.example" not in err
    assert s.written() == []


@pytest.mark.parametrize("variant", ["bad_state", "duplicate_number"])
def test_pr_set_failing_load_prs_writes_nothing(script, setup, capsys, variant):
    row = json.loads(GOOD["pr"])[0]
    rows = [{**row, "state": "WEIRD"}] if variant == "bad_state" else [row, dict(row)]
    s = setup(pr=json.dumps(rows))
    code, _, err = s.run(script, capsys)
    assert code == 2 and "prs.json" in err and "field" in err
    assert s.written() == []


def test_an_existing_target_file_is_not_replaced(script, setup, capsys):
    s = setup()
    (s.out / "prs.json").write_text("keep")
    code, _, err = s.run(script, capsys)
    assert code == 2 and "prs.json" in err
    assert (s.out / "prs.json").read_text() == "keep"
    assert s.written() == ["prs.json"]


def test_gh_failure_writes_nothing_and_hides_its_stderr(script, setup, capsys):
    s = setup(exit=1)
    code, _, err = s.run(script, capsys)
    assert code == 2
    assert "gh" in err and "Traceback" not in err
    assert s.written() == []


def test_one_thousand_rows_warn_about_truncation_but_succeed(script, setup, capsys):
    row = json.loads(GOOD["pr"])[0]
    rows = [{**row, "number": n} for n in range(1, 1001)]
    s = setup(pr=json.dumps(rows))
    code, _, err = s.run(script, capsys)
    assert code == 0
    assert "1000" in err and "truncat" in err.lower()
    assert len(load_prs(s.out / "prs.json")) == 1000


def test_timeout_kills_gh_and_writes_nothing(script, setup, capsys):
    s = setup(sleep=30)
    started = time.monotonic()
    code, _, err = s.run(script, capsys, timeout=0.5)
    assert code == 2
    assert "timed out" in err
    assert time.monotonic() - started < 10
    assert s.written() == []


def test_output_round_trips_through_the_loaders_without_leaks(script, setup, capsys):
    s = setup()
    code, _, _ = s.run(script, capsys)
    assert code == 0
    assert (s.out / "prs.json").read_text() == GOOD["pr"]
    assert (s.out / "releases.json").read_text() == GOOD["release"]
    assert load_prs(s.out / "prs.json") == load_prs(FIXTURES / "prs.json")
    assert load_releases(s.out / "releases.json") == load_releases(FIXTURES / "releases.json")
    for name in s.written():
        data = (s.out / name).read_text()
        assert str(s.out) not in data and "secret" not in data and "github.example" not in data
        assert (s.out / name).stat().st_mode & 0o777 == 0o600


def test_the_script_refuses_to_start_without_a_terminal(setup):
    s = setup()
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT), str(s.checkout), str(s.out)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            **s.environ,
            "HOME": os.environ["HOME"],
            "PYTHONPATH": str(ROOT / "src"),
        },
        timeout=60,
    )
    assert result.returncode == 2
    assert "interactive" in result.stderr
    assert s.calls == [] and s.written() == []


def test_script_stays_small_and_outside_src():
    lines = textwrap.dedent(SCRIPT.read_text()).splitlines()
    assert len(lines) < 400


HOSTILE_REPO = [
    "[" * 200_000,
    '{"url": 5, "nameWithOwner": "a/b"}',
    '{"url": "https://h.example/x", "nameWithOwner": 5}',
    '{"url": "https://h.example/x", "nameWithOwner": "a/b/c"}',
    '{"url": "https://h.example/x", "nameWithOwner": "a b/c"}',
    '{"url": "https://h.example/x", "nameWithOwner": "a/b\\n"}',
    '{"url": "https://h.example/x"}',
    "[]",
    "null",
]


@pytest.mark.parametrize("repo", HOSTILE_REPO, ids=range(len(HOSTILE_REPO)))
def test_hostile_repo_view_output_is_a_plain_error(script, setup, capsys, repo):
    s = setup(repo=repo)
    code, _, err = s.run(script, capsys)
    assert code == 2
    assert "gh repo view: unexpected output" in err
    assert "Traceback" not in err and str(s.out.parent) not in err
    assert len(s.calls) == 1 and s.written() == []


def test_symlinked_output_directory_is_refused_before_gh_runs(script, setup, capsys):
    s = setup()
    real = s.out.parent / "real-out"
    real.mkdir()
    s.out.rmdir()
    s.out.symlink_to(real)
    code, _, err = s.run(script, capsys)
    assert code == 2 and "symbolic link" in err
    assert "Traceback" not in err and str(s.out.parent) not in err
    assert s.calls == [] and os.listdir(real) == []


def test_symlinked_parent_of_the_output_directory_is_refused_before_gh_runs(script, setup, capsys):
    s = setup()
    link = s.out.parent / "link"
    link.symlink_to(s.out.parent)
    s.out = link / "out"
    code, _, err = s.run(script, capsys)
    assert code == 2 and "symbolic link" in err
    assert "Traceback" not in err and str(s.out.parent) not in err
    assert s.calls == [] and os.listdir(s.out.parent / "out") == []


def test_output_directory_swapped_for_a_symlink_mid_run_is_a_plain_error(script, setup, capsys):
    s = setup()
    (s.bin.parent / "behavior.json").write_text(json.dumps({**GOOD, "swap": str(s.out)}))
    code, _, err = s.run(script, capsys)
    assert code == 2
    assert "Traceback" not in err and str(s.out.parent) not in err
    assert os.listdir(s.out) == []


def test_a_grandchild_holding_the_pipe_does_not_outlast_the_timeout(script, setup, capsys):
    s = setup(grandchild=True)
    started = time.monotonic()
    code, _, err = s.run(script, capsys, timeout=1.0)
    assert code == 2 and "timed out" in err
    assert time.monotonic() - started < 4
    assert s.written() == []


def test_a_timer_firing_after_gh_finished_is_not_a_timeout(script, setup, capsys, monkeypatch):
    class LateTimer:
        def __init__(self, _interval, function):
            self.function = function

        def start(self):
            pass

        def cancel(self):
            self.function()

    monkeypatch.setitem(script["run_gh"].__globals__, "Timer", LateTimer)
    s = setup()
    code, _, err = s.run(script, capsys)
    assert code == 0 and "timed out" not in err
    assert s.written() == ["prs.json", "releases.json"]


def test_interrupt_at_the_prompt_is_reported_and_writes_nothing(script, setup, capsys):
    s = setup()
    code, _, err = s.run(script, capsys, answer=KeyboardInterrupt())
    assert code == 2
    assert "record_github: interrupted; nothing was written" in err
    assert "Traceback" not in err
    assert len(s.calls) == 1 and s.written() == []


def test_a_stale_check_file_does_not_break_a_run(script, setup, capsys):
    s = setup()
    for name in ("prs.json", "releases.json"):
        (s.out / f".{name}.check.tmp").write_text("stale")
    code, _, err = s.run(script, capsys)
    assert code == 0, err
    assert (s.out / ".prs.json.check.tmp").read_text() == "stale"
    assert len(s.written()) == 4


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_an_unwritable_output_directory_reports_the_check_file(script, setup, capsys):
    s = setup()
    s.out.chmod(0o500)
    try:
        code, _, err = s.run(script, capsys)
    finally:
        s.out.chmod(0o700)
    assert code == 2 and "cannot create the check file" in err
    assert "Traceback" not in err and str(s.out.parent) not in err
    assert s.written() == []


def test_interrupt_between_the_two_files_removes_the_first(script, setup, capsys, monkeypatch):
    real = script["write_new_text"]

    def interrupting(path, text, **kwargs):
        if path.name == "releases.json":
            raise KeyboardInterrupt
        return real(path, text, **kwargs)

    monkeypatch.setitem(script["publish"].__globals__, "write_new_text", interrupting)
    s = setup()
    code, _, err = s.run(script, capsys)
    assert code == 2
    assert "interrupted; nothing was written" in err and "Traceback" not in err
    assert s.written() == []
