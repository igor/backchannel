"""One process that supervises Backchannel’s periodic work."""
from __future__ import annotations

import argparse
import logging
import os
import shlex
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from config import Settings
from derive import cli as derive_cli
from heartbeat import cli as heartbeat_cli
from index import cli as index_cli
from sources.signal import cli as signal_cli
from transcribe import cli as transcribe_cli


log = logging.getLogger("backchannel.daemon")


@dataclass(frozen=True)
class Job:
    name: str
    interval: int
    function: object
    first_run: float
    long_running: bool = False


class ChildProcesses:
    """Tracks supervised child processes so shutdown can terminate them instead
    of joining a worker thread blocked forever in Popen.wait()."""

    def __init__(self):
        self._lock = threading.Lock()
        self._children = set()

    def register(self, proc) -> None:
        with self._lock:
            self._children.add(proc)

    def discard(self, proc) -> None:
        with self._lock:
            self._children.discard(proc)

    def terminate_all(self, grace: float = 10.0) -> None:
        with self._lock:
            children = list(self._children)
        live = []
        for proc in children:
            try:
                if proc.poll() is None:
                    proc.terminate()
                    live.append(proc)
            except Exception:
                log.exception("backchannel daemon failed to terminate child pid=%s", getattr(proc, "pid", "?"))
        deadline = time.time() + grace
        for proc in live:
            remaining = deadline - time.time()
            try:
                proc.wait(timeout=max(0.0, remaining))
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    log.exception("backchannel daemon failed to kill child pid=%s", getattr(proc, "pid", "?"))


def next_nightly_epoch(now, localtime=time.localtime, mktime=time.mktime) -> float:
    current = localtime(now)
    candidate = list(current)
    candidate[3:6] = [3, 17, 0]
    target = mktime(tuple(candidate))
    return target if target > now else target + 86400


class Scheduler:
    def __init__(self, jobs, clock=time.time, sleep=time.sleep, thread_factory=threading.Thread, terminate_children=None):
        self.jobs = list(jobs)
        self.clock = clock
        self.sleep = sleep
        self.thread_factory = thread_factory
        self.terminate_children = terminate_children
        self.next_runs = {job.name: job.first_run for job in self.jobs}
        self.running = set()
        self._workers = []
        self._lock = threading.Lock()
        self.stopping = False

    def workers(self):
        return list(self._workers)

    def _run_job(self, job):
        try:
            job.function()
        except Exception:
            log.exception("backchannel daemon job failed: %s", job.name)
        finally:
            with self._lock:
                self.running.discard(job.name)

    def tick(self):
        now = self.clock()
        # Drop references to finished threads. This process is meant to run for
        # months; without pruning, _workers grows by roughly one object per job
        # run (~1,200/day across the full schedule) and shutdown() joins every
        # long-dead one.
        self._workers = [worker for worker in self._workers if worker.is_alive()]
        for job in self.jobs:
            if self.stopping or now < self.next_runs[job.name]:
                continue
            self.next_runs[job.name] += job.interval
            with self._lock:
                if job.name in self.running:
                    if job.long_running:
                        log.debug("backchannel daemon skipped overlapping long-running job: %s", job.name)
                    else:
                        log.warning("backchannel daemon skipped overlapping job: %s", job.name)
                    continue
                self.running.add(job.name)
            worker = self.thread_factory(target=self._run_job, args=(job,), name=f"backchannel-{job.name}")
            self._workers.append(worker)
            worker.start()

    def shutdown(self, join_timeout: float = 10.0):
        self.stopping = True
        if self.terminate_children is not None:
            self.terminate_children()
        for worker in self.workers():
            worker.join(timeout=join_timeout)
            if worker.is_alive():
                log.warning("backchannel daemon shutdown: worker did not finish in time: %s", worker.name)

    def handle_sigterm(self, signum, frame):
        log.info("backchannel daemon received SIGTERM; waiting for in-flight jobs")
        self.shutdown()

    def run(self):
        signal.signal(signal.SIGTERM, self.handle_sigterm)
        while not self.stopping:
            self.tick()
            next_due = min(self.next_runs.values())
            self.sleep(max(0.0, min(1.0, next_due - self.clock())))


