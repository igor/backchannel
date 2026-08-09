"""Append complete signal-cli output lines before any JSON parsing occurs."""
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


def spool_path(root: Path, now: datetime) -> Path:
    """UTC daily spool path; callers inject `now` in tests."""
    return Path(root) / "spool" / f"{now.astimezone(timezone.utc).date().isoformat()}.jsonl"


def append_fsynced(root: Path, lines: Iterable[str], now: datetime) -> tuple[Path, int]:
    """Append original non-empty JSON lines and fsync once before returning."""
    path = spool_path(root, now)
    path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for line in lines:
            clean = line.rstrip("\r\n")
            if not clean:
                continue
            handle.write(clean + "\n")
            written += 1
        handle.flush()
        os.fsync(handle.fileno())
    return path, written


def read_lines(path: Path, offset: int = 0) -> list[tuple[int, str]]:
    """Return `(byte_offset, line)` records after `offset`, without parsing them."""
    out = []
    with Path(path).open("r", encoding="utf-8") as handle:
        handle.seek(offset)
        while True:
            position = handle.tell()
            line = handle.readline()
            if not line:
                break
            if line.strip():
                out.append((position, line.rstrip("\r\n")))
    return out