# Components reference

## Public Backchannel command

| Command | Purpose |
| --- | --- |
| `backchannel setup` | initialise config, report dependency gaps, download the small Whisper model |
| `backchannel link signal` | obtain a Signal linked-device URI through a pty, render/open a temporary PNG QR code, then delete it |
| `backchannel daemon` | run the one supervisor process |
| `backchannel capture --source <source>` | run one capture implementation |
| `backchannel derive --source <source> [--rebuild]` | derive one source store |
| `backchannel transcribe --source <source>` | transcribe one source's pending audio |
| `backchannel index` | create/update/embed qmd collection `backchannel` |

## Scheduled core jobs

| Job | Interval | Implementation |
| --- | ---: | --- |
| WhatsApp and Signal capture | 5 minutes | bridge wrapper / Signal receive-spool-replay |
| WhatsApp and Signal derive | 15 minutes | `derive.cli.main` |
| WhatsApp and Signal transcription | 1 hour | `transcribe.cli.main`, optionally mutex-prefixed |
| WhatsApp and Signal heartbeat | 6 hours | `heartbeat.cli.check` |
| qmd index | nightly at 03:17 | `index.cli.main` |

## Configuration

See [CONFIGURATION.md](CONFIGURATION.md). The public settings are `BC_CORPUS_ROOT`,
per-source stores, `BC_WHATSAPP_BACKEND`, `BC_WHISPER_MODEL`, and optional
`BC_TRANSCRIBE_WRAPPER`. qmd is optional for capture but required for `backchannel index`.

## Connectors

Connectors are optional and sit outside the daemon: they run on their own schedule and
Backchannel works without them. `msgvault_connector` projects the WhatsApp store into a
synthetic Android `msgstore.db` so msgvault can import it alongside your mail.
See [CONNECTORS.md](CONNECTORS.md).
