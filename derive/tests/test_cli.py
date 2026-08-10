from pathlib import Path
from derive import cli


def test_cli_rebuild(store_db, tmp_path):
    root = tmp_path / "corpus"
    work = tmp_path / "work"
    env = {
        "BC_WHATSAPP_STORE": str(store_db),
        "BC_CORPUS_ROOT": str(root),
        "BC_DERIVE_WORK": str(work),
    }
    written = cli.main(["--source", "whatsapp", "--rebuild"], env=env)
    assert written > 0

    # Group files
    assert (root / "whatsapp" / "groups" / "sample-group" / "2026-06-15.md").exists()
    assert (root / "whatsapp" / "groups" / "sample-group" / "2026-06-16.md").exists()

    # DM files
    assert (root / "whatsapp" / "dms" / "anna-beispiel" / "2026-06-15.md").exists()
    assert (root / "whatsapp" / "dms" / "anna-beispiel" / "2013-05-01.md").exists()
    assert (root / "whatsapp" / "dms" / "12025550101" / "2026-06-15.md").exists()

    # Slug collision (two "Chris Muster" numbers): BOTH kept, disambiguated — no data loss
    assert (root / "whatsapp" / "dms" / "chris-muster-447700900123" / "2026-06-15.md").exists()
    assert (root / "whatsapp" / "dms" / "chris-muster-447700900102" / "2026-06-15.md").exists()

    # No pre-2009
    assert list((root / "whatsapp").rglob("2008-*.md")) == []

    # No newsletter
    assert not (root / "whatsapp" / "groups" / "some-channel").exists()
    assert not (root / "whatsapp" / "dms" / "some-channel").exists()

    # State file
    assert (work / "whatsapp" / "state.json").exists()


def test_cli_incremental_noop(store_db, tmp_path):
    root = tmp_path / "corpus"
    work = tmp_path / "work"
    env = {
        "BC_WHATSAPP_STORE": str(store_db),
        "BC_CORPUS_ROOT": str(root),
        "BC_DERIVE_WORK": str(work),
    }
    cli.main(["--source", "whatsapp", "--rebuild"], env=env)
    group_file = root / "whatsapp" / "groups" / "sample-group" / "2026-06-15.md"
    mtime = group_file.stat().st_mtime

    # second run — no new messages, watermark stops processing
    written = cli.main(["--source", "whatsapp"], env=env)
    assert written == 0
    assert group_file.stat().st_mtime == mtime


def test_cli_idempotent_rebuild(store_db, tmp_path):
    root = tmp_path / "corpus"
    work = tmp_path / "work"
    env = {
        "BC_WHATSAPP_STORE": str(store_db),
        "BC_CORPUS_ROOT": str(root),
        "BC_DERIVE_WORK": str(work),
    }
    cli.main(["--source", "whatsapp", "--rebuild"], env=env)
    group_file = root / "whatsapp" / "groups" / "sample-group" / "2026-06-15.md"
    first = group_file.read_bytes()

    cli.main(["--source", "whatsapp", "--rebuild"], env=env)
    second = group_file.read_bytes()
    assert first == second


def test_resolve_config_whatsapp_contacts_db_default(tmp_path):
    store_db = tmp_path / "store" / "messages.db"
    store_db.parent.mkdir(parents=True)
    env = {"BC_WHATSAPP_STORE": str(store_db), "BC_CORPUS_ROOT": str(tmp_path / "c"),
           "BC_DERIVE_WORK": str(tmp_path / "w")}
    cfg = cli.resolve_config("whatsapp", env)
    assert cfg.contacts_db == tmp_path / "store" / "whatsapp.db"   # sibling of messages.db
    assert cfg.contacts_snapshot == tmp_path / "w" / "whatsapp" / "contacts.db"


def test_resolve_config_whatsapp_contacts_db_override(tmp_path):
    env = {"BC_WHATSAPP_STORE": str(tmp_path / "messages.db"), "BC_WHATSAPP_CONTACTS": "/custom/wa.db",
           "BC_CORPUS_ROOT": str(tmp_path / "c"), "BC_DERIVE_WORK": str(tmp_path / "w")}
    assert cli.resolve_config("whatsapp", env).contacts_db == Path("/custom/wa.db")


def test_cli_resolves_group_sender_names(store_db, contacts_db, tmp_path):
    root = tmp_path / "corpus"
    work = tmp_path / "work"
    env = {
        "BC_WHATSAPP_STORE": str(store_db),
        "BC_WHATSAPP_CONTACTS": str(contacts_db),
        "BC_CORPUS_ROOT": str(root),
        "BC_DERIVE_WORK": str(work),
    }
    cli.main(["--source", "whatsapp", "--rebuild"], env=env)
    text = (root / "whatsapp" / "groups" / "sample-group" / "2026-06-15.md").read_text()
    assert "Joe Group" in text          # 12025550101 resolved via contacts
    assert "+12025550101" not in text   # raw-number fallback is gone


