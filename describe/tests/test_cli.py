from describe import cli, extracts
from describe.text import VisionUnavailableError


def _env(messages_db, tmp_path):
    return {
        "BC_WHATSAPP_STORE": str(messages_db),
        "BC_WHATSAPP_MEDIA": str(tmp_path / "media"),
        "BC_CORPUS_ROOT": str(tmp_path / "corpus"),
    }


def test_main_stores_document_like_text_and_skips_terminal_rows(messages_db, tmp_path):
    env = _env(messages_db, tmp_path)
    path = tmp_path / "media" / "fixture-chat" / "document.png"
    path.parent.mkdir(parents=True)
    path.touch()
    lines = [("fixture line one with enough text", 0.9), ("fixture line two with enough text", 0.8), ("fixture line three with enough text", 0.7)]
    assert cli.main(["--source", "whatsapp"], env, recognize_fn=lambda _: lines) == 1
    conn = extracts.connect(tmp_path / "corpus" / "image_text.db")
    assert conn.execute(
        "SELECT text, line_count, document_like, status FROM image_text WHERE message_id='image-document'"
    ).fetchone() == ("fixture line one with enough text\nfixture line two with enough text\nfixture line three with enough text", 3, 1, "ok")
    conn.close()
    assert cli.main(["--source", "whatsapp"], env, recognize_fn=lambda _: (_ for _ in ()).throw(AssertionError("terminal row rerun"))) == 0


def test_main_marks_empty_missing_and_failed_for_retry(messages_db, tmp_path):
    env = _env(messages_db, tmp_path)
    folder = tmp_path / "media" / "fixture-chat"
    folder.mkdir(parents=True)
    (folder / "document.png").touch()
    (folder / "short.jpg").touch()

    def recognize(path):
        if path.name == "document.png":
            return []
        raise RuntimeError("fixture OCR failure")

    assert cli.main(["--source", "whatsapp"], env, recognize_fn=recognize) == 0
    conn = extracts.connect(tmp_path / "corpus" / "image_text.db")
    assert dict(conn.execute("SELECT message_id, status FROM image_text")) == {
        "image-document": "empty", "image-short": "failed", "image-missing": "missing"
    }
    conn.close()
    assert cli.main(["--source", "whatsapp"], env, recognize_fn=lambda _: [("recovered", 0.8)]) == 1


def test_main_reports_unavailable_dependency_once_without_failed_rows(messages_db, tmp_path, caplog):
    env = _env(messages_db, tmp_path)
    folder = tmp_path / "media" / "fixture-chat"
    folder.mkdir(parents=True)
    (folder / "document.png").touch()
    (folder / "short.jpg").touch()
    calls = []

    def unavailable(path):
        calls.append(path)
        raise VisionUnavailableError("fixture Vision unavailable")

    assert cli.main(["--source", "whatsapp"], env, recognize_fn=unavailable) == 0
    assert len(calls) == 1
    assert "fixture Vision unavailable" in caplog.text
    conn = extracts.connect(tmp_path / "corpus" / "image_text.db")
    assert conn.execute("SELECT COUNT(*) FROM image_text").fetchone() == (0,)
    conn.close()


def test_signal_and_whatsapp_identical_ids_remain_separate(messages_db, tmp_path):
    import sqlite3

    root = tmp_path / "corpus"
    wa_media = tmp_path / "wa-media" / "fixture-chat"
    wa_media.mkdir(parents=True)
    (wa_media / "document.png").touch()
    wa_env = {"BC_WHATSAPP_STORE": str(messages_db), "BC_WHATSAPP_MEDIA": str(tmp_path / "wa-media"), "BC_CORPUS_ROOT": str(root)}
    assert cli.main(["--source", "whatsapp"], wa_env, recognize_fn=lambda _: [("whatsapp words", 0.9)]) == 1

    signal = tmp_path / "signal.db"
    conn = sqlite3.connect(signal)
    conn.executescript("CREATE TABLE messages (id TEXT, chat_jid TEXT, media_type TEXT, filename TEXT)")
    conn.execute("INSERT INTO messages VALUES ('image-document', 'signal-fixture', 'image', 'same.png')")
    conn.commit()
    conn.close()
    media = tmp_path / "signal-media" / "signal-fixture"
    media.mkdir(parents=True)
    (media / "same.png").touch()
    signal_env = {"BC_SIGNAL_STORE": str(signal), "BC_SIGNAL_MEDIA": str(tmp_path / "signal-media"), "BC_CORPUS_ROOT": str(root)}
    assert cli.main(["--source", "signal"], signal_env, recognize_fn=lambda _: [("signal words", 0.9)]) == 1
    conn = extracts.connect(root / "image_text.db")
    assert conn.execute("SELECT source, text FROM image_text WHERE message_id='image-document' ORDER BY source").fetchall() == [("signal", "signal words"), ("whatsapp", "whatsapp words")]
    conn.close()
