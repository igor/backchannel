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
