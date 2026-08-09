import sqlite3
import pytest
from sources.signal import parser, spool, store
from sources.signal.tests.conftest import DM_UUID, GROUP_ID, OWN_UUID, envelope


def rows(db):
    conn = sqlite3.connect(db)
    got = conn.execute("SELECT id, chat_jid, sender, content, timestamp, is_from_me, media_type, filename FROM messages ORDER BY timestamp").fetchall()
    conn.close()
    return got


def test_parse_fixture_shapes_and_identity(lines, now, tmp_path):
    path, _ = spool.append_fsynced(tmp_path, lines, now)
    db = tmp_path / "messages.db"
    result = parser.replay(path, db, contacts={DM_UUID: "Ada Contact"}, groups={GROUP_ID: "Original group"})
    got = rows(db)
    assert result.parsed == 10
    assert got[0][1] == f"{DM_UUID}@signal"
    assert got[1][1] == f"{GROUP_ID}@group.signal"
    assert got[2][6:] == ("audio", "voice.m4a")
    assert "signal reaction" in got[3][3]
    assert "signal edit" in got[4][3]
    assert "signal remote-delete" in got[5][3]
    assert got[6][2] == "99999999-0000-4000-8000-999999999999"
    assert got[8][6:] == ("document", "brief.pdf")
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT name FROM chats WHERE jid=?", (f"{GROUP_ID}@group.signal",)).fetchone()[0] == "Renamed group"
    assert conn.execute("SELECT name FROM chats WHERE jid=?", ("99999999-0000-4000-8000-999999999999@signal",)).fetchone()[0] == "99999999"
    conn.close()


def test_outbound_sync_shares_the_chat_and_records_self_as_sender(lines, now, tmp_path):
    """The inbound DM and the outbound reply must land in ONE chat, keyed by the other
    party -- not split across the correspondent's UUID and our own."""
    path, _ = spool.append_fsynced(tmp_path, lines, now)
    db = tmp_path / "messages.db"
    parser.replay(path, db, contacts={DM_UUID: "Ada Contact"}, groups={GROUP_ID: "Original group"})
    conn = sqlite3.connect(db)
    outbound = conn.execute(
        "SELECT chat_jid, sender, is_from_me FROM messages WHERE content='my reply'").fetchone()
    inbound = conn.execute(
        "SELECT chat_jid FROM messages WHERE content='direct note'").fetchone()
    assert outbound == (f"{DM_UUID}@signal", OWN_UUID, 1)
    assert outbound[0] == inbound[0]
    # No phantom self-DM chat is minted for our own account.
    assert conn.execute("SELECT 1 FROM chats WHERE jid=?", (f"{OWN_UUID}@signal",)).fetchone() is None
    conn.close()


def test_replay_is_idempotent(lines, now, tmp_path):
    path, _ = spool.append_fsynced(tmp_path, lines, now)
    db = tmp_path / "messages.db"
    parser.replay(path, db, contacts={}, groups={})
    parser.replay(path, db, contacts={}, groups={})
    assert len(rows(db)) == 10


def test_missing_attachment_keeps_message_with_empty_filename(lines, now, tmp_path):
    path, _ = spool.append_fsynced(tmp_path, lines, now)
    db = tmp_path / "messages.db"
    parser.replay(path, db, contacts={}, groups={}, media_root=tmp_path / "media", signal_data=tmp_path / "signal-cli-data")
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT filename FROM messages WHERE content='file attached'").fetchone()[0] == ""
    conn.close()


def test_parser_crash_leaves_fsynced_spool_for_safe_retry(lines, now, tmp_path):
    path, _ = spool.append_fsynced(tmp_path, lines, now)
    db = tmp_path / "messages.db"
    with pytest.raises(RuntimeError):
        parser.replay(path, db, contacts={}, groups={}, fail_after=3)
    assert len(path.read_text().splitlines()) == len(lines)
    parser.replay(path, db, contacts={}, groups={})
    assert len(rows(db)) == len(lines)


def test_image_attachment_classifies_by_content_type_or_filename(tmp_path):
    assert parser._attachment(
        {"attachments": [{"storedFilename": "fixture.bin", "contentType": "image/png"}]}, tmp_path
    )[:2] == ("image", "fixture.bin")
    assert parser._attachment(
        {"attachments": [{"storedFilename": "fixture.HEIC", "contentType": "application/octet-stream"}]}, tmp_path
    )[:2] == ("image", "fixture.HEIC")


def test_replay_does_not_correct_an_existing_row_when_classification_changes(now, tmp_path):
    original = parser._attachment
    path, _ = spool.append_fsynced(
        tmp_path,
        [envelope(dataMessage={"timestamp": 1785135600000, "attachments": [{"storedFilename": "fixture.png", "contentType": "image/png"}]})],
        now,
    )
    db = tmp_path / "messages.db"
    parser._attachment = lambda data, signal_data: ("document", "fixture.png", None)
    try:
        parser.replay(path, db, contacts={}, groups={})
    finally:
        parser._attachment = original
    parser.replay(path, db, contacts={}, groups={})
    assert sqlite3.connect(db).execute("SELECT media_type FROM messages").fetchone() == ("document",)