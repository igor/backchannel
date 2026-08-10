from pathlib import Path
from transcribe import cli, transcripts


def test_main_transcribes_existing_audio_and_marks_missing(messages_db, tmp_path):
    root = tmp_path / "corpus"
    work = tmp_path / "work"
    media = tmp_path / "media"
    # Create media files for A1 and A2; leave A3 missing
    (media / "447700900108@s.whatsapp.net").mkdir(parents=True)
    (media / "120363100000000001@g.us").mkdir(parents=True)
    (media / "447700900108@s.whatsapp.net" / "audio_1.ogg").touch()
    (media / "120363100000000001@g.us" / "audio_2.ogg").touch()

    env = {
        "BC_WHATSAPP_STORE": str(messages_db),
        "BC_CORPUS_ROOT": str(root),
        "BC_DERIVE_WORK": str(work),
        "BC_WHATSAPP_MEDIA": str(media),
    }
    fake = lambda p: ("hallo welt", "de")

    count = cli.main(["--source", "whatsapp"], env=env, transcribe_fn=fake)
    assert count == 2

    # Verify transcripts.db
    tconn = transcripts.connect(root / "transcripts.db")
    rows = {r[0]: r for r in tconn.execute(
        "SELECT message_id, status, text FROM transcripts WHERE source='whatsapp'").fetchall()}
    assert rows["A1"] == ("A1", "ok", "hallo welt")
    assert rows["A2"] == ("A2", "ok", "hallo welt")
    assert rows["A3"] == ("A3", "missing", "")

    # Second run: A1/A2 are done, nothing new
    count2 = cli.main(["--source", "whatsapp"], env=env, transcribe_fn=fake)
    assert count2 == 0


def test_main_marks_failed_on_transcribe_exception(messages_db, tmp_path):
    root = tmp_path / "corpus"
    work = tmp_path / "work"
    media = tmp_path / "media"
    (media / "447700900108@s.whatsapp.net").mkdir(parents=True)
    (media / "120363100000000001@g.us").mkdir(parents=True)
    (media / "447700900108@s.whatsapp.net" / "audio_1.ogg").touch()
    (media / "120363100000000001@g.us" / "audio_2.ogg").touch()

    env = {
        "BC_WHATSAPP_STORE": str(messages_db),
        "BC_CORPUS_ROOT": str(root),
        "BC_DERIVE_WORK": str(work),
        "BC_WHATSAPP_MEDIA": str(media),
    }
    calls = []
    def fake(p):
        calls.append(str(p))
        if len(calls) == 1:
            raise RuntimeError("boom")
        return ("hallo welt", "de")

    count = cli.main(["--source", "whatsapp"], env=env, transcribe_fn=fake)
    assert count == 1  # only A2 succeeded

    tconn = transcripts.connect(root / "transcripts.db")
    rows = {r[0]: r for r in tconn.execute(
        "SELECT message_id, status FROM transcripts WHERE source='whatsapp'").fetchall()}
    assert rows["A1"] == ("A1", "failed")
    assert rows["A2"] == ("A2", "ok")


def test_main_marks_empty_on_blank_transcript(messages_db, tmp_path):
    root = tmp_path / "corpus"
    work = tmp_path / "work"
    media = tmp_path / "media"
    (media / "447700900108@s.whatsapp.net").mkdir(parents=True)
    (media / "447700900108@s.whatsapp.net" / "audio_1.ogg").touch()

    env = {
        "BC_WHATSAPP_STORE": str(messages_db),
        "BC_CORPUS_ROOT": str(root),
        "BC_DERIVE_WORK": str(work),
        "BC_WHATSAPP_MEDIA": str(media),
    }
    fake = lambda p: ("", "auto")

    count = cli.main(["--source", "whatsapp"], env=env, transcribe_fn=fake)
    assert count == 0

    tconn = transcripts.connect(root / "transcripts.db")
    rows = {r[0]: r for r in tconn.execute(
        "SELECT message_id, status, text FROM transcripts WHERE source='whatsapp'").fetchall()}
    assert rows["A1"] == ("A1", "empty", "")


def test_transcribe_wacli_finds_audio_via_projected_local_path(tmp_path):
    import sqlite3
    store_dir = tmp_path / "wa"
    ogg = tmp_path / "media-cache" / "voice-M1.ogg"
    ogg.parent.mkdir(parents=True); ogg.touch()
    db = store_dir / "wacli.db"; db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    conn.executescript(
        "CREATE TABLE chats (jid TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT, last_message_ts INTEGER);"
        "CREATE TABLE contacts (jid TEXT PRIMARY KEY, phone TEXT, push_name TEXT, full_name TEXT, updated_at INTEGER NOT NULL);"
        "CREATE TABLE messages (rowid INTEGER PRIMARY KEY AUTOINCREMENT, chat_jid TEXT NOT NULL, msg_id TEXT NOT NULL, "
        "sender_jid TEXT, ts INTEGER NOT NULL, from_me INTEGER NOT NULL, text TEXT, media_type TEXT, filename TEXT, "
        "local_path TEXT, payload_purged_at INTEGER, UNIQUE(chat_jid, msg_id));")
    conn.execute(
        "INSERT INTO messages (chat_jid, msg_id, sender_jid, ts, from_me, text, media_type, filename, local_path) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        ("447700900107@s.whatsapp.net", "M1", "447700900107@s.whatsapp.net", 1752400000, 0, "", "audio", "voice.ogg", str(ogg)))
    conn.commit(); conn.close()

    root = tmp_path / "corpus"
    env = {"BC_WHATSAPP_BACKEND": "wacli", "BC_WACLI_STORE": str(store_dir),
           "BC_CORPUS_ROOT": str(root), "BC_DERIVE_WORK": str(tmp_path / "w")}
    count = cli.main(["--source", "whatsapp"], env=env, transcribe_fn=lambda p: ("hallo", "de"))
    assert count == 1
    tconn = transcripts.connect(root / "transcripts.db")
    status = dict(tconn.execute("SELECT message_id, status FROM transcripts")).get("M1")
    tconn.close()
    assert status == "ok"
