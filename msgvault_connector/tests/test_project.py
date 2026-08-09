"""Projection tests: bridge store in, synthetic msgstore.db out."""
import sqlite3
from pathlib import Path

import pytest

from msgvault_connector.project import build

MESSAGES_SCHEMA = """
CREATE TABLE chats (jid TEXT PRIMARY KEY, name TEXT, last_message_time TIMESTAMP);
CREATE TABLE messages (
    id TEXT, chat_jid TEXT, sender TEXT, content TEXT, timestamp TIMESTAMP,
    is_from_me BOOLEAN, media_type TEXT, filename TEXT, url TEXT,
    media_key BLOB, file_sha256 BLOB, file_enc_sha256 BLOB, file_length INTEGER,
    PRIMARY KEY (id, chat_jid));
"""

CONTACTS_SCHEMA = """
CREATE TABLE whatsmeow_contacts (their_jid TEXT PRIMARY KEY, full_name TEXT, push_name TEXT);
CREATE TABLE whatsmeow_lid_map (lid TEXT PRIMARY KEY, pn TEXT UNIQUE NOT NULL);
"""

TRANSCRIPTS_SCHEMA = """
CREATE TABLE transcripts (message_id TEXT PRIMARY KEY, chat_jid TEXT, text TEXT,
    lang TEXT, model TEXT, status TEXT, transcribed_at TEXT);
"""

GROUP_JID = "120363100000000001@g.us"
DM_JID = "447700900103@s.whatsapp.net"
NEWS_JID = "120363100000000002@newsletter"
LID_JID = "6600000000001@lid"


