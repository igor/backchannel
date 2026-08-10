# Backchannel

Backchannel keeps your own WhatsApp history on your Mac as plain Markdown, and
keeps it current.

It builds on [wacli](https://wacli.sh), which mirrors your WhatsApp into a local
SQLite database. Backchannel turns that mirror into something an agent can
actually read: a Markdown corpus where voice notes arrive as transcripts,
screenshots arrive as text, and a semantic index answers questions instead of
keyword matches. wacli gives your terminal WhatsApp; Backchannel gives your
agent a memory.

The files are the interface. There is no database to query and no API to call:
an agent with access to your disk reads the corpus directly, and `qmd` gives it
semantic search across every conversation. Backchannel's job is to keep that
substrate accurate and current.

Everything runs on your machine. No cloud service, no account, no telemetry.

## What it does

Backchannel runs one supervisor process, `backchannel daemon`, that owns a
fixed schedule of jobs:

- **capture** — runs a bounded `wacli sync` every 5 minutes
- **derive** — turns captured messages into the Markdown corpus every 15
  minutes
- **transcribe** — transcribes voice notes with whisper.cpp, hourly
- **heartbeat** — checks capture is still writing, every 6 hours
- **index** — rebuilds the local qmd search collection nightly

Each job runs in its own thread. A failure in one job does not stop the
others, and the same job never runs twice at once.

### Image OCR

Image OCR (Apple Vision) is off by default and enabled with
`BC_DESCRIBE_ENABLED=1`. It is the newest capability and the least proven over
long runs; `backchannel describe --source whatsapp` works by hand either way.

## Install

```bash
brew install openclaw/tap/wacli
python3 -m venv .venv
.venv/bin/pip install .
backchannel setup
```

`backchannel setup` creates the config file if it doesn't exist, reports any
missing dependencies, and downloads the small Whisper model.

## Quick start

Pair wacli as a linked device (QR in the terminal, scanned from your phone):

```bash
wacli auth
```

Point Backchannel at the wacli backend and start the daemon:

```bash
export BC_WHATSAPP_BACKEND=wacli
backchannel daemon
```

Once the corpus has been indexed, ask it something:

```bash
qmd query "what did we decide about the invoice" -c backchannel -n 3
```

To see what the corpus looks like without linking an account, run the demo. It
builds a small fabricated message store, runs the real derivation over it, and
prints the resulting Markdown:

```bash
.venv/bin/python demo/run_demo.py
```

## How your data is stored

Backchannel draws a hard line between durable records and derivations. wacli's
store and its downloaded media are the durable record. Everything else — the
Markdown corpus, `transcripts.db`, the qmd search index — is a derivation,
rebuilt at any time with `backchannel derive --source whatsapp --rebuild`.

The corpus lives at `~/.local/share/backchannel/corpus`, organized as
`corpus/whatsapp/{groups,dms}/<chat>/<date>.md`. Media that wacli has not
downloaded yet is reported as missing and picked up once it exists; `wacli
media backfill` fetches it in bulk, and `wacli media retry` recovers files
whose CDN links have expired, as long as your phone still has them.

## The account you link is yours

wacli pairs as a linked device over the WhatsApp Web protocol via
[whatsmeow](https://github.com/tulir/whatsmeow). That is an unofficial client,
it is against WhatsApp's terms of service, and accounts have been banned for
unofficial-client use. The risk is low for a device that only receives — the
reported bans cluster around automated sending — but it is not zero, and it is
your account. Backchannel itself never sends: there is no send path in the
codebase.

## Configuration

Configuration is entirely `BC_*` environment variables or the equivalent keys
in `~/.config/backchannel/config.json`. A non-empty environment value wins
over the config file, which wins over the built-in default. Full reference:
[docs/CONFIGURATION.md](docs/CONFIGURATION.md).

## Requirements

- macOS (image OCR uses Apple's Vision framework)
- Python 3.11+
- [wacli](https://wacli.sh)
- `ffmpeg`
- `whisper-cpp`
- `qmd`

An older backend that reads a self-built whatsmeow bridge remains supported
for installs that already run one; see
[docs/SETUP.md](docs/SETUP.md#appendix-the-bridge-backend).

## Status

This started as a personal tool and is now released publicly. Interfaces,
config keys, and defaults may still change.

The tree also contains a Signal source. It runs in production privately but is
not yet documented or supported here; it becomes part of a later release.

## License

MIT. See [LICENSE](LICENSE).
