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
