from derive import cli, naming, render, store
from derive.model import Chat, ChatView, Message
from datetime import datetime, timezone


def test_signal_chat_type_and_uuid_collision_slug():
    assert naming.chat_type("signal", "abc@signal") == "dm"
    assert naming.chat_type("signal", "group@group.signal") == "group"
    assert naming.chat_type("signal", "x@s.whatsapp.net") is None
    slugs = naming.resolve_slugs("signal", {"11111111-2222-4333-8444-555555555555@signal": Chat("", "Ada"), "22222222-2222-4333-8444-555555555555@signal": Chat("", "Ada")})
    assert len(set(slugs.values())) == 2


def test_parse_ts_accepts_wa_contract_timestamp():
    assert store.parse_ts("2026-06-15 15:26:28+02:00").utcoffset().total_seconds() == 7200


def test_rebuild_renders_signal_frontmatter_and_uuid_sender(signal_store_db, tmp_path):
    root = tmp_path / "corpus"
    assert cli.main(["--source", "signal", "--rebuild"], env={"BC_SIGNAL_STORE": str(signal_store_db), "BC_CORPUS_ROOT": str(root), "BC_DERIVE_WORK": str(tmp_path / "work")}) == 2
    group = root / "signal" / "groups" / "research-group" / "2026-07-27.md"
    text = group.read_text()
    assert "source: signal" in text and "tags:\n- signal" in text
    assert "Bea Profile" in text and "[voice note · voice.m4a]" in text


def test_transcript_renders_inline(signal_store_db, tmp_path):
    import sqlite3
    root = tmp_path / "corpus"; root.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(root / "transcripts.db")
    conn.executescript("CREATE TABLE transcripts (source TEXT NOT NULL,message_id TEXT NOT NULL,chat_jid TEXT,text TEXT,lang TEXT,model TEXT,status TEXT,transcribed_at TEXT,revision INTEGER,PRIMARY KEY(source,message_id))")
    conn.execute("INSERT INTO transcripts VALUES ('signal','g2','','spoken locally','','','ok','2026-07-27T09:02:00+00:00',1)"); conn.commit(); conn.close()
    cli.main(["--source", "signal", "--rebuild"], env={"BC_SIGNAL_STORE": str(signal_store_db), "BC_CORPUS_ROOT": str(root), "BC_DERIVE_WORK": str(tmp_path / "work")})
    day_file = root / "signal" / "groups" / "research-group" / "2026-07-27.md"
    assert "🎙 spoken locally" in day_file.read_text()


def test_incremental_is_noop_after_watermark(signal_store_db, tmp_path):
    env = {"BC_SIGNAL_STORE": str(signal_store_db), "BC_CORPUS_ROOT": str(tmp_path / "corpus"), "BC_DERIVE_WORK": str(tmp_path / "work")}
    cli.main(["--source", "signal", "--rebuild"], env=env)
    assert cli.main(["--source", "signal"], env=env) == 0
