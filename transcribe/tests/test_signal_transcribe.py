from pathlib import Path
from unittest.mock import MagicMock, patch
from transcribe import cli, transcripts, whisper


def test_m4a_and_aac_transcribe_and_missing_retries(signal_messages_db, tmp_path):
    root, media = tmp_path / "corpus", tmp_path / "media"
    for jid, name in [("x@signal", "voice.m4a"), ("g@group.signal", "voice.aac")]:
        path = media / jid / name; path.parent.mkdir(parents=True, exist_ok=True); path.touch()
    env = {"BC_SIGNAL_STORE": str(signal_messages_db), "BC_CORPUS_ROOT": str(root), "BC_SIGNAL_MEDIA": str(media)}
    assert cli.main(["--source", "signal"], env=env, transcribe_fn=lambda _: ("local words", "en")) == 2
    conn = transcripts.connect(root / "transcripts.db")
    assert set(conn.execute("SELECT message_id FROM transcripts WHERE source='signal' AND status='ok'").fetchall()) == {("a1",), ("a2",)}
    conn.close()


def test_ffmpeg_accepts_m4a_without_extension_branching():
    def fake(command, **_):
        return MagicMock(stdout="text", stderr="auto-detected language: en")
    with patch("transcribe.whisper.subprocess.run", side_effect=fake) as run:
        assert whisper.transcribe("voice.m4a", "model.bin") == ("text", "en")
    assert run.call_args_list[0].args[0][0] == "ffmpeg"


def test_failed_rows_are_retried(signal_messages_db, tmp_path):
    root, media = tmp_path / "corpus", tmp_path / "media"; path = media / "x@signal" / "voice.m4a"; path.parent.mkdir(parents=True); path.touch()
    env = {"BC_SIGNAL_STORE": str(signal_messages_db), "BC_CORPUS_ROOT": str(root), "BC_SIGNAL_MEDIA": str(media)}
    cli.main(["--source", "signal"], env=env, transcribe_fn=lambda _: (_ for _ in ()).throw(RuntimeError("bad")))
    assert cli.main(["--source", "signal"], env=env, transcribe_fn=lambda _: ("recovered", "en")) == 1
