from datetime import datetime, timezone
from derive import store
from derive.model import Chat


def test_parse_ts_offset():
    dt = store.parse_ts("2026-06-15 15:26:28+02:00")
    assert dt.tzinfo is not None
    assert dt.utcoffset().total_seconds() == 7200
    assert dt.year == 2026


def test_parse_ts_z():
    dt = store.parse_ts("2026-06-15T13:26:28Z")
    assert dt.tzinfo is not None
    assert dt.utcoffset().total_seconds() == 0


def test_snapshot_connect_get_chats(store_db, tmp_path):
    snap = tmp_path / "snap.db"
    store.snapshot_db(store_db, snap)
    conn = store.connect_ro(snap)
    chats = store.get_chats(conn)
    assert isinstance(chats, dict)
    assert "447700900101@s.whatsapp.net" in chats
    assert chats["447700900101@s.whatsapp.net"] == Chat(
        jid="447700900101@s.whatsapp.net", name="Anna Beispiel")


def test_scan_affected_full(store_db):
    conn = store.connect_ro(store_db)
    affected, max_utc = store.scan_affected(conn, None)
    assert max_utc.year == 2026
    pairs = set(affected)
    assert ("120363100000000001@g.us", __import__("datetime").date(2026, 6, 15)) in pairs
    assert ("120363100000000001@g.us", __import__("datetime").date(2026, 6, 16)) in pairs
    assert ("447700900101@s.whatsapp.net", __import__("datetime").date(2013, 5, 1)) in pairs


def test_scan_affected_since(store_db):
    conn = store.connect_ro(store_db)
    since = store.parse_ts("2026-06-15 23:59:00+02:00").astimezone(__import__("datetime").timezone.utc)
    affected, max_utc = store.scan_affected(conn, since)
    assert affected == [("120363100000000001@g.us", __import__("datetime").date(2026, 6, 16))]


def test_messages_for_chat_day(store_db):
    conn = store.connect_ro(store_db)
    msgs = store.messages_for_chat_day(conn, "120363100000000001@g.us", __import__("datetime").date(2026, 6, 15))
    ids = [m.id for m in msgs]
    assert ids == ["G1", "G2", "G3", "G4"]
    assert msgs[-1].media_type == "audio"
    assert msgs[-1].filename == "audio_20260615_091300_AB.ogg"


def test_watermark_roundtrip(tmp_path):
    path = tmp_path / "state.json"
    assert store.load_watermark(path) is None
    dt = __import__("datetime").datetime(2026, 6, 15, 12, 0, 0, tzinfo=__import__("datetime").timezone.utc)
    store.save_watermark(path, dt)
    loaded = store.load_watermark(path)
    assert loaded == dt


# --- sender name resolution: _pick_names (pure) ---
# rows are (phone, full_name, push_name, pri); pri is ordering-only.

def test_pick_names_full_beats_push():
    assert store._pick_names([("49111", "Anna Beispiel", "anni", 0)]) == {"49111": "Anna Beispiel"}


def test_pick_names_push_fallback_when_no_full():
    assert store._pick_names([("49111", "", "anni", 0)]) == {"49111": "anni"}


def test_pick_names_skips_empty_and_whitespace():
    assert store._pick_names([("49111", "  ", "", 0), ("49222", None, None, 1)]) == {}


def test_pick_names_upgrades_push_then_full():
    rows = [("49111", "", "anni", 0), ("49111", "Anna Beispiel", "", 1)]
    assert store._pick_names(rows) == {"49111": "Anna Beispiel"}


def test_pick_names_keeps_full_when_push_arrives_later():
    rows = [("49111", "Anna Beispiel", "", 0), ("49111", "", "anni", 1)]
    assert store._pick_names(rows) == {"49111": "Anna Beispiel"}


def test_pick_names_two_fulls_first_wins():
    # pri-ordered: direct (@s.whatsapp.net) row arrives first and wins deterministically
    rows = [("49111", "Direct Name", "", 0), ("49111", "Lid Name", "", 1)]
    assert store._pick_names(rows) == {"49111": "Direct Name"}


