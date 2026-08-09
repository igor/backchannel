"""Transcribe an .ogg via ffmpeg (-> 16k mono wav) + whisper.cpp. The subprocess boundary."""
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Tuple

_LANG_RE = re.compile(r"auto-detected language:\s*(\w+)")


def transcribe(ogg_path, model, whisper_bin: str = "whisper-cli",
               ffmpeg_bin: str = "ffmpeg") -> Tuple[str, str]:
    """Return (text, lang). Raises subprocess.CalledProcessError on binary failure."""
    ogg_path = Path(ogg_path)
    with tempfile.TemporaryDirectory() as td:
        wav = str(Path(td) / "a.wav")
        subprocess.run([ffmpeg_bin, "-i", str(ogg_path), "-ar", "16000", "-ac", "1", "-y", wav],
                       check=True, capture_output=True, text=True)
        res = subprocess.run([whisper_bin, "-m", str(model), "-f", wav, "-l", "auto", "-nt"],
                             check=True, capture_output=True, text=True)
    m = _LANG_RE.search(res.stderr or "")
    return (res.stdout or "").strip(), (m.group(1) if m else "auto")
