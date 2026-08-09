"""Maintain the one shared Backchannel qmd collection."""
import argparse
import subprocess
from pathlib import Path


def _run(run, argv):
    return run(argv, text=True, capture_output=True)


def main(argv=None, env=None, run=subprocess.run) -> int:
    parser = argparse.ArgumentParser(prog="backchannel index")
    parser.parse_args(argv)
    env = {} if env is None else env
    qmd = env.get("BC_QMD_BIN") or env.get("QMD_BIN") or "qmd"
    root = Path(env.get("BC_CORPUS_ROOT") or "~/.local/share/backchannel/corpus").expanduser()
    if not root.is_dir():
        return 1
    listed = _run(run, [qmd, "collection", "list"])
    if listed.returncode:
        return 1
    if not any(line.startswith("backchannel") for line in listed.stdout.splitlines()):
        added = _run(run, [qmd, "collection", "add", str(root), "--name", "backchannel", "--pattern", "**/*.md"])
        if added.returncode:
            return 1
    for command in ([qmd, "update"], [qmd, "embed", "-f"]):
        if _run(run, command).returncode:
            return 1
    return 0
