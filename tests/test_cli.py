import pytest
from pathlib import Path
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


@pytest.mark.skipif(not cli.SIGNAL_AVAILABLE, reason="signal source not in this tree (public export)")
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


@pytest.mark.skipif(not cli.SIGNAL_AVAILABLE, reason="signal source not in this tree (public export)")
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


@pytest.mark.skipif(not cli.SIGNAL_AVAILABLE, reason="signal source not in this tree (public export)")
def test_describe_dispatches_to_existing_main(monkeypatch):
    from describe import cli as describe_cli

    calls = []
    monkeypatch.setattr(describe_cli, "main", lambda argv, env: calls.append(argv) or 6)
    monkeypatch.setattr(cli, "describe_cli", describe_cli, raising=False)
    assert cli.main(["describe", "--source", "signal"], env={"BC_CONFIG": "/fixture/missing-config.json"}) == 0
    assert calls == [["--source", "signal"]]


@pytest.mark.skipif(not cli.SIGNAL_AVAILABLE, reason="signal source not in this tree (public export)")
def test_signal_available_in_dev_and_sources_include_signal():
    # The dev/test tree has sources.signal installed; this pins the contract that nothing
    # changes when the package is present. The 353-test suite is the broader proof.
    assert cli.SIGNAL_AVAILABLE is True
    assert cli.SOURCES == ("whatsapp", "signal")
    assert cli.LINK_SOURCES == ("signal",)


def test_source_signal_is_a_clean_argparse_error_when_signal_absent(monkeypatch):
    # A WhatsApp-only export omits sources/signal/. `backchannel capture --source signal`
    # must be a clean argparse exit (2), not an ImportError traceback. Absence is simulated
    # by patching the module truth the parser reads — nothing is uninstalled.
    monkeypatch.setattr(cli, "signal_cli", None)
    monkeypatch.setattr(cli, "SIGNAL_AVAILABLE", False)
    monkeypatch.setattr(cli, "SOURCES", ("whatsapp",))
    with pytest.raises(SystemExit) as raised:
        cli.main(["capture", "--source", "signal"], env={})
    assert raised.value.code == 2


def test_link_signal_is_a_clean_argparse_error_when_signal_absent(monkeypatch):
    monkeypatch.setattr(cli, "signal_cli", None)
    monkeypatch.setattr(cli, "SIGNAL_AVAILABLE", False)
    monkeypatch.setattr(cli, "LINK_SOURCES", ())
    with pytest.raises(SystemExit) as raised:
        cli.main(["link", "signal"], env={})
    assert raised.value.code == 2


def _whatsapp_only_tree(tmp_path):
    # A real tree with sources/signal omitted, as the public export ships it. Subprocess
    # imports keep the import machinery honest — no sys.modules tricks.
    import shutil
    root = Path(__file__).resolve().parents[1]
    tree = tmp_path / "tree"
    ignore = shutil.ignore_patterns("__pycache__", "tests")
    for name in ("cli.py", "config.py", "daemon.py", "link.py", "provision.py"):
        (tree / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(root / name, tree / name)
    for pkg in ("derive", "describe", "transcribe", "index", "heartbeat"):
        shutil.copytree(root / pkg, tree / pkg, ignore=ignore)
    (tree / "sources").mkdir()
    shutil.copy(root / "sources" / "__init__.py", tree / "sources" / "__init__.py")
    shutil.copytree(root / "sources" / "whatsapp", tree / "sources" / "whatsapp", ignore=ignore)
    return tree


def test_whatsapp_only_tree_imports_and_schedules_without_signal(tmp_path):
    import subprocess, sys
    tree = _whatsapp_only_tree(tmp_path)
    code = (
        "import cli, daemon\n"
        "assert cli.SIGNAL_AVAILABLE is False and cli.SOURCES == ('whatsapp',)\n"
        "from config import Settings\n"
        "names = [j.name for j in daemon.build_jobs(Settings.from_environment({}))]\n"
        "assert not any(n.endswith('-signal') for n in names), names\n"
    )
    done = subprocess.run([sys.executable, "-c", code], cwd=tree, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


def test_broken_signal_package_fails_loudly_instead_of_degrading(tmp_path):
    import subprocess, sys
    tree = _whatsapp_only_tree(tmp_path)
    signal_pkg = tree / "sources" / "signal"
    signal_pkg.mkdir()
    (signal_pkg / "__init__.py").write_text("")
    (signal_pkg / "cli.py").write_text("import missing_dep_xyz\n")
    for module in ("cli", "daemon"):        # each has its own guard; exercise both
        done = subprocess.run([sys.executable, "-c", f"import {module}"], cwd=tree,
                              capture_output=True, text=True)
        assert done.returncode != 0, module
        assert "missing_dep_xyz" in done.stderr, module