def _child_env(settings) -> dict:
    """Backchannel settings layered ON TOP of the inherited environment.

    Never pass settings.as_env() to Popen as `env=` on its own: that REPLACES the
    whole environment, so HOME, PATH and everything else vanish. Observed in
    production — the WhatsApp bridge connected fine and then failed with
    "determine home directory: $HOME is not defined", and any child needing a
    binary from PATH (ffmpeg, whisper-cli, qmd) would fail the same way.
    """
    return {**os.environ, **settings.as_env()}


def _run_transcribe(settings, source, run):
    argv = [sys.executable, "-m", "transcribe", "--source", source]
    if settings.transcribe_wrapper:
        argv = shlex.split(settings.transcribe_wrapper) + argv
    result = run(argv, env=_child_env(settings), text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(f"backchannel transcribe {source} exited {result.returncode}")


def _run_describe(settings, source, run):
    argv = [sys.executable, "-m", "describe", "--source", source]
    if settings.transcribe_wrapper:
        argv = shlex.split(settings.transcribe_wrapper) + argv
    result = run(argv, env=_child_env(settings), text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(f"backchannel describe {source} exited {result.returncode}")


def _run_whatsapp_capture(settings, registry, popen_factory=subprocess.Popen):
    # Run the bridge binary directly, NOT through sources/whatsapp/run_bridge.sh.
    #
    # That wrapper wraps the bridge in `script -q /dev/null` to force line-buffered
    # output, which mattered when launchd read the bridge through a pipe. This daemon
    # writes to a real file handle instead, so the buffering problem does not arise —
    # and the pty the wrapper allocates is actively harmful: the bridge starts its
    # interactive REPL, immediately reads EOF on stdin, and exits. Observed in
    # production: authenticate, connect, download media, quit within seconds.
    #
    # stdin is DEVNULL and there is no tty, so the bridge stays in daemon mode. The
    # working directory must be the one holding `store/`, because the bridge resolves
    # its session database relative to cwd; launched from elsewhere it finds no session
    # and starts asking to be re-linked by QR.
    settings.log_root.mkdir(parents=True, exist_ok=True)
    log_path = settings.log_root / "whatsapp-bridge.log"
    with open(log_path, "a") as log_file:
        proc = popen_factory(
            [settings.whatsapp_bridge_bin],
            env=_child_env(settings),
            text=True,
            cwd=str(settings.whatsapp_store.parent.parent),
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=log_file,
        )
        registry.register(proc)
        try:
            returncode = proc.wait()
        finally:
            registry.discard(proc)
    if returncode:
        raise RuntimeError(f"backchannel capture whatsapp exited {returncode}")


def build_jobs(settings: Settings, run=subprocess.run, now=None, registry=None):
    now = time.time() if now is None else now
    env = settings.as_env()
    registry = ChildProcesses() if registry is None else registry
    jobs = [
        Job("capture-whatsapp", 300, lambda: _run_whatsapp_capture(settings, registry), now, long_running=True),
        Job("capture-signal", 300, lambda: signal_cli.main([], env), now),
        Job("derive-whatsapp", 900, lambda: derive_cli.main(["--source", "whatsapp"], env), now),
        Job("derive-signal", 900, lambda: derive_cli.main(["--source", "signal"], env), now),
        Job("transcribe-whatsapp", 3600, lambda: _run_transcribe(settings, "whatsapp", run), now),
        Job("transcribe-signal", 3600, lambda: _run_transcribe(settings, "signal", run), now),
    ]
    if settings.describe_enabled:
        jobs += [
            Job("describe-whatsapp", 3600, lambda: _run_describe(settings, "whatsapp", run), now),
            Job("describe-signal", 3600, lambda: _run_describe(settings, "signal", run), now),
        ]
    jobs += [
        Job("heartbeat-whatsapp", 21600, lambda: heartbeat_cli.check("whatsapp", env), now),
        Job("heartbeat-signal", 21600, lambda: heartbeat_cli.check("signal", env), now),
        Job("index", 86400, lambda: index_cli.main([], env, run=run), next_nightly_epoch(now)),
    ]
    return jobs


def main(argv=None, env=None) -> int:
    parser = argparse.ArgumentParser(prog="backchannel daemon")
    parser.parse_args(argv)
    registry = ChildProcesses()
    scheduler = Scheduler(
        build_jobs(Settings.from_environment(env), registry=registry),
        terminate_children=registry.terminate_all,
    )
    scheduler.run()
    return 0
