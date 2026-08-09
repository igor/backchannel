from pathlib import Path

from derive import store as derive_store
from transcribe import store


def test_audio_messages_returns_only_audio_rows(messages_db, tmp_path):
    snap = tmp_path / "snap.db"
    derive_store.snapshot_db(messages_db, snap)
    conn = derive_store.connect_ro(snap)
    rows = store.audio_messages(conn)
    assert rows == [
        ("A1", "447700900108@s.whatsapp.net", "audio_1.ogg"),
        ("A2", "120363100000000001@g.us", "audio_2.ogg"),
        ("A3", "447700900108@s.whatsapp.net", "audio_missing.ogg"),
    ]
    # non-audio T1 is excluded
    ids = [r[0] for r in rows]
    assert "T1" not in ids


def test_audio_messages_handles_null_filename(messages_db, tmp_path):
    # add an audio row with NULL filename -> COALESCE to ''
    import sqlite3
    conn_w = sqlite3.connect(messages_db)
    conn_w.execute(
        "INSERT INTO messages (id, chat_jid, sender, content, timestamp, is_from_me, media_type, filename) "
        "VALUES ('A4', '447700900108@s.whatsapp.net', '', '', '2026-06-15 09:00:00+02:00', 0, 'audio', NULL)")
    conn_w.commit(); conn_w.close()

    snap = tmp_path / "snap2.db"
    derive_store.snapshot_db(messages_db, snap)
    conn = derive_store.connect_ro(snap)
    rows = store.audio_messages(conn)
    by_id = {r[0]: r for r in rows}
    assert by_id["A4"] == ("A4", "447700900108@s.whatsapp.net", "")