# --- sender name resolution: load_sender_names (both join paths) ---

def test_load_sender_names_both_paths(contacts_db):
    names = store.load_sender_names(contacts_db)
    assert names["12025550101"] == "Joe Group"      # direct @s.whatsapp.net, full_name
    assert names["447700900110"] == "Example Contact"        # via lid_map -> @lid, push_name only
    assert "49000" not in names                       # contact with no name -> absent


def test_load_sender_names_missing_file_returns_empty(tmp_path):
    assert store.load_sender_names(tmp_path / "nope.db") == {}


def test_load_sender_names_missing_tables_returns_empty(tmp_path):
    db = tmp_path / "fresh.db"
    import sqlite3 as _sq
    _sq.connect(db).close()  # valid DB, but no whatsmeow_* tables
    assert store.load_sender_names(db) == {}


# --- sender name resolution: group_sender_coverage (message-weighted) ---

def test_group_sender_coverage_full(store_db):
    conn = store.connect_ro(store_db)
    # 12025550101 sends all 3 non-from-me group messages (G1,G3,G5)
    assert store.group_sender_coverage(conn, {"12025550101": "X"}) == 1.0


def test_group_sender_coverage_zero(store_db):
    conn = store.connect_ro(store_db)
    assert store.group_sender_coverage(conn, {}) == 0.0
    # 447700900110 appears in the group only as is_from_me=1 -> excluded from denominator
    assert store.group_sender_coverage(conn, {"447700900110": "Y"}) == 0.0


def test_group_sender_coverage_no_group_messages(tmp_path):
    import sqlite3 as _sq
    db = tmp_path / "m.db"
    c = _sq.connect(db)
    c.executescript("CREATE TABLE messages (id TEXT, chat_jid TEXT, sender TEXT, is_from_me BOOLEAN);")
    c.execute("INSERT INTO messages VALUES ('x','a@s.whatsapp.net','49','0')")  # DM, not a group
    c.commit(); c.close()
    conn = store.connect_ro(db)
    assert store.group_sender_coverage(conn, {}) == 1.0


def test_load_image_text_returns_nonempty_ok_rows_for_one_source(tmp_path):
    from describe import extracts

    db = tmp_path / "image_text.db"
    conn = extracts.connect(db)
    extracts.upsert(conn, "whatsapp", "fixture-inline", "fixture-chat", "inline text", 3, 0.9, True, "apple-vision", "ok", "now")
    extracts.upsert(conn, "whatsapp", "fixture-empty", "fixture-chat", "", 0, 0.0, False, "apple-vision", "empty", "now")
    extracts.upsert(conn, "signal", "fixture-inline", "fixture-chat", "other source", 3, 0.9, True, "apple-vision", "ok", "now")
    conn.close()
    assert store.load_image_text(db, "whatsapp") == {"fixture-inline": {"text": "inline text", "document_like": True}}


def test_load_image_text_returns_empty_when_sidecar_is_absent(tmp_path):
    assert store.load_image_text(tmp_path / "absent.db", "signal") == {}


def _make_transcripts_db(path, rows):
    import sqlite3 as _sq
    conn = _sq.connect(path)
    conn.executescript(
        "CREATE TABLE transcripts (source TEXT, message_id TEXT, transcribed_at TEXT, revision INTEGER)")
    conn.executemany("INSERT INTO transcripts VALUES (?,?,?,?)", rows)
    conn.commit()
    conn.close()


def test_scan_sidecar_dirty_does_not_rescan_rows_already_covered_by_the_watermark(store_db, tmp_path):
    # A transcription run stamps every row with one shared timestamp but a distinct,
    # monotonically increasing revision: G3 (revision 1) was already covered by the
    # watermark; G4 (revision 2, same run/timestamp) is a genuinely later write.
    conn = store.connect_ro(store_db)
    transcripts_db = tmp_path / "transcripts.db"
    _make_transcripts_db(transcripts_db, [
        ("whatsapp", "G3", "2026-06-20T10:00:00+00:00", 1),
        ("whatsapp", "G4", "2026-06-20T10:00:00+00:00", 2),
    ])
    affected, max_transcripts, max_image_text = store.scan_sidecar_dirty(
        conn, transcripts_db, tmp_path / "image_text.db", "whatsapp", 1, None)
    assert ("120363100000000001@g.us", __import__("datetime").date(2026, 6, 15)) in affected
    assert max_transcripts == 2
    assert max_image_text is None


