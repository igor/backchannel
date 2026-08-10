# Setup guide

## Prerequisites

```bash
brew install openclaw/tap/wacli ffmpeg whisper-cpp
```

`qmd` provides the semantic index; install it from its own instructions.
Python 3.11+ comes with macOS or Homebrew.

## Link WhatsApp through wacli

wacli pairs as a linked device, the same slot WhatsApp Web uses. Pairing needs
your phone once; capture afterwards does not.

```bash
wacli auth
```

Scan the QR from WhatsApp → Settings → Linked devices → Link a device. The
code rotates every ~20 seconds, so scan promptly. `wacli auth status` confirms
the session. The bootstrap sync starts immediately and pulls what WhatsApp
offers — recent history for every chat, often reaching back years.

Two wacli commands are worth running once after the bootstrap:

```bash
wacli media backfill            # download media for already-synced messages
wacli media retry               # recover media whose CDN links expired (phone online)
```

Older messages beyond the bootstrap can be requested from your phone with
`wacli history backfill`; see [wacli's history docs](https://wacli.sh/history.html).

## Install Backchannel

```bash
# From the checked-out Backchannel repository:
python3 -m venv .venv
.venv/bin/pip install -e .
backchannel setup
```

Setup creates the JSON configuration if needed, reports missing commands, and
downloads the small Whisper model. Use `backchannel setup --model large` only
when the larger model is intentionally wanted.

Select the wacli backend:

```bash
export BC_WHATSAPP_BACKEND=wacli
```

`BC_WACLI_STORE` defaults to `~/.wacli`; set it if wacli uses a custom store
directory. Backchannel reads `wacli.db` read-only through a snapshot copy and
never touches `session.db`, following wacli's own
[companion-tool guidance](https://wacli.sh/integrations.html).

## Run and verify

```bash
backchannel daemon
```

The capture job runs `wacli sync --once --presence-mode quiet` every five
minutes: bounded, non-interactive, and without broadcasting your presence to
contacts on every tick. In another terminal, verify after a message arrives:

```bash
qmd query "fixture query" -c backchannel -n 3
```

The daemon owns all core timing. Do not install core launchd plists, render
scripts, or start individual scheduled copies alongside it. Connectors run on
their own schedule and are outside this setup — see
[CONNECTORS.md](CONNECTORS.md).

## Keeping the link alive

WhatsApp deactivates a linked device that stays offline for weeks, and
re-linking needs the QR ceremony again. Short gaps are safe: messages queue
server-side and deliver on reconnect, so an overnight or weekend sleep fills
itself in. For a machine that sleeps, `pmset repeat wakeorpoweron` schedules a
daily wake with no extra software.

## Appendix: the bridge backend

Before wacli, Backchannel read a separate whatsmeow bridge process that
maintained its own linked-device session and SQLite store. That backend
remains the default (`BC_WHATSAPP_BACKEND=bridge`) so existing installs keep
working, and any bridge satisfying the store contract below still works.
Development used `whatsapp-mcp` builds; expect a stock build to need
whatsmeow patching (HTTP 405 on connect, HTTP 403 on media download).

Point `BC_WHATSAPP_BRIDGE_BIN` at the bridge binary. The bridge resolves its
session relative to its working directory; `backchannel daemon` sets this,
derived from `BC_WHATSAPP_STORE`.

### The store contract

A SQLite database with these tables and columns. Extra columns are ignored.

| Table | Columns read |
| --- | --- |
| `messages` | `id`, `chat_jid`, `sender`, `content`, `timestamp`, `is_from_me`, `media_type`, `filename` |
| `chats` | `jid`, `name`, `last_message_time` |
| `whatsmeow_contacts` | `their_jid`, `full_name`, `push_name` |
| `whatsmeow_lid_map` | `lid`, `pn` |

`whatsmeow_contacts` and `whatsmeow_lid_map` resolve display names; without
them chats fall back to their JID. Downloaded media is expected at
`<media root>/<chat_jid>/<filename>`, which is what `BC_WHATSAPP_MEDIA`
points at. If text arrives but media never does, the whatsmeow 403 patch is
the first thing to check — Backchannel reports those messages as `missing`
media indefinitely and is behaving correctly when it does.
