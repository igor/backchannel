import logging
import subprocess
import threading
from datetime import datetime
from subprocess import CompletedProcess

from config import Settings
from daemon import ChildProcesses, Job, Scheduler, build_jobs, next_nightly_epoch, _run_whatsapp_capture


class Clock:
    def __init__(self, value=0):
        self.value = value

    def __call__(self):
        return self.value


def test_each_declared_interval_fires_only_when_due():
    clock = Clock()
    fired = []
    jobs = [Job(name, interval, lambda name=name: fired.append(name), 0) for name, interval in (
        ("capture", 300), ("derive", 900), ("transcribe", 3600), ("heartbeat", 21600), ("index", 86400),
    )]
    scheduler = Scheduler(jobs, clock=clock, sleep=lambda seconds: None)
    scheduler.tick()
    for worker in scheduler.workers():
        worker.join()
    assert set(fired) == {"capture", "derive", "transcribe", "heartbeat", "index"}
    clock.value = 299
    scheduler.tick()
    assert len(fired) == 5
    clock.value = 300
    scheduler.tick()
    for worker in scheduler.workers():
        worker.join()
    assert fired.count("capture") == 2
    assert fired.count("derive") == 1


def test_failing_job_does_not_stop_other_jobs():
    clock = Clock()
    completed = []

    def fail():
        raise RuntimeError("fixture failure")

    scheduler = Scheduler([Job("bad", 300, fail, 0), Job("good", 300, lambda: completed.append("good"), 0)], clock=clock, sleep=lambda seconds: None)
    scheduler.tick()
    for worker in scheduler.workers():
        worker.join()
    assert completed == ["good"]
    assert scheduler.running == set()


def test_tick_skips_a_job_already_running():
    clock = Clock()
    started = threading.Event()
    release = threading.Event()
    calls = []

    def blocked():
        calls.append("run")
        started.set()
        release.wait()

    scheduler = Scheduler([Job("capture", 300, blocked, 0)], clock=clock, sleep=lambda seconds: None)
    scheduler.tick()
    assert started.wait(1)
    clock.value = 300
    scheduler.tick()
    assert calls == ["run"]
    release.set()
    for worker in scheduler.workers():
        worker.join()


def test_sigterm_finishes_inflight_job_then_stops_cleanly():
    clock = Clock()
    started = threading.Event()
    release = threading.Event()
    finished = []

    def blocked():
        started.set()
        release.wait()
        finished.append("finished")

    scheduler = Scheduler([Job("capture", 300, blocked, 0)], clock=clock, sleep=lambda seconds: None)
    scheduler.tick()
    assert started.wait(1)
    waiter = threading.Thread(target=scheduler.handle_sigterm, args=(None, None))
    waiter.start()
    release.set()
    waiter.join()
    assert finished == ["finished"]
    assert scheduler.stopping is True
    assert scheduler.running == set()


def test_transcribe_job_honours_configured_heavy_job_wrapper(tmp_path):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return CompletedProcess(argv, 0, stdout="", stderr="")

    settings = Settings.from_environment({
        "BC_CONFIG": str(tmp_path / "missing.json"),
        "BC_TRANSCRIBE_WRAPPER": "/bin/echo fixture-lock",
    })
    job = next(job for job in build_jobs(settings, run=run, now=0) if job.name == "transcribe-signal")
    job.function()
    assert calls[0][0] == ["/bin/echo", "fixture-lock", __import__("sys").executable, "-m", "transcribe", "--source", "signal"]


def test_next_nightly_epoch_uses_0317_and_rolls_to_tomorrow_after_it():
    before = datetime(2026, 8, 7, 3, 16).timestamp()
    after = datetime(2026, 8, 7, 3, 17).timestamp()
    assert datetime.fromtimestamp(next_nightly_epoch(before)) == datetime(2026, 8, 7, 3, 17)
    assert datetime.fromtimestamp(next_nightly_epoch(after)) == datetime(2026, 8, 8, 3, 17)


def test_finished_workers_do_not_accumulate():
    """The daemon runs for months. Without pruning, _workers grows by one object
    per job run and shutdown() joins every long-dead thread."""
    import daemon as daemon_module

    runs = []
    jobs = [daemon_module.Job(name="capture", interval=300, first_run=0.0,
                              function=lambda: runs.append(1))]
    clock = {"now": 0.0}
    scheduler = daemon_module.Scheduler(
        jobs, clock=lambda: clock["now"], sleep=lambda _: None)
    for index in range(200):
        clock["now"] = index * 300.0
        scheduler.tick()
    for worker in scheduler.workers():
        worker.join()
    scheduler.tick()

    assert len(runs) >= 200
    assert len(scheduler.workers()) <= 2