def test_scan_sidecar_dirty_excludes_rows_at_or_below_the_watermark(store_db, tmp_path):
    # Once the watermark has moved past a revision, that batch must not be marked dirty
    # again on the next scan (would otherwise rewrite the same day forever).
    conn = store.connect_ro(store_db)
    transcripts_db = tmp_path / "transcripts.db"
    _make_transcripts_db(transcripts_db, [
        ("whatsapp", "G3", "2026-06-20T10:00:00+00:00", 1),
        ("whatsapp", "G4", "2026-06-20T10:00:00+00:00", 2),
    ])
    affected, max_transcripts, max_image_text = store.scan_sidecar_dirty(
        conn, transcripts_db, tmp_path / "image_text.db", "whatsapp", 2, None)
    assert affected == []
    assert max_transcripts == 2


def test_scan_sidecar_dirty_uses_separate_cursors_per_pipeline(store_db, tmp_path):
    # transcripts.db is far ahead of image_text.db; a lagging image_text row must not be
    # dropped just because a shared cursor would already have moved past its revision.
    conn = store.connect_ro(store_db)
    transcripts_db = tmp_path / "transcripts.db"
    _make_transcripts_db(transcripts_db, [
        ("whatsapp", "G5", "2026-06-20T12:00:00+00:00", 1),
    ])
    import sqlite3 as _sq
    image_text_db = tmp_path / "image_text.db"
    iconn = _sq.connect(image_text_db)
    iconn.executescript(
        "CREATE TABLE image_text (source TEXT, message_id TEXT, extracted_at TEXT, revision INTEGER)")
    iconn.execute("INSERT INTO image_text VALUES ('whatsapp','G3','2026-06-20T09:00:00+00:00',1)")
    iconn.commit(); iconn.close()

    affected, max_transcripts, max_image_text = store.scan_sidecar_dirty(
        conn, transcripts_db, image_text_db, "whatsapp", None, None)
    assert ("120363100000000001@g.us", __import__("datetime").date(2026, 6, 15)) in affected
    assert ("120363100000000001@g.us", __import__("datetime").date(2026, 6, 16)) in affected
    assert max_transcripts == 1
    assert max_image_text == 1


def test_media_path_absolute_filename_wins_over_media_root(tmp_path):
    # wacli projects an absolute local_path; it must resolve to itself regardless of media_root.
    import pathlib
    resolved = store.media_path(tmp_path / "media", "chat@x", "/abs/store/message-P1.jpg")
    assert resolved == pathlib.Path("/abs/store/message-P1.jpg")


def test_media_path_relative_filename_uses_the_bridge_convention(tmp_path):
    # The bridge stores a basename under <media_root>/<chat_jid>/<filename>.
    resolved = store.media_path(tmp_path / "media", "chat@x", "audio_1.ogg")
    assert resolved == tmp_path / "media" / "chat@x" / "audio_1.ogg"


def test_save_watermark_persists_the_wacli_rowid_cursor(tmp_path):
    import json
    path = tmp_path / "state.json"
    dt = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
    store.save_watermark(path, dt, wacli_rowid=42)
    raw = json.loads(path.read_text())
    assert raw["wacli_rowid_cursor"] == 42


def test_save_watermark_omits_cursor_when_none_so_bridge_path_is_unchanged(tmp_path):
    import json
    path = tmp_path / "state.json"
    dt = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
    store.save_watermark(path, dt)
    raw = json.loads(path.read_text())
    assert "wacli_rowid_cursor" not in raw