def test_cli_incremental_rerenders_day_when_transcript_lands_after_watermark(store_db, tmp_path):
    """A transcript that finishes after the message watermark has already moved past
    its day must still get rendered on the next incremental run — it must not require
    another later message in that same day to force a re-scan."""
    from transcribe import transcripts

    root = tmp_path / "corpus"
    work = tmp_path / "work"
    env = {
        "BC_WHATSAPP_STORE": str(store_db),
        "BC_CORPUS_ROOT": str(root),
        "BC_DERIVE_WORK": str(work),
    }
    cli.main(["--source", "whatsapp", "--rebuild"], env=env)
    group_file = root / "whatsapp" / "groups" / "sample-group" / "2026-06-15.md"
    assert "🎙 hallo welt" not in group_file.read_text()

    tconn = transcripts.connect(root / "transcripts.db")
    transcripts.upsert(tconn, "whatsapp", "G4", "120363100000000001@g.us", "hallo welt", "de", "m.bin", "ok",
                        "2026-06-16T09:00:00+00:00")
    tconn.close()

    written = cli.main(["--source", "whatsapp"], env=env)
    assert written > 0
    assert "🎙 hallo welt" in group_file.read_text()


def test_cli_renders_transcript(store_db, tmp_path):
    from transcribe import transcripts
    root = tmp_path / "corpus"
    work = tmp_path / "work"
    env = {
        "BC_WHATSAPP_STORE": str(store_db),
        "BC_CORPUS_ROOT": str(root),
        "BC_DERIVE_WORK": str(work),
    }
    # Pre-populate transcripts.db with an ok row for G4 (fixture audio message)
    tconn = transcripts.connect(root / "transcripts.db")
    transcripts.upsert(tconn, "whatsapp", "G4", "120363100000000001@g.us", "hallo welt", "de", "m.bin", "ok", "2026-06-15T09:00:00+00:00")
    tconn.close()

    cli.main(["--source", "whatsapp", "--rebuild"], env=env)
    group_file = root / "whatsapp" / "groups" / "sample-group" / "2026-06-15.md"
    text = group_file.read_text()
    assert "🎙 hallo welt" in text
    # The placeholder should NOT appear for this message
    assert "[voice note" not in text


def test_two_sources_share_one_corpus_without_slug_collision(tmp_path):
    import sqlite3
    from derive import cli

    def seed(path, jid, name, sender, content):
        conn = sqlite3.connect(path)
        conn.executescript(
            "CREATE TABLE chats (jid TEXT PRIMARY KEY, name TEXT);"
            "CREATE TABLE messages (id TEXT, chat_jid TEXT, sender TEXT, content TEXT, "
            "timestamp TEXT, is_from_me BOOLEAN, media_type TEXT, filename TEXT, "
            "PRIMARY KEY (id, chat_jid));"
        )
        conn.execute("INSERT INTO chats VALUES (?, ?)", (jid, name))
        conn.execute(
            "INSERT INTO messages VALUES (?, ?, ?, ?, ?, 0, '', '')",
            ("fixture-1", jid, sender, content, "2026-08-07 09:00:00+00:00"),
        )
        conn.commit()
        conn.close()

    whatsapp = tmp_path / "whatsapp.db"
    signal = tmp_path / "signal.db"
    seed(whatsapp, "120000000000000001@g.us", "Shared Fixture", "447700900111", "from whatsapp")
    seed(signal, "fixture-group@group.signal", "Shared Fixture", "fixture-sender", "from signal")
    root = tmp_path / "corpus"
    env = {"BC_CORPUS_ROOT": str(root), "BC_WHATSAPP_STORE": str(whatsapp), "BC_SIGNAL_STORE": str(signal)}

    assert cli.main(["--source", "whatsapp", "--rebuild"], env=env) == 1
    assert cli.main(["--source", "signal", "--rebuild"], env=env) == 1
    wa_file = root / "whatsapp" / "groups" / "shared-fixture" / "2026-08-07.md"
    sig_file = root / "signal" / "groups" / "shared-fixture" / "2026-08-07.md"
    assert wa_file.read_text(encoding="utf-8").count("from whatsapp") == 1
    assert sig_file.read_text(encoding="utf-8").count("from signal") == 1
    assert "source: whatsapp" in wa_file.read_text(encoding="utf-8")
    assert "source: signal" in sig_file.read_text(encoding="utf-8")


def test_cli_renders_image_text_and_indexes_below_threshold_text(store_db, tmp_path):
    from describe import extracts

    root = tmp_path / "corpus"
    env = {"BC_WHATSAPP_STORE": str(store_db), "BC_CORPUS_ROOT": str(root), "BC_DERIVE_WORK": str(tmp_path / "work")}
    conn = extracts.connect(root / "image_text.db")
    extracts.upsert(conn, "whatsapp", "G3", "120363100000000001@g.us", "fixture searchable image text", 1, 0.9, False, "apple-vision", "ok", "now")
    conn.close()
    cli.main(["--source", "whatsapp", "--rebuild"], env=env)
    text = (root / "whatsapp" / "groups" / "sample-group" / "2026-06-15.md").read_text()
    assert "fixture searchable image text" in text
    assert "**09:12" in text and "[image]" in text


