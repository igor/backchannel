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
