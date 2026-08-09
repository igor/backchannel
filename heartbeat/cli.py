"""Check source-specific derive watermarks without a launchd shell wrapper."""
import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


SOURCES = ("whatsapp", "signal")


def _notify(message: str) -> None:
    subprocess.run(["osascript", "-e", f'display notification "{message}" with title "Backchannel"'], check=False, capture_output=True, text=True)


def check(source: str, env=None, now: datetime | None = None, notify=None) -> int:
    if source not in SOURCES:
        raise ValueError(f"backchannel heartbeat: unknown source {source!r}")
    env = os.environ if env is None else env
    root = Path(env.get("BC_CORPUS_ROOT") or "~/.local/share/backchannel/corpus").expanduser()
    state = root / ".derive" / source / "state.json"
    warning = root / f"WARNING-{source}.md"
    now = datetime.now(timezone.utc) if now is None else now.astimezone(timezone.utc)
    notify = _notify if notify is None else notify
    root.mkdir(parents=True, exist_ok=True)
    if not state.exists():
        warning.write_text(f"# Backchannel warning — no state file\n\n`{state}` does not exist.\n", encoding="utf-8")
        notify("no state file — derive never wrote since launch")
        return 0
    try:
        stamp = datetime.fromisoformat(json.loads(state.read_text(encoding="utf-8"))["watermark_utc"]).astimezone(timezone.utc)
    except Exception:
        warning.write_text(f"# Backchannel warning — state file unreadable\n\n`{state}` could not be parsed.\n", encoding="utf-8")
        notify("state file unreadable")
        return 0
    hours = (now - stamp).total_seconds() / 3600
    if hours > 24:
        warning.write_text(f"# Backchannel warning — no writes in {hours:.1f}h\n\ncapture stalled.\n", encoding="utf-8")
        notify(f"no writes in {hours:.1f}h — capture stalled")
    else:
        warning.unlink(missing_ok=True)
    return 0


def main(argv=None, env=None) -> int:
    parser = argparse.ArgumentParser(prog="backchannel heartbeat")
    parser.add_argument("--source", required=True, choices=SOURCES)
    args = parser.parse_args(argv)
    return check(args.source, env=env)
