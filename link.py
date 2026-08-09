"""Signal linked-device QR flow with no URI exposure through argv or durable files."""
import argparse
import os
import re
import subprocess
import tempfile
import threading
from pathlib import Path


URI = re.compile(r"(?:sgnl://linkdevice|tsdevice://)[^\s\"']+")


def extract_link_uri(text: str) -> str | None:
    match = URI.search(text)
    return match.group(0) if match else None


def _drain(stream) -> None:
    # signal-cli keeps logging after it prints the URI (initial sync, under a pty). Nothing
    # else reads the pipe between the URI and proc.wait(), so without this the child blocks
    # on a full pipe buffer and wait() never returns.
    try:
        for _ in stream:
            pass
    except Exception:
        pass


def main(argv=None, env=None, run=subprocess.run, pause=input, opener="open", popen_factory=subprocess.Popen) -> int:
    parser = argparse.ArgumentParser(prog="backchannel link")
    parser.add_argument("source", choices=("signal",))
    args = parser.parse_args(argv)
    env = {} if env is None else env
    signal_cli = env.get("BC_SIGNAL_CLI_BIN") or "signal-cli"
    # signal-cli link stays alive until the QR is scanned, so it must be started
    # with Popen and kept running while the QR is shown, not waited on up front.
    proc = popen_factory(
        ["script", "-q", "/dev/null", signal_cli, "link", "-n", "Backchannel"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    png = None
    try:
        uri = None
        for line in proc.stdout:
            uri = extract_link_uri(line)
            if uri:
                break
        if uri is None:
            return 1
        threading.Thread(target=_drain, args=(proc.stdout,), daemon=True).start()
        descriptor, png = tempfile.mkstemp(prefix="backchannel-link-", suffix=".png")
        os.close(descriptor)
        rendered = run(["qrencode", "-t", "PNG", "-o", png], input=uri + "\n", text=True, capture_output=True)
        if rendered.returncode:
            return 1
        if callable(opener):
            opener(png)
        else:
            run([opener, png], text=True, capture_output=True)
        pause("Scan the Signal QR code, then press Enter to delete it. ")
        return 0 if proc.wait() == 0 else 1
    finally:
        if png is not None:
            Path(png).unlink(missing_ok=True)
        if proc.poll() is None:
            proc.terminate()
            proc.wait()
