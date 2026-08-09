"""Public Backchannel console command."""
import argparse
import os
import sys
import subprocess
from pathlib import Path

from config import Settings
from derive import cli as derive_cli
from describe import cli as describe_cli
from heartbeat import cli as heartbeat_cli
from index import cli as index_cli
from sources.signal import cli as signal_cli
from transcribe import cli as transcribe_cli


SOURCES = ("whatsapp", "signal")


def _settings_env(env):
    settings = Settings.from_environment(env)
    return settings, {**dict(env), **settings.as_env()}


def main(argv=None, env=None, run=subprocess.run) -> int:
    parser = argparse.ArgumentParser(prog="backchannel")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("capture", "derive", "transcribe", "describe", "heartbeat"):
        command = commands.add_parser(name)
        command.add_argument("--source", required=True, choices=SOURCES)
        if name == "derive":
            command.add_argument("--rebuild", action="store_true")
            command.add_argument("--dry-run", action="store_true")
    commands.add_parser("index")
    link = commands.add_parser("link")
    link.add_argument("source", choices=("signal",))
    setup = commands.add_parser("setup")
    setup.add_argument("--config")
    setup.add_argument("--model", choices=("small", "large"), default="small")
    commands.add_parser("daemon")
    args, remaining = parser.parse_known_args(argv)
    env = os.environ if env is None else env
    settings, runtime_env = _settings_env(env)
    if args.command == "capture":
        if args.source == "signal":
            return signal_cli.main(remaining, runtime_env)
        # Delegate to the daemon's supervisor so this path cannot drift from it.
        # Running the bridge here through the pty wrapper with capture_output=True
        # reproduced two bugs the daemon already fixed: the pty makes the bridge
        # start its interactive REPL and exit on EOF, and capture_output buffers a
        # months-long process's output in memory.
        from daemon import ChildProcesses, _run_whatsapp_capture

        try:
            _run_whatsapp_capture(settings, ChildProcesses())
        except RuntimeError as exc:
            print(exc, file=sys.stderr)
            return 1
        return 0
    if args.command == "derive":
        forwarded = ["--source", args.source] + (["--rebuild"] if args.rebuild else []) + (["--dry-run"] if args.dry_run else []) + remaining
        derive_cli.main(forwarded, runtime_env)
        return 0
    if args.command == "transcribe":
        transcribe_cli.main(["--source", args.source] + remaining, runtime_env)
        return 0
    if args.command == "describe":
        describe_cli.main(["--source", args.source] + remaining, runtime_env)
        return 0
    if args.command == "index":
        return index_cli.main(remaining, runtime_env)
    if args.command == "heartbeat":
        return heartbeat_cli.check(args.source, runtime_env)
    if args.command == "link":
        from link import main as link_main
        return link_main([args.source] + remaining, runtime_env)
    if args.command == "setup":
        from provision import main as setup_main
        forwarded = (["--config", args.config] if args.config else []) + ["--model", args.model] + remaining
        return setup_main(forwarded, runtime_env)
    from daemon import main as daemon_main
    return daemon_main(remaining, runtime_env)