def _seed_wacli_store(store_dir):
    import sqlite3
    db = store_dir / "wacli.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    conn.executescript(
        "CREATE TABLE chats (jid TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT, last_message_ts INTEGER);"
        "CREATE TABLE contacts (jid TEXT PRIMARY KEY, phone TEXT, push_name TEXT, full_name TEXT, updated_at INTEGER NOT NULL);"
        "CREATE TABLE messages (rowid INTEGER PRIMARY KEY AUTOINCREMENT, chat_jid TEXT NOT NULL, msg_id TEXT NOT NULL, "
        "sender_jid TEXT, ts INTEGER NOT NULL, from_me INTEGER NOT NULL, text TEXT, media_type TEXT, filename TEXT, "
        "local_path TEXT, revoked INTEGER NOT NULL DEFAULT 0, deleted_for_me INTEGER NOT NULL DEFAULT 0, "
        "payload_purged_at INTEGER, UNIQUE(chat_jid, msg_id));")
    conn.execute("INSERT INTO chats VALUES ('447700900107@s.whatsapp.net','dm','Fixture Contact',1752400000)")
    conn.execute("INSERT INTO contacts VALUES ('447700900107@s.whatsapp.net','447700900107','fixi','Fixture Contact',1752400000)")
    return conn


def test_resolve_config_wacli_backend_points_at_wacli_db(tmp_path):
    wacli_store = tmp_path / "wa"
    env = {
        "BC_WHATSAPP_BACKEND": "wacli",
        "BC_WACLI_STORE": str(wacli_store),
        "BC_CORPUS_ROOT": str(tmp_path / "c"),
        "BC_DERIVE_WORK": str(tmp_path / "w"),
    }
    cfg = cli.resolve_config("whatsapp", env)
    assert cfg.backend == "wacli"
    assert cfg.store_db == wacli_store / "wacli.db"
    assert cfg.contacts_db is None
    assert cfg.wacli_store == wacli_store


def test_derive_wacli_rebuild_writes_corpus_and_advances_cursor(tmp_path):
    import datetime as _dt
    import json
    conn = _seed_wacli_store(tmp_path / "wa")
    conn.execute(
        "INSERT INTO messages (chat_jid, msg_id, sender_jid, ts, from_me, text, media_type, filename, local_path) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        ("447700900107@s.whatsapp.net", "M1", "447700900107@s.whatsapp.net", 1752400000, 0, "hello wacli", "", "", None))
    conn.commit(); conn.close()

    root = tmp_path / "corpus"
    env = {"BC_WHATSAPP_BACKEND": "wacli", "BC_WACLI_STORE": str(tmp_path / "wa"),
           "BC_CORPUS_ROOT": str(root), "BC_DERIVE_WORK": str(tmp_path / "w")}
    written = cli.main(["--source", "whatsapp", "--rebuild"], env=env)
    assert written > 0

    expected_day = _dt.datetime.fromtimestamp(1752400000, tz=_dt.timezone.utc).astimezone().date()
    day_file = root / "whatsapp" / "dms" / "fixture-contact" / f"{expected_day.isoformat()}.md"
    assert day_file.exists()
    assert "hello wacli" in day_file.read_text()
    state = json.loads((tmp_path / "w" / "whatsapp" / "state.json").read_text())
    assert state["wacli_rowid_cursor"] == 1


def test_derive_wacli_incremental_advances_cursor_for_backdated_rows(tmp_path):
    # A backdated row (older ts) arriving later as a new rowid must still be derived — the
    # case a timestamp watermark gets permanently wrong for wacli history sync.
    import datetime as _dt
    import sqlite3
    conn = _seed_wacli_store(tmp_path / "wa")
    conn.execute(
        "INSERT INTO messages (chat_jid, msg_id, sender_jid, ts, from_me, text, media_type, filename, local_path) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        ("447700900107@s.whatsapp.net", "M1", "447700900107@s.whatsapp.net", 1752400000, 0, "first", "", "", None))
    conn.commit(); conn.close()

    root = tmp_path / "corpus"
    env = {"BC_WHATSAPP_BACKEND": "wacli", "BC_WACLI_STORE": str(tmp_path / "wa"),
           "BC_CORPUS_ROOT": str(root), "BC_DERIVE_WORK": str(tmp_path / "w")}
    cli.main(["--source", "whatsapp"], env=env)  # first run derives everything; cursor -> 1

    conn = sqlite3.connect(tmp_path / "wa" / "wacli.db")
    conn.execute(
        "INSERT INTO messages (chat_jid, msg_id, sender_jid, ts, from_me, text, media_type, filename, local_path) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        ("447700900107@s.whatsapp.net", "M2", "447700900107@s.whatsapp.net", 1700000000, 0, "backdated", "", "", None))
    conn.commit(); conn.close()

    written = cli.main(["--source", "whatsapp"], env=env)
    assert written > 0
    expected_day = _dt.datetime.fromtimestamp(1700000000, tz=_dt.timezone.utc).astimezone().date()
    assert (root / "whatsapp" / "dms" / "fixture-contact" / f"{expected_day.isoformat()}.md").exists()
