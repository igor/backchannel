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
| `BC_WHATSAPP_BACKEND` | `bridge` | `bridge` or `wacli` |
| `BC_WACLI_BIN` | `wacli` | wacli executable (wacli backend) |
| `BC_WACLI_STORE` | `~/.wacli` | wacli store directory (wacli backend) |
| `BC_WHISPER_MODEL` | `~/whisper-models/ggml-small.bin` | Whisper GGML model |
| `BC_WHISPER_BIN` | `whisper-cli` | Whisper command |
| `BC_FFMPEG_BIN` | `ffmpeg` | audio conversion command |
| `BC_QMD_BIN` | `qmd` (also reads `QMD_BIN`) | qmd command |
| `BC_TRANSCRIBE_WRAPPER` | empty | optional heavy-job mutex prefix |
| `BC_DESCRIBE_ENABLED` | empty (off) | schedule image OCR in the daemon; `1`/`true`/`yes`/`on` enable it |
| `BC_CAPTURE_INTERVAL` | `300` | seconds between capture runs |
| `BC_DERIVE_INTERVAL` | `900` | seconds between corpus derivations |
| `BC_TRANSCRIBE_INTERVAL` | `3600` | seconds between voice-note transcription runs |
| `BC_DESCRIBE_INTERVAL` | `3600` | seconds between image OCR runs, when enabled |
| `BC_HEARTBEAT_INTERVAL` | `21600` | seconds between capture health checks |

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

## Scheduling

The defaults are what the development machine runs on, and most installs should leave them
alone. They are configurable because the right values depend on how much history you have and
what the machine is doing otherwise.

| Setting | Raise it when | Lower it when |
| --- | --- | --- |
| `BC_CAPTURE_INTERVAL` | never, in practice — capture is cheap, and for WhatsApp this is only how often the supervisor checks the bridge is alive | you want a stopped bridge noticed sooner |
| `BC_DERIVE_INTERVAL` | the corpus is large and derivation shows up in `top` | you want new messages in the corpus sooner |
| `BC_TRANSCRIBE_INTERVAL` | Whisper is competing with something you care about, or you are on battery | you have a backlog of voice notes to clear |
| `BC_DESCRIBE_INTERVAL` | OCR is competing for the GPU | you have a backlog of images |
| `BC_HEARTBEAT_INTERVAL` | rarely — the check is nearly free | you want a broken source reported sooner |

A run that is still going when its next turn comes round is skipped, not queued, so a too-short
interval wastes cycles rather than piling work up.

An unparseable or non-positive value stops the daemon at startup rather than falling back to
the default, so a typo cannot leave it quietly running on the wrong schedule.

`backchannel index` is not on this list. It runs once a night at a fixed local time rather than
on an interval.

The Signal source present in the tree keeps its settings undocumented until its release.
