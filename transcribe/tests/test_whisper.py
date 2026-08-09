from pathlib import Path
import subprocess
import tempfile
from unittest.mock import patch, MagicMock
import pytest

from transcribe import whisper


def test_transcribe_invokes_ffmpeg_then_whisper_and_returns_text_and_lang():
    ogg = Path("/x/a.ogg")
    model = Path("/m/model.bin")

    def fake_run(cmd, **kwargs):
        if cmd[0] == "ffmpeg":
            assert cmd == ["ffmpeg", "-i", str(ogg), "-ar", "16000", "-ac", "1", "-y", cmd[-1]]
            assert kwargs.get("check") is True
            return MagicMock(stdout="", stderr="", returncode=0)
        if cmd[0] == "whisper-cli":
            assert "-m" in cmd
            assert str(model) in cmd
            assert "-f" in cmd
            assert "-l" in cmd
            assert "auto" in cmd
            assert "-nt" in cmd
            return MagicMock(stdout="  hallo welt  ", stderr="auto-detected language: de\n", returncode=0)
        raise AssertionError(f"unexpected command: {cmd}")

    with patch("transcribe.whisper.subprocess.run", side_effect=fake_run):
        text, lang = whisper.transcribe(ogg, model)
    assert text == "hallo welt"
    assert lang == "de"


def test_transcribe_returns_auto_when_no_lang_detected():
    def fake_run(cmd, **kwargs):
        if cmd[0] == "ffmpeg":
            return MagicMock(stdout="", stderr="", returncode=0)
        if cmd[0] == "whisper-cli":
            return MagicMock(stdout="hello world", stderr="some other output", returncode=0)
        raise AssertionError(f"unexpected command: {cmd}")

    with patch("transcribe.whisper.subprocess.run", side_effect=fake_run):
        text, lang = whisper.transcribe("/x/a.ogg", "/m/model.bin")
    assert text == "hello world"
    assert lang == "auto"


def test_transcribe_raises_on_ffmpeg_failure():
    def fake_run(cmd, **kwargs):
        if cmd[0] == "ffmpeg":
            raise subprocess.CalledProcessError(1, cmd, stderr="bad file")
        raise AssertionError("whisper should not be called after ffmpeg fails")

    with patch("transcribe.whisper.subprocess.run", side_effect=fake_run):
        with pytest.raises(subprocess.CalledProcessError):
            whisper.transcribe("/x/a.ogg", "/m/model.bin")


def test_transcribe_raises_on_whisper_failure():
    def fake_run(cmd, **kwargs):
        if cmd[0] == "ffmpeg":
            return MagicMock(stdout="", stderr="", returncode=0)
        if cmd[0] == "whisper-cli":
            raise subprocess.CalledProcessError(1, cmd, stderr="model error")
        raise AssertionError(f"unexpected command: {cmd}")

    with patch("transcribe.whisper.subprocess.run", side_effect=fake_run):
        with pytest.raises(subprocess.CalledProcessError):
            whisper.transcribe("/x/a.ogg", "/m/model.bin")
