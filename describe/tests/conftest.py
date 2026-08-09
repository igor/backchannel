import sqlite3
from pathlib import Path

import pytest


@pytest.fixture
def messages_db(tmp_path) -> Path:
    db = tmp_path / "messages.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        "CREATE TABLE messages ("
        "id TEXT, chat_jid TEXT, media_type TEXT, filename TEXT, "
        "PRIMARY KEY (id, chat_jid));"
    )
    conn.executemany(
        "INSERT INTO messages VALUES (?,?,?,?)",
        [
            ("image-document", "fixture-chat", "image", "document.png"),
            ("image-short", "fixture-chat", "image", "short.jpg"),
            ("image-missing", "fixture-chat", "image", "missing.webp"),
            ("audio-only", "fixture-chat", "audio", "voice.m4a"),
        ],
    )
    conn.commit()
    conn.close()
    return db
