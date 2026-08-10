import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from derive import store, wacli


WACLI_SCHEMA = """
CREATE TABLE chats (
    jid TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT, last_message_ts INTEGER,
    archived INTEGER NOT NULL DEFAULT 0, pinned INTEGER NOT NULL DEFAULT 0,
    muted_until INTEGER NOT NULL DEFAULT 0, unread INTEGER NOT NULL DEFAULT 0,
    unread_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE contacts (
    jid TEXT PRIMARY KEY, phone TEXT, push_name TEXT, full_name TEXT, first_name TEXT,
    business_name TEXT, system_name TEXT, updated_at INTEGER NOT NULL
);
CREATE TABLE messages (
    rowid INTEGER PRIMARY KEY AUTOINCREMENT, chat_jid TEXT NOT NULL, chat_name TEXT,
    msg_id TEXT NOT NULL, sender_jid TEXT, sender_name TEXT, ts INTEGER NOT NULL,
    from_me INTEGER NOT NULL, text TEXT, display_text TEXT, quoted_msg_id TEXT,
    quoted_sender_jid TEXT, is_forwarded INTEGER NOT NULL DEFAULT 0,
    forwarding_score INTEGER NOT NULL DEFAULT 0, reaction_to_id TEXT, reaction_emoji TEXT,
    media_type TEXT, media_caption TEXT, filename TEXT, mime_type TEXT, direct_path TEXT,
    media_key BLOB, file_sha256 BLOB, file_enc_sha256 BLOB, file_length INTEGER,
    local_path TEXT, downloaded_at INTEGER, media_unavailable_at INTEGER,
    revoked INTEGER NOT NULL DEFAULT 0, deleted_for_me INTEGER NOT NULL DEFAULT 0,
    deleted_at INTEGER, deletion_reason TEXT, payload_purged_at INTEGER,
    edited INTEGER NOT NULL DEFAULT 0, edited_ts INTEGER NOT NULL DEFAULT 0, buttons TEXT,
    UNIQUE(chat_jid, msg_id)
);
"""


def _seed(store_dir) -> sqlite3.Connection:
    db = Path(store_dir) / "wacli.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    conn.executescript(WACLI_SCHEMA)
    conn.execute("INSERT INTO chats (jid, kind, name, last_message_ts) VALUES (?,?,?,?)",
                 ("447700900107@s.whatsapp.net", "dm", "Fixture Contact", 1752400000))
    conn.execute("INSERT INTO contacts (jid, phone, push_name, full_name, updated_at) VALUES (?,?,?,?,?)",
                 ("447700900107@s.whatsapp.net", "447700900107", "fixi", "Fixture Contact", 1752400000))
    return conn


def _msg(conn, msg_id, sender_jid="447700900107@s.whatsapp.net", text="hello", ts=1752400000,
         from_me=0, media_type="", filename="", local_path=None, payload_purged_at=None):
    conn.execute(
        "INSERT INTO messages (chat_jid, msg_id, sender_jid, text, ts, from_me, media_type, "
        "filename, local_path, payload_purged_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("447700900107@s.whatsapp.net", msg_id, sender_jid, text, ts, from_me,
         media_type, filename, local_path, payload_purged_at))


def test_project_maps_columns_and_converts_ts_to_local_aware_iso(tmp_path):
    conn = _seed(tmp_path / "store")
    _msg(conn, "M1")
    conn.commit(); conn.close()

    out = tmp_path / "snapshot.db"
    wacli.project(tmp_path / "store", out)
    snap = store.connect_ro(out)
    row = snap.execute("SELECT id, chat_jid, sender, content, timestamp, is_from_me FROM messages").fetchone()
    snap.close()
    assert row[0] == "M1"
    assert row[1] == "447700900107@s.whatsapp.net"
    assert row[2] == "447700900107"          # bare phone, host stripped
    assert row[3] == "hello"
    assert row[5] == 0
    assert store.parse_ts(row[4]) == datetime.fromtimestamp(1752400000, tz=timezone.utc).astimezone()


