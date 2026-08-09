"""Initialise Backchannel locally without installing or starting services."""
import argparse
import json
import shutil
import urllib.request
from pathlib import Path

from config import DEFAULT_CONFIG_PATH, Settings


DEPENDENCIES = ("signal-cli", "ffmpeg", "whisper-cli", "qmd", "qrencode")
MODELS = {
    "small": ("ggml-small.bin", "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin"),
    "large": ("ggml-large-v3-turbo.bin", "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo.bin"),
}


def missing_dependencies(which=shutil.which) -> list[str]:
    return [name for name in DEPENDENCIES if which(name) is None]


def model_url(model: str) -> str:
    return MODELS[model][1]


def download_model(model: str, destination: Path, urlopen=urllib.request.urlopen) -> None:
    destination = Path(destination).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    try:
        with urlopen(model_url(model)) as response, temporary.open("wb") as output:
            shutil.copyfileobj(response, output)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv=None, env=None) -> int:
    parser = argparse.ArgumentParser(prog="backchannel setup")
    parser.add_argument("--config")
    parser.add_argument("--model", choices=tuple(MODELS), default="small")
    args = parser.parse_args(argv)
    env = {} if env is None else env
    config_path = Path(args.config or env.get("BC_CONFIG") or DEFAULT_CONFIG_PATH).expanduser()
    created = Settings.write_default_config(config_path)
    settings = Settings.from_environment(env, config_path=config_path)
    missing = missing_dependencies()
    print(f"config {'created' if created else 'already exists'}: {config_path}")
    print("missing dependencies: " + (", ".join(missing) if missing else "none"))
    destination = settings.whisper_model if args.model == "small" else settings.whisper_model.parent / MODELS[args.model][0]
    if created and args.model != "small":
        # write_default_config always points BC_WHISPER_MODEL at the small model;
        # a freshly created config must instead point at the model this run downloads.
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        payload["BC_WHISPER_MODEL"] = str(destination)
        config_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"downloading Whisper {args.model} model to {destination}")
    download_model(args.model, destination)
    return 0
