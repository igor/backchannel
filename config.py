"""Backchannel configuration: the BC_* environment and config-file contract."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


DEFAULT_CONFIG_PATH = Path("~/.config/backchannel/config.json").expanduser()


_WHATSAPP_BACKENDS = ("bridge", "wacli")


def resolve_backend(raw: str) -> str:
    """Validate a BC_WHATSAPP_BACKEND value. A typo must fail loudly, never silently
    select the bridge — every consumer (Settings, derive, transcribe, describe) resolves
    through here so the vocabulary is enforced once."""
    backend = (raw or "bridge").strip().lower()
    if backend not in _WHATSAPP_BACKENDS:
        raise ValueError(
            f"BC_WHATSAPP_BACKEND must be one of {', '.join(_WHATSAPP_BACKENDS)}; got {raw!r}")
    return backend


def _nonempty(values: Mapping[str, str], *names: str, default: str) -> str:
    for name in names:
        value = values.get(name, "")
        if value:
            return value
    return default


def _positive_int(values: Mapping[str, str], name: str, default: int) -> int:
    raw = values.get(name, "")
    if not raw:
        return default
    try:
        seconds = int(raw)
    except ValueError:
        raise ValueError(f"backchannel: {name} must be a whole number of seconds, got {raw!r}")
    if seconds < 1:
        raise ValueError(f"backchannel: {name} must be at least 1 second, got {seconds}")
    return seconds


def _config_values(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in raw.items()):
        raise ValueError(f"backchannel: config must be a JSON object of string values: {path}")
    return raw


@dataclass(frozen=True)
class Settings:
    corpus_root: Path
    whatsapp_store: Path
    whatsapp_media: Path
    whatsapp_contacts: Path
    whatsapp_bridge_bin: str
    whatsapp_backend: str
    wacli_bin: str
    wacli_store: Path
    signal_store_root: Path
    signal_store: Path
    signal_account: str
    signal_cli_bin: str
    signal_cli_data: Path
    whisper_model: Path
    whisper_bin: str
    ffmpeg_bin: str
    qmd_bin: str
    transcribe_wrapper: str
    log_root: Path
    describe_enabled: bool
    capture_interval: int
    derive_interval: int
    transcribe_interval: int
    describe_interval: int
    heartbeat_interval: int

    @classmethod
    def from_environment(cls, env: Mapping[str, str] | None = None, config_path: Path | None = None) -> "Settings":
        env = os.environ if env is None else env
        path = Path(env.get("BC_CONFIG") or config_path or DEFAULT_CONFIG_PATH).expanduser()
        values = {**_config_values(path), **{key: value for key, value in env.items() if value}}
        corpus = Path(_nonempty(values, "BC_CORPUS_ROOT", default="~/.local/share/backchannel/corpus")).expanduser()
        whatsapp_store = Path(_nonempty(values, "BC_WHATSAPP_STORE", default="~/store/messages.db")).expanduser()
        signal_root = Path(_nonempty(values, "BC_SIGNAL_STORE_ROOT", default="~/.local/share/backchannel/signal")).expanduser()
        return cls(
            corpus_root=corpus,
            whatsapp_store=whatsapp_store,
            whatsapp_media=Path(_nonempty(values, "BC_WHATSAPP_MEDIA", default=str(whatsapp_store.parent))).expanduser(),
            whatsapp_contacts=Path(_nonempty(values, "BC_WHATSAPP_CONTACTS", default=str(whatsapp_store.parent / "whatsapp.db"))).expanduser(),
            whatsapp_bridge_bin=_nonempty(values, "BC_WHATSAPP_BRIDGE_BIN", default="whatsapp-bridge"),
            whatsapp_backend=resolve_backend(_nonempty(values, "BC_WHATSAPP_BACKEND", default="bridge")),
            wacli_bin=_nonempty(values, "BC_WACLI_BIN", default="wacli"),
            wacli_store=Path(_nonempty(values, "BC_WACLI_STORE", default="~/.wacli")).expanduser(),
            signal_store_root=signal_root,
            signal_store=Path(_nonempty(values, "BC_SIGNAL_STORE", default=str(signal_root / "messages.db"))).expanduser(),
            signal_account=_nonempty(values, "BC_SIGNAL_ACCOUNT", default=""),
            signal_cli_bin=_nonempty(values, "BC_SIGNAL_CLI_BIN", default="signal-cli"),
            signal_cli_data=Path(_nonempty(values, "BC_SIGNAL_CLI_DATA", default="~/.local/share/signal-cli/data")).expanduser(),
            whisper_model=Path(_nonempty(values, "BC_WHISPER_MODEL", default="~/whisper-models/ggml-small.bin")).expanduser(),
            whisper_bin=_nonempty(values, "BC_WHISPER_BIN", default="whisper-cli"),
            ffmpeg_bin=_nonempty(values, "BC_FFMPEG_BIN", default="ffmpeg"),
            qmd_bin=_nonempty(values, "BC_QMD_BIN", "QMD_BIN", default="qmd"),
            transcribe_wrapper=_nonempty(values, "BC_TRANSCRIBE_WRAPPER", default=""),
            log_root=Path(_nonempty(values, "BC_LOG_ROOT", default="~/.local/state/backchannel/logs")).expanduser(),
            # Image OCR is off unless the operator asks for it. It is the newest capability and
            # the least proven in production, and a public install has nobody watching it.
            # `backchannel describe` still runs by hand; this gates the scheduler only.
            describe_enabled=_nonempty(values, "BC_DESCRIBE_ENABLED", default="").strip().lower()
            in ("1", "true", "yes", "on"),
            # Seconds between runs of each daemon job. The defaults are what the development
            # machine has run on; they exist so an operator with a much larger archive, or a
            # laptop on battery, has a lever. A bad value raises at startup rather than
            # silently falling back — a daemon quietly running on the wrong schedule is worse
            # than one that refuses to start.
            capture_interval=_positive_int(values, "BC_CAPTURE_INTERVAL", 300),
            derive_interval=_positive_int(values, "BC_DERIVE_INTERVAL", 900),
            transcribe_interval=_positive_int(values, "BC_TRANSCRIBE_INTERVAL", 3600),
            describe_interval=_positive_int(values, "BC_DESCRIBE_INTERVAL", 3600),
            heartbeat_interval=_positive_int(values, "BC_HEARTBEAT_INTERVAL", 21600),
        )

    @staticmethod
    def write_default_config(path: Path) -> bool:
        path = Path(path).expanduser()
        if path.exists():
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "BC_CORPUS_ROOT": "~/.local/share/backchannel/corpus",
            "BC_WHATSAPP_STORE": "~/store/messages.db",
            "BC_SIGNAL_STORE_ROOT": "~/.local/share/backchannel/signal",
            "BC_SIGNAL_ACCOUNT": "",
            "BC_WHISPER_MODEL": "~/whisper-models/ggml-small.bin",
            "BC_TRANSCRIBE_WRAPPER": "",
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return True

    def as_env(self) -> dict[str, str]:
        return {
            "BC_CORPUS_ROOT": str(self.corpus_root),
            "BC_WHATSAPP_STORE": str(self.whatsapp_store),
            "BC_WHATSAPP_MEDIA": str(self.whatsapp_media),
            "BC_WHATSAPP_CONTACTS": str(self.whatsapp_contacts),
            "BC_WHATSAPP_BRIDGE_BIN": self.whatsapp_bridge_bin,
            "BC_WHATSAPP_BACKEND": self.whatsapp_backend,
            "BC_WACLI_BIN": self.wacli_bin,
            "BC_WACLI_STORE": str(self.wacli_store),
            "BC_SIGNAL_STORE_ROOT": str(self.signal_store_root),
            "BC_SIGNAL_STORE": str(self.signal_store),
            "BC_SIGNAL_ACCOUNT": self.signal_account,
            "BC_SIGNAL_CLI_BIN": self.signal_cli_bin,
            "BC_SIGNAL_CLI_DATA": str(self.signal_cli_data),
            "BC_WHISPER_MODEL": str(self.whisper_model),
            "BC_WHISPER_BIN": self.whisper_bin,
            "BC_FFMPEG_BIN": self.ffmpeg_bin,
            "BC_QMD_BIN": self.qmd_bin,
            "BC_TRANSCRIBE_WRAPPER": self.transcribe_wrapper,
            "BC_LOG_ROOT": str(self.log_root),
            "BC_DESCRIBE_ENABLED": "1" if self.describe_enabled else "",
            "BC_CAPTURE_INTERVAL": str(self.capture_interval),
            "BC_DERIVE_INTERVAL": str(self.derive_interval),
            "BC_TRANSCRIBE_INTERVAL": str(self.transcribe_interval),
            "BC_DESCRIBE_INTERVAL": str(self.describe_interval),
            "BC_HEARTBEAT_INTERVAL": str(self.heartbeat_interval),
        }
