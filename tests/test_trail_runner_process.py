from io import BytesIO

import pytest

from etat_major import trail_runner
from etat_major.trail_runner import TrailRunError


def test_signals_process_group_before_waiting_on_exited_leader(tmp_path, monkeypatch):
    events = []

    class FinishedProcess:
        pid = 42
        returncode = None

        stdout = BytesIO()

        def wait(self, *, timeout):
            assert 0 < timeout < 5
            events.append("reap")
            self.returncode = 0
            return 0

    def observe(kind, pid, flags):
        assert kind == trail_runner.os.P_PID
        assert pid == 42
        assert flags & trail_runner.os.WNOWAIT
        events.append("observe")
        return object()

    def signal_group(pid, sig):
        assert pid == 42
        assert sig == trail_runner.signal.SIGKILL
        events.append("signal")

    monkeypatch.setattr(trail_runner.subprocess, "Popen", lambda *args, **kwargs: FinishedProcess())
    monkeypatch.setattr(trail_runner, "_drain_output", lambda *args: None)
    monkeypatch.setattr(trail_runner.os, "waitid", observe)
    monkeypatch.setattr(trail_runner.os, "killpg", signal_group)
    trail_runner._run(tmp_path / "trail", tmp_path, {})
    assert events[0] == "observe"
    assert events[-2:] == ["signal", "reap"]


@pytest.mark.parametrize(
    ("timed_out", "message"),
    [(True, "timed out"), (False, "could not signal Trail's process group")],
)
def test_reports_group_cleanup_failure_without_masking_timeout(
    tmp_path, monkeypatch, timed_out, message
):
    class FakeProcess:
        pid = 42

        stdout = BytesIO()

        def wait(self, *, timeout):
            assert 0 < timeout < 5
            return 0

    def drain(process, deadline, root):
        if timed_out:
            raise TrailRunError(root, "trail build", "timed out")

    def cannot_signal(pid, sig):
        raise PermissionError("private system diagnostic")

    monkeypatch.setattr(trail_runner.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    monkeypatch.setattr(trail_runner, "_drain_output", drain)
    monkeypatch.setattr(trail_runner.os, "waitid", lambda *args: object())
    monkeypatch.setattr(trail_runner.os, "killpg", cannot_signal)
    with pytest.raises(TrailRunError, match=message) as error:
        trail_runner._run(tmp_path / "trail", tmp_path, {})
    assert "private system diagnostic" not in str(error.value)
    if timed_out:
        assert error.value.__notes__ == ["could not signal Trail's process group"]


def test_timeout_cleanup_is_bounded_when_signals_are_denied(tmp_path, monkeypatch):
    events = []

    class UninterruptibleProcess:
        pid = 42
        stdout = BytesIO()

        def wait(self, *, timeout):
            assert 0 < timeout < 5
            events.append("bounded reap")
            raise trail_runner.subprocess.TimeoutExpired("trail", timeout)

    def drain(process, deadline, root):
        raise TrailRunError(root, "trail build", "timed out")

    def deny_signal(kind):
        def deny(pid, sig):
            assert pid == 42
            events.append(kind)
            raise PermissionError("private diagnostic")

        return deny

    process = UninterruptibleProcess()
    monkeypatch.setattr(trail_runner.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(trail_runner, "_drain_output", drain)
    monkeypatch.setattr(trail_runner.os, "waitid", lambda *args: None)
    monkeypatch.setattr(trail_runner.os, "killpg", deny_signal("group"))
    monkeypatch.setattr(trail_runner.os, "kill", deny_signal("leader"))

    with pytest.raises(TrailRunError, match="timed out") as error:
        trail_runner._run(tmp_path / "trail", tmp_path, {})
    assert events == ["group", "leader", "bounded reap"]
    assert process.stdout.closed
    assert error.value.__notes__ == [
        "could not signal Trail's process group",
        "could not signal Trail directly",
        "could not reap Trail within the cleanup timeout",
    ]