def test_overlapping_long_running_job_logs_at_debug_not_warning(caplog):
    clock = Clock()
    started = threading.Event()
    release = threading.Event()

    def blocked():
        started.set()
        release.wait()

    scheduler = Scheduler(
        [Job("capture-whatsapp", 300, blocked, 0, long_running=True)],
        clock=clock, sleep=lambda seconds: None,
    )
    with caplog.at_level(logging.DEBUG, logger="backchannel.daemon"):
        scheduler.tick()
        assert started.wait(1)
        clock.value = 300
        scheduler.tick()
    release.set()
    for worker in scheduler.workers():
        worker.join()
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING and "overlap" in r.message.lower()]
    debugs = [r for r in caplog.records if r.levelno == logging.DEBUG and "overlap" in r.message.lower()]
    assert warnings == []
    assert len(debugs) == 1


def test_overlapping_normal_job_still_logs_at_warning(caplog):
    clock = Clock()
    started = threading.Event()
    release = threading.Event()

    def blocked():
        started.set()
        release.wait()

    scheduler = Scheduler(
        [Job("derive-whatsapp", 300, blocked, 0)],
        clock=clock, sleep=lambda seconds: None,
    )
    with caplog.at_level(logging.DEBUG, logger="backchannel.daemon"):
        scheduler.tick()
        assert started.wait(1)
        clock.value = 300
        scheduler.tick()
    release.set()
    for worker in scheduler.workers():
        worker.join()
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING and "overlap" in r.message.lower()]
    assert len(warnings) == 1


class FakeChildProcess:
    def __init__(self):
        self.terminated = False
        self.killed = False
        self._alive = True

    def poll(self):
        return None if self._alive else 0

    def terminate(self):
        self.terminated = True
        self._alive = False

    def kill(self):
        self.killed = True
        self._alive = False

    def wait(self, timeout=None):
        return 0


def test_shutdown_terminates_registered_children_and_returns_promptly():
    clock = Clock()
    started = threading.Event()
    release = threading.Event()
    registry = ChildProcesses()
    fake_child = FakeChildProcess()
    registry.register(fake_child)

    def blocked():
        started.set()
        release.wait()

    scheduler = Scheduler(
        [Job("capture-whatsapp", 300, blocked, 0, long_running=True)],
        clock=clock, sleep=lambda seconds: None,
        terminate_children=registry.terminate_all,
    )
    scheduler.tick()
    assert started.wait(1)

    finisher = threading.Thread(target=scheduler.shutdown, kwargs={"join_timeout": 0.1})
    finisher.start()
    finisher.join(timeout=2)
    assert not finisher.is_alive()
    assert fake_child.terminated is True
    release.set()
    for worker in scheduler.workers():
        worker.join()


def test_run_whatsapp_capture_uses_real_files_never_pipe_and_appends_log(tmp_path):
    settings = Settings.from_environment({
        "BC_CONFIG": str(tmp_path / "missing.json"),
        "BC_LOG_ROOT": str(tmp_path / "logs"),
    })
    registry = ChildProcesses()
    captured_kwargs = {}

    class FakeProc:
        def __init__(self):
            self.pid = 4242

        def wait(self):
            return 0

    def popen_factory(argv, **kwargs):
        captured_kwargs.update(kwargs)
        return FakeProc()

    _run_whatsapp_capture(settings, registry, popen_factory=popen_factory)

    assert captured_kwargs["stdout"] is not subprocess.PIPE
    assert captured_kwargs["stderr"] is not subprocess.PIPE
    assert hasattr(captured_kwargs["stdout"], "write")
    assert captured_kwargs["stdout"].mode == "a"
    log_path = tmp_path / "logs" / "whatsapp-bridge.log"
    assert log_path.exists()
    assert registry._children == set()


def test_run_whatsapp_capture_nonzero_exit_raises_runtime_error(tmp_path):
    settings = Settings.from_environment({
        "BC_CONFIG": str(tmp_path / "missing.json"),
        "BC_LOG_ROOT": str(tmp_path / "logs"),
    })
    registry = ChildProcesses()

    class FakeProc:
        def wait(self):
            return 1

    def popen_factory(argv, **kwargs):
        return FakeProc()

    try:
        _run_whatsapp_capture(settings, registry, popen_factory=popen_factory)
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass
    assert registry._children == set()


