#!/usr/bin/env python3
"""Runnable demo of the Backchannel derive pipeline.

No WhatsApp or Signal account is linked. This script builds a small,
fabricated WhatsApp store on disk, points the real derive pipeline at it,
and prints the resulting Markdown. It shows what the corpus looks like
without requiring the reader to link a real account first.

All names, phone numbers, and group IDs below are invented. Phone numbers
use the same reserved test-number pattern the project's own test fixtures
use (derive/tests/conftest.py); group JIDs are fabricated in the same
120363100000000XXX@g.us range WhatsApp itself uses for group IDs.

Run from the repo root:

    .venv/bin/python demo/run_demo.py
"""
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from derive import cli  # noqa: E402  (import after sys.path setup)

SCHEMA = """
CREATE TABLE chats (
    jid TEXT PRIMARY KEY, name TEXT, last_message_time TIMESTAMP,
    ephemeral_expiration INTEGER NOT NULL DEFAULT 0,
    ephemeral_setting_timestamp INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE messages (
    id TEXT, chat_jid TEXT, sender TEXT, content TEXT, timestamp TIMESTAMP,
    is_from_me BOOLEAN, media_type TEXT, filename TEXT, url TEXT,
    media_key BLOB, file_sha256 BLOB, file_enc_sha256 BLOB, file_length INTEGER,
    PRIMARY KEY (id, chat_jid), FOREIGN KEY (chat_jid) REFERENCES chats(jid)
);
"""

# Fabricated chats: one group, two direct messages. JIDs and numbers below
# do not correspond to any real WhatsApp account.
GROUP_JID = "120363100000099001@g.us"
DM1_JID = "447700900105@s.whatsapp.net"   # "Ada Lovelace"
DM2_JID = "12025550199@s.whatsapp.net"    # "Grace Hopper"

CHATS = [
    (GROUP_JID, "Weekend Hikers"),
    (DM1_JID, "Ada Lovelace"),
    (DM2_JID, "Grace Hopper"),
]

# (id, chat_jid, sender, content, timestamp, is_from_me, media_type, filename)
MESSAGES = [
    ("G1", GROUP_JID, "447700900105", "Anyone up for a hike Saturday?",
     "2026-01-10 09:00:00+01:00", 0, "", ""),
    ("G2", GROUP_JID, "", "Count me in", "2026-01-10 09:02:00+01:00", 1, "", ""),
    ("G3", GROUP_JID, "12025550199", "", "2026-01-10 09:05:00+01:00", 0, "image", ""),
    ("G4", GROUP_JID, "", "", "2026-01-10 09:07:00+01:00", 1, "audio",
     "voice_20260110_090700.ogg"),
    ("D1", DM1_JID, "447700900105", "See you at the trailhead",
     "2026-01-10 18:00:00+01:00", 0, "", ""),
    ("D2", DM1_JID, "", "Sounds good", "2026-01-10 18:01:00+01:00", 1, "", ""),
    ("D3", DM2_JID, "12025550199", "Thanks for organizing!",
     "2026-01-11 08:00:00+01:00", 0, "", ""),
    ("D4", DM2_JID, "", "Anytime", "2026-01-11 08:05:00+01:00", 1, "", ""),
]


def build_fake_store(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.executemany(
            "INSERT INTO chats (jid, name, last_message_time) VALUES (?,?,?)",
            [(jid, name, "2026-01-11 08:05:00+01:00") for jid, name in CHATS],
        )
        conn.executemany(
            "INSERT INTO messages "
            "(id, chat_jid, sender, content, timestamp, is_from_me, media_type, filename) "
            "VALUES (?,?,?,?,?,?,?,?)",
            MESSAGES,
        )
        conn.commit()
    finally:
        conn.close()


def main() -> int:
    tmp_dir = Path(tempfile.mkdtemp(prefix="backchannel-demo-"))
    try:
        store_dir = tmp_dir / "store"
        store_dir.mkdir()
        store_db = store_dir / "messages.db"
        build_fake_store(store_db)

        corpus_root = tmp_dir / "corpus"
        work_root = tmp_dir / "work"

        env = {
            "BC_WHATSAPP_STORE": str(store_db),
            "BC_CORPUS_ROOT": str(corpus_root),
            "BC_DERIVE_WORK": str(work_root),
        }

        written = cli.main(["--source", "whatsapp", "--rebuild"], env=env)

        if not written:
            print("demo: derive produced no Markdown files", file=sys.stderr)
            return 1

        md_files = sorted((corpus_root / "whatsapp").rglob("*.md"))
        if not md_files:
            print("demo: derive reported files written but none exist on disk", file=sys.stderr)
            return 1

        for path in md_files:
            rel = path.relative_to(corpus_root)
            print(f"===== {rel} =====")
            print(path.read_text(encoding="utf-8"))

        print(f"demo: {written} day-file(s) derived from a fabricated store", file=sys.stderr)
        return 0
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
