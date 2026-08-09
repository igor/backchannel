import pytest
from subprocess import CompletedProcess

import cli


@pytest.mark.parametrize("argv", [
    ["capture", "--help"],
    ["derive", "--help"],
    ["transcribe", "--help"],
    ["describe", "--help"],
    ["index", "--help"],
    ["link", "--help"],
    ["setup", "--help"],
    ["daemon", "--help"],
])
def test_each_public_verb_has_zero_exit_help(argv):
    with pytest.raises(SystemExit) as raised:
        cli.main(argv)
    assert raised.value.code == 0


def test_capture_signal_dispatches_to_existing_main(monkeypatch):
    monkeypatch.setattr(cli.signal_cli, "main", lambda argv, env: 17)
    assert cli.main(["capture", "--source", "signal"], env={"BC_CONFIG": "/fixture/missing-config.json"}) == 17


def test_capture_whatsapp_delegates_to_the_daemon_supervisor(monkeypatch, tmp_path):
    """`backchannel capture --source whatsapp` must run the bridge exactly as the
    daemon does. Running it here through the pty wrapper with capture_output=True
    reproduced two production bugs: the pty starts the bridge's interactive REPL,
    which exits on EOF, and capture_output buffers a months-long process in memory."""
    import daemon as daemon_module

    seen = {}

    class FakeProc:
        def poll(self): return 0
        def wait(self, timeout=None): return 0

    def fake_popen(argv, **kwargs):
        seen["argv"] = argv
        seen["stdin"] = kwargs.get("stdin")
        return FakeProc()

    real = daemon_module._run_whatsapp_capture
    monkeypatch.setattr(
        daemon_module, "_run_whatsapp_capture",
        lambda settings, registry, popen_factory=None: real(settings, registry, fake_popen),
    )

    assert cli.main(
        ["capture", "--source", "whatsapp"],
        env={"BC_CONFIG": "/fixture/missing-config.json",
             "BC_WHATSAPP_BRIDGE_BIN": "fixture-bridge",
             "BC_LOG_ROOT": str(tmp_path)},
    ) == 0
    assert seen["argv"] == ["fixture-bridge"], "must invoke the binary directly"
    assert not any("run_bridge" in str(a) for a in seen["argv"]), "must not use the pty wrapper"


def test_derive_dispatches_to_existing_main(monkeypatch):
    calls = []
    monkeypatch.setattr(cli.derive_cli, "main", lambda argv, env: calls.append(argv) or 3)
    assert cli.main(["derive", "--source", "signal"], env={"BC_CONFIG": "/fixture/missing-config.json"}) == 0
    assert calls == [["--source", "signal"]]


def test_transcribe_dispatches_to_existing_main(monkeypatch):
    calls = []
    monkeypatch.setattr(cli.transcribe_cli, "main", lambda argv, env: calls.append(argv) or 4)
    assert cli.main(["transcribe", "--source", "whatsapp"], env={"BC_CONFIG": "/fixture/missing-config.json"}) == 0
    assert calls == [["--source", "whatsapp"]]


def test_index_dispatches_to_existing_main(monkeypatch):
    monkeypatch.setattr(cli.index_cli, "main", lambda argv, env: 5)
    assert cli.main(["index"], env={"BC_CONFIG": "/fixture/missing-config.json"}) == 5


def test_describe_dispatches_to_existing_main(monkeypatch):
    from describe import cli as describe_cli

    calls = []
    monkeypatch.setattr(describe_cli, "main", lambda argv, env: calls.append(argv) or 6)
    monkeypatch.setattr(cli, "describe_cli", describe_cli, raising=False)
    assert cli.main(["describe", "--source", "signal"], env={"BC_CONFIG": "/fixture/missing-config.json"}) == 0
    assert calls == [["--source", "signal"]]