@pytest.fixture
def sources(tmp_path):
    """(store_db, contacts_db, transcripts_db) with one row of every shape."""
    store_db = tmp_path / "messages.db"
    conn = sqlite3.connect(store_db)
    conn.executescript(MESSAGES_SCHEMA)
    conn.executemany(
        "INSERT INTO chats (jid, name, last_message_time) VALUES (?,?,?)",
        [
            (GROUP_JID, "Team Chat", "2026-06-15 15:26:28+02:00"),
            (DM_JID, "Ada Lovelace", "2026-06-15 10:00:00+02:00"),
            (NEWS_JID, "", "2026-06-14 09:00:00+02:00"),
            (LID_JID, "", "2026-06-13 09:00:00+02:00"),
            ("status@broadcast", "", "2026-06-12 09:00:00+02:00"),
        ],
    )
    rows = [
        # (id, chat_jid, sender, content, timestamp, from_me, media_type, filename, file_length)
        ("KEYTEXT", GROUP_JID, "447700900103", "hello there",
         "2026-06-15 15:26:28+02:00", 0, "", "", None),
        ("KEYIMAGE", GROUP_JID, "447700900112", "look at this",
         "2026-06-15 15:27:00+02:00", 0, "image", "image_1.jpg", 1234),
        ("KEYAUDIO", DM_JID, "447700900103", "",
         "2026-06-15 10:00:00+02:00", 0, "audio", "audio_1.ogg", 4321),
        ("KEYMINE", DM_JID, "447700900114", "mine",
         "2026-06-15 10:01:00+02:00", 1, "", "", None),
        ("KEYSTATUS", "status@broadcast", "447700900113", "a status",
         "2026-06-12 09:00:00+02:00", 0, "", "", None),
        ("KEYDUP", GROUP_JID, "447700900103", "first copy",
         "2026-06-15 15:28:00+02:00", 0, "", "", None),
        ("KEYDUP", DM_JID, "447700900103", "second copy",
         "2026-06-15 15:29:00+02:00", 0, "", "", None),
    ]
    conn.executemany(
        "INSERT INTO messages (id, chat_jid, sender, content, timestamp, is_from_me, "
        "media_type, filename, file_length) VALUES (?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()

    contacts_db = tmp_path / "whatsapp.db"
    conn = sqlite3.connect(contacts_db)
    conn.executescript(CONTACTS_SCHEMA)
    conn.execute("INSERT INTO whatsmeow_contacts VALUES (?,?,?)",
                 ("447700900103@s.whatsapp.net", "Ada Lovelace", "ada"))
    conn.execute("INSERT INTO whatsmeow_lid_map VALUES (?,?)",
                 ("6600000000001", "447700900104"))
    conn.commit()
    conn.close()

    transcripts_db = tmp_path / "transcripts.db"
    conn = sqlite3.connect(transcripts_db)
    conn.executescript(TRANSCRIPTS_SCHEMA)
    conn.execute("INSERT INTO transcripts VALUES (?,?,?,?,?,?,?)",
                 ("KEYAUDIO", DM_JID, "spoken words", "de", "m", "ok", "2026-06-15"))
    conn.commit()
    conn.close()

    return store_db, contacts_db, transcripts_db


@pytest.fixture
def projected(sources, tmp_path):
    """(counts, connection to the projected msgstore.db)."""
    store_db, contacts_db, transcripts_db = sources
    out_dir = tmp_path / "out"
    counts = build(store_db, out_dir, contacts_db=contacts_db,
                   transcripts_db=transcripts_db)
    conn = sqlite3.connect(out_dir / "msgstore.db")
    yield counts, conn, out_dir
    conn.close()


def test_reader_tables_exist(projected):
    """msgvault validates message/jid/chat and reads five optional tables."""
    _counts, conn, _out = projected
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"message", "jid", "chat", "message_media"} <= names
    assert {"message_quoted", "message_add_on", "message_add_on_reaction",
            "group_participants", "jid_map"} <= names
    for table in ("message_quoted", "message_add_on", "message_add_on_reaction",
                  "group_participants", "jid_map"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_journal_mode_is_wal(projected):
    """msgvault opens the file read-only AND asks for WAL; rollback mode fails."""
    _counts, conn, _out = projected
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_chats_group_type_and_skips(projected):
    """Groups and channels are group_type=1, DMs 0, status@broadcast is dropped."""
    counts, conn, _out = projected
    got = {raw: gt for raw, gt in conn.execute(
        "SELECT j.raw_string, c.group_type FROM chat c JOIN jid j ON c.jid_row_id = j._id")}
    assert got[GROUP_JID] == 1
    assert got[NEWS_JID] == 1
    assert got[DM_JID] == 0
    assert "status@broadcast" not in got
    # the @lid chat resolves through lid_map to a phone JID
    assert "447700900104@s.whatsapp.net" in got
    assert counts.chats == 4
    assert counts.skipped_chats == 1
    subject = conn.execute(
        "SELECT c.subject FROM chat c JOIN jid j ON c.jid_row_id = j._id "
        "WHERE j.raw_string = ?", (GROUP_JID,)).fetchone()[0]
    assert subject == "Team Chat"


def test_message_types_and_timestamp(projected):
    """media_type maps to WhatsApp ints; timestamps become offset-correct epoch ms."""
    _counts, conn, _out = projected
    types = dict(conn.execute("SELECT key_id, message_type FROM message"))
    assert types["KEYTEXT"] == 0
    assert types["KEYIMAGE"] == 1
    assert types["KEYAUDIO"] == 5
    assert "KEYSTATUS" not in types
    ts = conn.execute("SELECT timestamp FROM message WHERE key_id = 'KEYTEXT'").fetchone()[0]
    # 2026-06-15 15:26:28+02:00 == 2026-06-15 13:26:28Z
    assert ts == 1781529988000
    from_me = dict(conn.execute("SELECT key_id, from_me FROM message"))
    assert from_me["KEYMINE"] == 1
    assert from_me["KEYTEXT"] == 0


def test_transcript_injected_into_body(projected):
    """A voice note's transcript lands in text_data so msgvault indexes it."""
    counts, conn, _out = projected
    text = conn.execute(
        "SELECT text_data FROM message WHERE key_id = 'KEYAUDIO'").fetchone()[0]
    assert text == "🎙 spoken words"
    assert counts.transcripts == 1


def test_media_path_and_metadata(projected):
    """file_path is <chat_jid>/<filename>, resolved against --media-dir."""
    counts, conn, _out = projected
    row = conn.execute(
        "SELECT mm.file_path, mm.mime_type, mm.file_size FROM message_media mm "
        "JOIN message m ON m._id = mm.message_row_id WHERE m.key_id = 'KEYIMAGE'").fetchone()
    assert row[0] == f"{GROUP_JID}/image_1.jpg"
    assert row[1] == "image/jpeg"
    assert row[2] == 1234
    assert counts.media == 2


def test_collision_suffix_and_vcf(projected):
    """A key_id under two chats keeps both rows; contacts go out as E.164 vCards."""
    counts, conn, out_dir = projected
    keys = {r[0] for r in conn.execute("SELECT key_id FROM message")}
    assert "KEYDUP" in keys
    assert f"KEYDUP-{DM_JID}" in keys
    assert counts.collisions == 1
    vcf = (out_dir / "contacts.vcf").read_text(encoding="utf-8")
    assert "FN:Ada Lovelace" in vcf
    assert "TEL:+447700900103" in vcf
    assert counts.contacts == 1
