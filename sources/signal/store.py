"""SQLite contract for Signal's replayable parsed projection."""
import json
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
    jid TEXT PRIMARY KEY,
    name TEXT
);
CREATE TABLE IF NOT EXISTS messages (
    id TEXT,
    chat_jid TEXT,
    sender TEXT,
    content TEXT,
    timestamp TEXT,
    is_from_me BOOLEAN,
    media_type TEXT,
    filename TEXT,
    PRIMARY KEY (id, chat_jid)
);
"""


def connect(path: Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


def load_state(path: Path) -> dict:
    path = Path(path)
    if not path.exists():
        return {"spool_offsets": {}, "last_success_utc": None}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(path: Path, state: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def mark_success(state: dict, spool_file: Path, offset: int, now: datetime) -> dict:
    """Return the state to atomically persist after the parser transaction commits."""
    next_state = dict(state)
    offsets = dict(state.get("spool_offsets", {}))
    offsets[str(Path(spool_file))] = offset
    next_state["spool_offsets"] = offsets
    next_state["last_success_utc"] = now.astimezone(timezone.utc).isoformat()
    return next_state