import json
from pathlib import Path

from config import Settings




def test_config_file_values_become_canonical_runtime_values(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "BC_CORPUS_ROOT": str(tmp_path / "corpus"),
        "BC_TRANSCRIBE_WRAPPER": "/bin/echo fixture-lock",
    }), encoding="utf-8")
    settings = Settings.from_environment({}, config_path=path)
    assert settings.corpus_root == tmp_path / "corpus"
    assert settings.as_env()["BC_TRANSCRIBE_WRAPPER"] == "/bin/echo fixture-lock"


def test_environment_canonical_value_wins_over_config_file(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"BC_WHISPER_MODEL": str(tmp_path / "file.bin")}), encoding="utf-8")
    settings = Settings.from_environment({"BC_WHISPER_MODEL": str(tmp_path / "env.bin")}, config_path=path)
    assert settings.whisper_model == tmp_path / "env.bin"


def test_write_default_config_does_not_overwrite_existing_file(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"BC_SIGNAL_ACCOUNT":"fixture-account"}\n', encoding="utf-8")
    assert Settings.write_default_config(path) is False
    assert path.read_text(encoding="utf-8") == '{"BC_SIGNAL_ACCOUNT":"fixture-account"}\n'


def test_whatsapp_backend_defaults_to_bridge(tmp_path):
    settings = Settings.from_environment({}, config_path=tmp_path / "missing.json")
    assert settings.whatsapp_backend == "bridge"
    assert settings.wacli_bin == "wacli"
    assert settings.wacli_store == Path("~/.wacli").expanduser()


def test_whatsapp_backend_is_lowercased_and_env_wins(tmp_path):
    settings = Settings.from_environment(
        {"BC_WHATSAPP_BACKEND": "  WaCli  ", "BC_WACLI_BIN": "/opt/homebrew/bin/wacli",
         "BC_WACLI_STORE": "/data/wacli"}, config_path=tmp_path / "missing.json")
    assert settings.whatsapp_backend == "wacli"
    assert settings.wacli_bin == "/opt/homebrew/bin/wacli"
    assert settings.wacli_store == Path("/data/wacli")


def test_wacli_settings_round_trip_through_as_env(tmp_path):
    first = Settings.from_environment(
        {"BC_WHATSAPP_BACKEND": "wacli", "BC_WACLI_STORE": "/data/wacli"},
        config_path=tmp_path / "missing.json")
    second = Settings.from_environment(first.as_env(), config_path=tmp_path / "missing.json")
    assert second.whatsapp_backend == "wacli"
    assert second.wacli_store == Path("/data/wacli")
    assert second.as_env()["BC_WACLI_BIN"] == "wacli"


def test_write_default_config_does_not_add_wacli_keys(tmp_path):
    # wacli is opt-in; an existing operator's config file must not change shape on upgrade.
    path = tmp_path / "config.json"
    Settings.write_default_config(path)
    raw = json.loads(path.read_text())
    assert "BC_WHATSAPP_BACKEND" not in raw
    assert "BC_WACLI_STORE" not in raw
