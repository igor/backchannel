import sqlite3
from pathlib import Path
import pytest

SCHEMA = """
CREATE TABLE chats (jid TEXT PRIMARY KEY, name TEXT, last_message_time TIMESTAMP);
CREATE TABLE messages (
    id TEXT, chat_jid TEXT, sender TEXT, content TEXT, timestamp TIMESTAMP,
    is_from_me BOOLEAN, media_type TEXT, filename TEXT, url TEXT,
    media_key BLOB, file_sha256 BLOB, file_enc_sha256 BLOB, file_length INTEGER,
    PRIMARY KEY (id, chat_jid)
);
"""
# (id, chat_jid, media_type, filename)
ROWS = [
    ("A1", "447700900108@s.whatsapp.net", "audio", "audio_1.ogg"),
    ("A2", "120363100000000001@g.us", "audio", "audio_2.ogg"),
    ("A3", "447700900108@s.whatsapp.net", "audio", "audio_missing.ogg"),
    ("T1", "447700900108@s.whatsapp.net", "", ""),   # non-audio, ignored
]


@pytest.fixture
def messages_db(tmp_path) -> Path:
    db = tmp_path / "messages.db"
    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA)
    conn.executemany(
        "INSERT INTO messages (id, chat_jid, sender, content, timestamp, is_from_me, media_type, filename) "
        "VALUES (?,?, '', '', '2026-06-15 09:00:00+02:00', 0, ?, ?)",
        ROWS)
    conn.commit(); conn.close()
    return db


@pytest.fixture
def signal_messages_db(tmp_path) -> Path:
    db = tmp_path / "messages.db"
    conn = sqlite3.connect(db)
    conn.executescript("CREATE TABLE messages (id TEXT,chat_jid TEXT,media_type TEXT,filename TEXT)")
    conn.executemany("INSERT INTO messages VALUES (?,?,?,?)", [("a1", "x@signal", "audio", "voice.m4a"), ("a2", "g@group.signal", "audio", "voice.aac"), ("d1", "x@signal", "document", "song.mp3")])
    conn.commit(); conn.close()
    return db