def test_project_strips_sender_jid_host_for_group_messages(tmp_path):
    conn = _seed(tmp_path / "store")
    conn.execute(
        "INSERT INTO messages (chat_jid, msg_id, sender_jid, text, ts, from_me, media_type, filename, local_path) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        ("120363000000000001@g.us", "G1", "447700900106@s.whatsapp.net", "group hi", 1752400000, 0, "", "", None))
    conn.commit(); conn.close()
    out = tmp_path / "snapshot.db"
    wacli.project(tmp_path / "store", out)
    snap = store.connect_ro(out)
    sender = snap.execute("SELECT sender FROM messages").fetchone()[0]
    snap.close()
    assert sender == "447700900106"


def test_project_carries_local_path_into_filename_and_falls_back(tmp_path):
    conn = _seed(tmp_path / "store")
    _msg(conn, "P1", text="", media_type="image", filename="photo.jpg",
         local_path="/abs/store/media/x/P1/image/message-P1.jpg")
    _msg(conn, "P2", text="", media_type="image", filename="notyet.jpg", local_path=None)
    conn.commit(); conn.close()
    out = tmp_path / "snapshot.db"
    wacli.project(tmp_path / "store", out)
    snap = store.connect_ro(out)
    fnames = dict(snap.execute("SELECT id, filename FROM messages"))
    snap.close()
    assert fnames["P1"] == "/abs/store/media/x/P1/image/message-P1.jpg"
    assert fnames["P2"] == "notyet.jpg"


def test_project_skips_only_payload_purged_rows(tmp_path):
    conn = _seed(tmp_path / "store")
    base = ("INSERT INTO messages (chat_jid, msg_id, sender_jid, text, ts, from_me, media_type, "
            "filename, local_path, revoked, deleted_for_me, payload_purged_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)")
    conn.execute(base, ("447700900107@s.whatsapp.net", "K1", "447700900107@s.whatsapp.net",
                        "kept history", 1752400000, 0, "", "", None, 1, 0, None))   # revoked, not purged -> kept
    conn.execute(base, ("447700900107@s.whatsapp.net", "D1", "447700900107@s.whatsapp.net",
                        "gone", 1752400000, 0, "", "", None, 0, 1, 1752400100))     # purged -> skipped
    conn.commit(); conn.close()
    out = tmp_path / "snapshot.db"
    wacli.project(tmp_path / "store", out)
    snap = store.connect_ro(out)
    ids = [r[0] for r in snap.execute("SELECT id FROM messages")]
    snap.close()
    assert "K1" in ids
    assert "D1" not in ids


def test_project_populates_contacts_and_creates_empty_lid_map(tmp_path):
    conn = _seed(tmp_path / "store")
    _msg(conn, "M1")
    conn.commit(); conn.close()
    out = tmp_path / "snapshot.db"
    wacli.project(tmp_path / "store", out)
    assert store.load_sender_names(out) == {"447700900107": "Fixture Contact"}
    snap = store.connect_ro(out)
    assert snap.execute("SELECT COUNT(*) FROM whatsmeow_lid_map").fetchone()[0] == 0
    snap.close()


def test_project_for_derive_marks_all_days_dirty_on_first_run(tmp_path):
    conn = _seed(tmp_path / "store")
    _msg(conn, "M1")
    conn.commit(); conn.close()
    out = tmp_path / "snapshot.db"
    state = tmp_path / "state.json"
    dirty, max_rowid, anchor = wacli.project_for_derive(tmp_path / "store", out, state, rebuild=False)
    assert max_rowid == 1
    assert anchor and len(anchor) == 64          # sha256 identity fingerprint
    expected_day = datetime.fromtimestamp(1752400000, tz=timezone.utc).astimezone().date()
    assert ("447700900107@s.whatsapp.net", expected_day) in dirty


def test_project_for_derive_advances_rowid_cursor_between_runs(tmp_path):
    conn = _seed(tmp_path / "store")
    _msg(conn, "M1", text="old")
    conn.commit(); conn.close()
    out = tmp_path / "snapshot.db"
    state = tmp_path / "state.json"

    dirty1, max1, anchor1 = wacli.project_for_derive(tmp_path / "store", out, state, rebuild=False)
    assert dirty1                                       # first run derives everything
    store.save_watermark(state, datetime.fromtimestamp(1752400000, tz=timezone.utc), wacli_rowid=max1,
                         wacli_anchor=anchor1)

    dirty2, max2, _ = wacli.project_for_derive(tmp_path / "store", out, state, rebuild=False)
    assert dirty2 == []                                 # cursor covers the only row
    assert max2 == max1


def test_recreated_wacli_db_resets_the_cursor(tmp_path):
    # Re-linking recreates wacli.db and restarts rowids; a stale cursor must trigger a
    # full re-derive, never a silent skip of rows at or below it.
    conn = _seed(tmp_path / "store")
    _msg(conn, "M1", text="old")
    conn.commit(); conn.close()
    out = tmp_path / "snapshot.db"
    state = tmp_path / "state.json"
    dirty1, max1, anchor1 = wacli.project_for_derive(tmp_path / "store", out, state, rebuild=False)
    store.save_watermark(state, datetime.fromtimestamp(1752400000, tz=timezone.utc), wacli_rowid=max1,
                         wacli_anchor=anchor1)

    (tmp_path / "store" / "wacli.db").unlink()
    conn = _seed(tmp_path / "store")
    _msg(conn, "M9", text="fresh history")            # same rowid 1, different message
    conn.commit(); conn.close()

    dirty2, max2, anchor2 = wacli.project_for_derive(tmp_path / "store", out, state, rebuild=False)
    assert dirty2                                      # anchor mismatch -> cursor reset
    assert max2 == 1
    assert anchor2 and anchor2 != anchor1        # new store, new fingerprint


def test_backend_vocabulary_is_validated():
    import config, pytest
    assert config.resolve_backend("  WaCli  ") == "wacli"
    assert config.resolve_backend("bridge") == "bridge"
    with pytest.raises(ValueError):
        config.resolve_backend("waclii")
    with pytest.raises(ValueError):
        config.resolve_backend("   ")


def test_recreated_db_with_identical_cursor_row_still_resets(tmp_path):
    # The collision the single-row anchor missed: the recreated store holds the SAME
    # message at the cursor rowid, but an earlier row differs. The prefix fingerprint
    # must catch it and re-derive everything.
    conn = _seed(tmp_path / "store")
    _msg(conn, "M1", text="old first")
    _msg(conn, "M2", text="cursor row")
    conn.commit(); conn.close()
    out = tmp_path / "snapshot.db"
    state = tmp_path / "state.json"
    dirty1, max1, fp1 = wacli.project_for_derive(tmp_path / "store", out, state, rebuild=False)
    assert max1 == 2
    store.save_watermark(state, datetime.fromtimestamp(1752400000, tz=timezone.utc),
                         wacli_rowid=max1, wacli_anchor=fp1)

    (tmp_path / "store" / "wacli.db").unlink()
    conn = _seed(tmp_path / "store")
    _msg(conn, "MX", text="different first row", ts=1752313600)   # rowid 1 differs, own day
    _msg(conn, "M2", text="cursor row")            # rowid 2 identical to the anchor row
    conn.commit(); conn.close()

    dirty2, max2, fp2 = wacli.project_for_derive(tmp_path / "store", out, state, rebuild=False)
    assert fp2 != fp1
    day_mx = datetime.fromtimestamp(1752313600, tz=timezone.utc).astimezone().date()
    day_m2 = datetime.fromtimestamp(1752400000, tz=timezone.utc).astimezone().date()
    # full re-derive: BOTH days are dirty, including the one at/below the stale cursor
    assert set(dirty2) == {("447700900107@s.whatsapp.net", day_mx),
                           ("447700900107@s.whatsapp.net", day_m2)}
