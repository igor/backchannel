# Configuration reference

`backchannel setup` creates `~/.config/backchannel/config.json` when it is absent.
It stores canonical `BC_*` strings. For every core setting, a non-empty environment
value wins; then the config file; then a portable default.

| Setting | Default | Purpose |
| --- | --- | --- |
| `BC_CORPUS_ROOT` | `~/.local/share/backchannel/corpus` | shared corpus and transcript root |
| `BC_WHATSAPP_STORE` | `~/store/messages.db` | WhatsApp source store |
| `BC_WHATSAPP_MEDIA` | store parent | WhatsApp media root |
| `BC_WHATSAPP_CONTACTS` | `~/store/whatsapp.db` | WhatsApp contact store |
| `BC_WHATSAPP_BRIDGE_BIN` | `whatsapp-bridge` | separate Go bridge binary |
| `BC_SIGNAL_STORE_ROOT` | `~/.local/share/backchannel/signal` | Signal store directory |
| `BC_SIGNAL_STORE` | `<signal root>/messages.db` | Signal source store |
| `BC_SIGNAL_ACCOUNT` | empty | Signal linked account, required for capture |
| `BC_SIGNAL_CLI_BIN` | `signal-cli` | Signal command |
| `BC_SIGNAL_CLI_DATA` | `~/.local/share/signal-cli/data` | Signal client data |
| `BC_WHISPER_MODEL` | `~/whisper-models/ggml-small.bin` | Whisper GGML model |
| `BC_WHISPER_BIN` | `whisper-cli` | Whisper command |
| `BC_FFMPEG_BIN` | `ffmpeg` | audio conversion command |
| `BC_QMD_BIN` | `qmd` (also reads `QMD_BIN`) | qmd command |
| `BC_TRANSCRIBE_WRAPPER` | empty | optional heavy-job mutex prefix |
| `BC_DESCRIBE_ENABLED` | empty (off) | schedule image OCR in the daemon; `1`/`true`/`yes`/`on` enable it |

`backchannel setup` checks `signal-cli`, `ffmpeg`, `whisper-cli`, `qmd`, and `qrencode`.
It downloads `ggml-small.bin` unless `--model large` is explicitly supplied. Keep keys,
real endpoints, and machine-specific locations in ignored local configuration, not in
tracked files.

Connector configuration lives with its connector and is not read by `backchannel daemon`.
See [CONNECTORS.md](CONNECTORS.md).

## Image OCR is opt-in

`backchannel daemon` does not schedule the `describe` jobs unless `BC_DESCRIBE_ENABLED`
is set. OCR is the newest capability and the least proven over long runs, so an install
that nobody is watching does not run it by default.

This gates the scheduler, not the feature: `backchannel describe --source whatsapp` works
by hand whether or not the variable is set. Turning it on is one environment variable and
a daemon restart.
