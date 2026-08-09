import subprocess
import sys
from pathlib import Path
from subprocess import CompletedProcess

import pytest

import link


class FakePopen:
    def __init__(self, argv, lines=(), returncode=0, **kwargs):
        self.argv = argv
        self.kwargs = kwargs
        self.stdout = iter(lines)
        self._returncode = returncode
        self._exited = False
        self.terminated = False

    def wait(self):
        self._exited = True
        return self._returncode

    def poll(self):
        return self._returncode if self._exited else None

    def terminate(self):
        self.terminated = True
        self._exited = True


@pytest.mark.parametrize("text, expected", [
    ("scan sgnl://linkdevice?uuid=fixture&pub_key=fixture now", "sgnl://linkdevice?uuid=fixture&pub_key=fixture"),
    ("scan tsdevice://fixture-token now", "tsdevice://fixture-token"),
])
def test_extract_link_uri_accepts_both_signal_formats(text, expected):
    assert link.extract_link_uri(text) == expected


def test_link_uses_script_pty_and_never_puts_uri_in_argv(tmp_path, monkeypatch):
    calls = []
    opened = []
    monkeypatch.setattr(link.tempfile, "gettempdir", lambda: str(tmp_path))

    popens = []

    def popen_factory(argv, **kwargs):
        proc = FakePopen(argv, lines=["sgnl://linkdevice?uuid=fixture&pub_key=fixture\n"], **kwargs)
        popens.append(proc)
        return proc

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return CompletedProcess(argv, 0, stdout="", stderr="")

    assert link.main(
        ["signal"],
        {"BC_SIGNAL_CLI_BIN": "fixture-signal-cli"},
        run=run,
        pause=lambda prompt: None,
        opener=lambda path: opened.append(path),
        popen_factory=popen_factory,
    ) == 0
    assert popens[0].argv == ["script", "-q", "/dev/null", "fixture-signal-cli", "link", "-n", "Backchannel"]
    assert all("sgnl://" not in " ".join(argv) for argv, _ in calls)
    assert calls[0][0][:4] == ["qrencode", "-t", "PNG", "-o"]
    assert calls[0][1]["input"] == "sgnl://linkdevice?uuid=fixture&pub_key=fixture\n"
    assert opened and not Path(opened[0]).exists()
    assert not popens[0].terminated


def test_link_terminates_child_when_pause_raises(tmp_path, monkeypatch):
    # e.g. the user hits Ctrl-C while the QR is on screen: signal-cli must not be
    # left running just because the failure happened after qrencode succeeded.
    monkeypatch.setattr(link.tempfile, "gettempdir", lambda: str(tmp_path))
    popens = []

    def popen_factory(argv, **kwargs):
        proc = FakePopen(argv, lines=["sgnl://linkdevice?uuid=fixture&pub_key=fixture\n"], **kwargs)
        popens.append(proc)
        return proc

    def run(argv, **kwargs):
        return CompletedProcess(argv, 0, stdout="", stderr="")

    def pause(prompt):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        link.main(
            ["signal"],
            {"BC_SIGNAL_CLI_BIN": "fixture-signal-cli"},
            run=run,
            pause=pause,
            opener=lambda path: None,
            popen_factory=popen_factory,
        )
    assert popens[0].terminated


def test_link_returns_one_when_no_uri_is_emitted():
    def popen_factory(argv, **kwargs):
        return FakePopen(argv, lines=["no fixture uri\n"], **kwargs)

    def run(argv, **kwargs):
        return CompletedProcess(argv, 0, stdout="", stderr="")

    assert link.main(
        ["signal"],
        {"BC_SIGNAL_CLI_BIN": "fixture-signal-cli"},
        run=run,
        pause=lambda prompt: None,
        popen_factory=popen_factory,
    ) == 1


def test_link_does_not_deadlock_on_large_post_uri_output():
    # A real OS pipe, not the FakePopen iterator: signal-cli logs its initial sync after the
    # URI, and if nothing drains stdout the child blocks on a full pipe buffer and wait()
    # never returns. Before the drain thread this test hangs instead of failing.
    child = (
        "import sys\n"
        "print('sgnl://linkdevice?uuid=fixture')\n"
        "sys.stdout.flush()\n"
        "sys.stdout.write('x' * 300000 + '\\n')\n"
        "sys.stdout.flush()\n"
    )

    def factory(argv, **kwargs):
        return subprocess.Popen(
            [sys.executable, "-c", child],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )

    def fake_run(argv, **kwargs):
        return CompletedProcess(argv, 0, stdout="", stderr="")

    assert link.main(
        ["signal"], env={}, run=fake_run, pause=lambda *a: None,
        opener=lambda path: None, popen_factory=factory,
    ) == 0