def test_describe_jobs_use_the_shared_heavy_job_wrapper_and_are_not_long_running(tmp_path):
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return CompletedProcess(argv, 0, stdout="", stderr="")

    settings = Settings.from_environment({
        "BC_CONFIG": str(tmp_path / "missing.json"),
        "BC_TRANSCRIBE_WRAPPER": "/bin/echo fixture-lock",
        "BC_DESCRIBE_ENABLED": "1",
    })
    jobs = {job.name: job for job in build_jobs(settings, run=run, now=0)}
    assert jobs["describe-whatsapp"].interval == 3600
    assert jobs["describe-signal"].interval == 3600
    assert jobs["describe-whatsapp"].long_running is False
    assert jobs["describe-signal"].long_running is False
    jobs["describe-signal"].function()
    assert calls == [["/bin/echo", "fixture-lock", __import__("sys").executable, "-m", "describe", "--source", "signal"]]


def test_whatsapp_capture_runs_the_binary_directly_without_a_pty():
    """The pty wrapper makes the bridge start its interactive REPL, which exits on
    EOF. Observed in production: authenticate, connect, quit within seconds."""
    import daemon as daemon_module
    import subprocess as sp
    import tempfile, pathlib

    seen = {}

    class FakeProc:
        def poll(self): return 0
        def wait(self, timeout=None): return 0

    def fake_popen(argv, **kwargs):
        seen["argv"] = argv
        seen["stdin"] = kwargs.get("stdin")
        seen["stdout"] = kwargs.get("stdout")
        seen["cwd"] = kwargs.get("cwd")
        return FakeProc()

    class S:
        whatsapp_bridge_bin = "/fixture/bin/bridge"
        whatsapp_store = pathlib.Path("/fixture/home/store/messages.db")
        def as_env(self): return {}
    settings = S()
    settings.log_root = pathlib.Path(tempfile.mkdtemp())
    daemon_module._run_whatsapp_capture(settings, daemon_module.ChildProcesses(), fake_popen)

    assert seen["argv"] == ["/fixture/bin/bridge"], "must invoke the binary directly"
    assert not any("run_bridge" in str(a) for a in seen["argv"]), "must not use the pty wrapper"
    assert seen["stdin"] is sp.DEVNULL, "stdin must be DEVNULL so no REPL starts"
    assert seen["stdout"] is not sp.PIPE, "must stream to a file, never a pipe"
    assert seen["cwd"] == "/fixture/home", "must cwd into the dir holding store/ so the bridge finds its session"


def test_child_env_layers_settings_over_the_inherited_environment():
    """Passing settings.as_env() alone as `env=` wipes HOME and PATH. The bridge
    then fails with '$HOME is not defined', and anything needing ffmpeg, whisper-cli
    or qmd from PATH fails the same way."""
    import os
    import daemon as daemon_module

    class S:
        def as_env(self): return {"BC_CORPUS_ROOT": "/fixture/corpus"}

    env = daemon_module._child_env(S())
    assert env["BC_CORPUS_ROOT"] == "/fixture/corpus", "settings must win"
    assert "PATH" in env, "PATH must be inherited"
    if "HOME" in os.environ:
        assert env["HOME"] == os.environ["HOME"], "HOME must be inherited"


def _settings_with_describe(enabled, tmp_path):
    from config import Settings
    env = {"BC_CORPUS_ROOT": str(tmp_path), "BC_WHATSAPP_STORE": str(tmp_path / "store" / "m.db")}
    if enabled:
        env["BC_DESCRIBE_ENABLED"] = "1"
    return Settings.from_environment(env, config_path=tmp_path / "missing.json")


def test_describe_jobs_absent_by_default(tmp_path):
    # Image OCR is the least proven capability; a public install must not schedule it silently.
    import daemon as daemon_module
    names = [j.name for j in daemon_module.build_jobs(_settings_with_describe(False, tmp_path))]
    assert "describe-whatsapp" not in names
    assert "describe-signal" not in names
    # everything else still scheduled
    assert "capture-whatsapp" in names and "derive-whatsapp" in names and "index" in names


def test_describe_jobs_present_when_enabled(tmp_path):
    import daemon as daemon_module
    names = [j.name for j in daemon_module.build_jobs(_settings_with_describe(True, tmp_path))]
    assert "describe-whatsapp" in names
    assert "describe-signal" in names
