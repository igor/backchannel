import sqlite3
from pathlib import Path
import pytest

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

CHATS = [
    ("120363100000000001@g.us", "Sample Group 🎲"),
    ("447700900101@s.whatsapp.net", "Anna Beispiel"),
    ("12025550101@s.whatsapp.net", "12025550101"),       # name is a phone number
    ("447700900123@s.whatsapp.net", "Chris Muster"),      # collides with the next
    ("447700900102@s.whatsapp.net", "Chris Muster"),      # same name, different number
    ("120363100000000002@newsletter", "Some Channel"),    # skipped type
]

# (id, chat_jid, sender, content, timestamp, is_from_me, media_type, filename)
MESSAGES = [
    ("G1", "120363100000000001@g.us", "12025550101", "Intertwined for sure",
     "2026-06-15 09:10:00+02:00", 0, "", ""),
    ("G2", "120363100000000001@g.us", "447700900110", "good thinking",
     "2026-06-15 09:11:00+02:00", 1, "", ""),
    ("G3", "120363100000000001@g.us", "12025550101", "",
     "2026-06-15 09:12:00+02:00", 0, "image", ""),
    ("G4", "120363100000000001@g.us", "447700900110", "",
     "2026-06-15 09:13:00+02:00", 1, "audio", "audio_20260615_091300_AB.ogg"),
    ("G5", "120363100000000001@g.us", "12025550101", "next day note",
     "2026-06-16 08:00:00+02:00", 0, "", ""),
    ("D1", "447700900101@s.whatsapp.net", "447700900101", "see https://example.com/x",
     "2026-06-15 10:00:00+02:00", 0, "", ""),
    ("D2", "447700900101@s.whatsapp.net", "447700900110", "danke",
     "2026-06-15 10:01:00+02:00", 1, "", ""),
    ("D3", "12025550101@s.whatsapp.net", "12025550101", "Vielen Dank",
     "2026-06-15 11:00:00+02:00", 0, "", ""),
    ("H1", "447700900101@s.whatsapp.net", "447700900101", "bin gleich online :)",
     "2013-05-01 15:00:45+02:00", 0, "", ""),       # real 2013 history -> KEEP
    ("Z1", "447700900101@s.whatsapp.net", "447700900101", "garbage",
     "2008-01-01 00:00:00+01:00", 0, "", ""),       # pre-2009 -> FLOORED
    ("N1", "120363100000000002@newsletter", "120363100000000002", "channel post",
     "2026-06-15 12:00:00+02:00", 0, "", ""),       # newsletter -> SKIPPED
    ("C1", "447700900123@s.whatsapp.net", "447700900123", "hi from uk daniel",
     "2026-06-15 13:00:00+02:00", 0, "", ""),       # collision pair -> both KEPT
    ("C2", "447700900102@s.whatsapp.net", "447700900102", "hi from at daniel",
     "2026-06-15 13:05:00+02:00", 0, "", ""),
]


@pytest.fixture
def store_db(tmp_path) -> Path:
    db = tmp_path / "messages.db"
    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA)
    conn.executemany("INSERT INTO chats (jid, name, last_message_time) VALUES (?,?,?)",
                     [(j, n, "2026-06-16 08:00:00+02:00") for j, n in CHATS])
    conn.executemany(
        "INSERT INTO messages (id, chat_jid, sender, content, timestamp, is_from_me, media_type, filename) "
        "VALUES (?,?,?,?,?,?,?,?)", MESSAGES)
    conn.commit()
    conn.close()
    return db


# whatsmeow session store (whatsapp.db) — minimal shape for name resolution.
# Sender 12025550101 resolves DIRECTLY (their_jid @s.whatsapp.net).
# Sender 447700900110 resolves ONLY via lid_map -> @lid (the load-bearing path).
CONTACTS_SCHEMA = """
CREATE TABLE whatsmeow_contacts (
    our_jid TEXT, their_jid TEXT, first_name TEXT, full_name TEXT,
    push_name TEXT, business_name TEXT, redacted_phone TEXT,
    PRIMARY KEY (our_jid, their_jid)
);
CREATE TABLE whatsmeow_lid_map (lid TEXT PRIMARY KEY, pn TEXT UNIQUE NOT NULL);
"""
OUR = "me@s.whatsapp.net"
CONTACTS = [
    # direct phone-keyed: full_name present
    (OUR, "12025550101@s.whatsapp.net", "Joe", "Joe Group", "joey", "", ""),
    # lid-keyed: reached only through lid_map; push_name only (no full_name)
    (OUR, "888777@lid", "", "", "Example Contact", "", ""),
    # a contact with neither name -> must NOT resolve
    (OUR, "49000@s.whatsapp.net", "", "  ", "", "", ""),
]
LID_MAP = [
    ("888777", "447700900110"),   # lid 888777 <-> phone 447700900110
]


@pytest.fixture
def contacts_db(tmp_path) -> Path:
    db = tmp_path / "whatsapp.db"
    conn = sqlite3.connect(db)
    conn.executescript(CONTACTS_SCHEMA)
    conn.executemany(
        "INSERT INTO whatsmeow_contacts "
        "(our_jid, their_jid, first_name, full_name, push_name, business_name, redacted_phone) "
        "VALUES (?,?,?,?,?,?,?)", CONTACTS)
    conn.executemany("INSERT INTO whatsmeow_lid_map (lid, pn) VALUES (?,?)", LID_MAP)
    conn.commit()
    conn.close()
    return db


# --- Signal fixtures ---

SIG_DM = "11111111-2222-4333-8444-555555555555@signal"
SIG_GROUP = "R3JvdXAtMDE=@group.signal"


@pytest.fixture
def signal_store_db(tmp_path) -> Path:
    db = tmp_path / "messages.db"
    conn = sqlite3.connect(db)
    conn.executescript("CREATE TABLE chats (jid TEXT PRIMARY KEY,name TEXT); CREATE TABLE messages (id TEXT,chat_jid TEXT,sender TEXT,content TEXT,timestamp TEXT,is_from_me BOOLEAN,media_type TEXT,filename TEXT,PRIMARY KEY(id,chat_jid));")
    conn.executemany("INSERT INTO chats VALUES (?,?)", [(SIG_DM, "Ada Contact"), (SIG_GROUP, "Research Group"), ("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee@signal", "Bea Profile"), ("22222222-2222-4222-8222-222222222222@signal", "Ada Contact")])
    conn.executemany("INSERT INTO messages VALUES (?,?,?,?,?,?,?,?)", [("d1", SIG_DM, SIG_DM.split("@", 1)[0], "see https://example.test/x", "2026-07-27 09:00:00+02:00", 0, "", ""), ("g1", SIG_GROUP, "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee", "hello", "2026-07-27 09:01:00+02:00", 0, "", ""), ("g2", SIG_GROUP, "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee", "", "2026-07-27 09:02:00+02:00", 0, "audio", "voice.m4a")])
    conn.commit()
    conn.close()
    return db
