from io import BytesIO
from pathlib import Path

import provision


def test_missing_dependencies_reports_every_absent_binary():
    assert provision.missing_dependencies(which=lambda name: None) == ["signal-cli", "ffmpeg", "whisper-cli", "qmd", "qrencode"]


def test_default_setup_initialises_config_and_downloads_small_model(tmp_path, monkeypatch):
    downloaded = []
    monkeypatch.setattr(provision, "missing_dependencies", lambda: [])
    monkeypatch.setattr(provision, "download_model", lambda model, destination: downloaded.append((model, destination)))
    config = tmp_path / "config.json"
    assert provision.main(["--config", str(config)], {}) == 0
    assert downloaded == [("small", Path("~/whisper-models/ggml-small.bin").expanduser())]
    assert '"BC_WHISPER_MODEL": "~/whisper-models/ggml-small.bin"' in config.read_text(encoding="utf-8")


def test_large_download_requires_explicit_model_flag(tmp_path, monkeypatch):
    downloaded = []
    monkeypatch.setattr(provision, "missing_dependencies", lambda: [])
    monkeypatch.setattr(provision, "download_model", lambda model, destination: downloaded.append(model))
    config = tmp_path / "config.json"
    assert provision.main(["--config", str(config), "--model", "large"], {}) == 0
    assert downloaded == ["large"]
    expected = str(Path("~/whisper-models/ggml-large-v3-turbo.bin").expanduser())
    assert f'"BC_WHISPER_MODEL": "{expected}"' in config.read_text(encoding="utf-8")


def test_large_setup_does_not_override_an_existing_configs_model(tmp_path, monkeypatch):
    monkeypatch.setattr(provision, "missing_dependencies", lambda: [])
    monkeypatch.setattr(provision, "download_model", lambda model, destination: None)
    config = tmp_path / "config.json"
    provision.main(["--config", str(config)], {})  # first run creates the small-model config
    provision.main(["--config", str(config), "--model", "large"], {})
    assert '"BC_WHISPER_MODEL": "~/whisper-models/ggml-small.bin"' in config.read_text(encoding="utf-8")


def test_download_model_writes_bytes_from_injected_urlopen(tmp_path):
    class Response(BytesIO):
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, traceback):
            return False

    destination = tmp_path / "model.bin"
    provision.download_model("small", destination, urlopen=lambda url: Response(b"fixture-model"))
    assert destination.read_bytes() == b"fixture-model"
