# Setup guide

## Prerequisites

Install Python 3.11+, `signal-cli`, `ffmpeg`, `whisper-cpp`, `qrencode`, and qmd with
your package manager.

Signal works with stock `signal-cli` and needs nothing else.

## The WhatsApp bridge

WhatsApp capture needs a separate bridge process, because there is no supported local
WhatsApp API. Backchannel does not ship one and does not talk to it over a socket: the bridge
maintains a linked-device session and writes messages into a SQLite store, and Backchannel
reads that store read-only.

Any bridge satisfying the contract below will work. This was developed against `whatsapp-mcp`,
a Go program built on [whatsmeow](https://github.com/tulir/whatsmeow). Two copies exist and
they are separate repositories rather than a fork pair:

- [lharries/whatsapp-mcp](https://github.com/lharries/whatsapp-mcp) — the original and the
  better known, but not pushed to since July 2025.
- [verygoodplugins/whatsapp-mcp](https://github.com/verygoodplugins/whatsapp-mcp) — actively
  maintained, and what the development machine builds from.

Build the `whatsapp-bridge` binary from whichever you prefer and point
`BC_WHATSAPP_BRIDGE_BIN` at it.

### What Backchannel requires of the store

A SQLite database with these tables and columns. Extra columns are ignored.

| Table | Columns read |
| --- | --- |
| `messages` | `id`, `chat_jid`, `sender`, `content`, `timestamp`, `is_from_me`, `media_type`, `filename` |
| `chats` | `jid`, `name`, `last_message_time` |
| `whatsmeow_contacts` | `their_jid`, `full_name`, `push_name` |
| `whatsmeow_lid_map` | `lid`, `pn` |

`whatsmeow_contacts` and `whatsmeow_lid_map` are whatsmeow's own tables and resolve display
names; without them chats fall back to their JID. Downloaded media is expected at
`<media root>/<chat_jid>/<filename>`, which is what `BC_WHATSAPP_MEDIA` points at.

### Operational notes

**Working directory.** The bridge resolves its session relative to its working directory, so it
must always be started from the same one. Started elsewhere it finds no session and asks to be
linked again by QR. `backchannel daemon` sets this for you, derived from `BC_WHATSAPP_STORE`.

**Expect to patch the bridge.** A stock build is not guaranteed to work, and the machine this
was developed on runs a patched one. Two failures have been seen, both in the bridge rather
than in Backchannel:

- A persistent HTTP **405 on connect**, tied to the pinned whatsmeow version. The bridge
  authenticates and then never connects. Check the whatsmeow version before suspecting the
  linked session.
- HTTP **403 on media download**, which needs a fast-path patch in whatsmeow. Messages still
  capture; media silently does not arrive, and OCR and voice transcription then have nothing to
  work on.

If text arrives but media never does, this is the first thing to check — Backchannel will
report those messages as `missing` media indefinitely and is behaving correctly when it does.

## Install Backchannel

```bash
# From the checked-out Backchannel repository:
python3 -m venv .venv
.venv/bin/pip install -e .
backchannel setup
```

Setup creates the JSON configuration if needed, reports missing commands, and downloads
the small Whisper model. Use `backchannel setup --model large` only when the larger model
is intentionally wanted.

Set source settings in the config file or environment. For WhatsApp, set
`BC_WHATSAPP_BRIDGE_BIN` to the bridge binary. For Signal, link a device:

```bash
backchannel link signal
```

## Run and verify

```bash
backchannel daemon
```

In another terminal, verify after a message arrives:

```bash
qmd query "fixture query" -c backchannel -n 3
```

The daemon owns all core timing. Do not install core launchd plists, render scripts, or
start individual scheduled copies alongside it. Connectors run on their own schedule and
are outside this setup — see [CONNECTORS.md](CONNECTORS.md).
