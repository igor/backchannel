# Backchannel

Backchannel archives your own WhatsApp and Signal message history on your Mac,
into plain Markdown you own.

It is for people who want a durable, local, searchable copy of their own chat
history. It reads the accounts you already have and writes files to your disk.
Everything it does runs on your machine.

The two sources do not cost the same to set up. Signal works with a stock
`signal-cli` and one linking step. WhatsApp has no local API, so it needs a
separate Go bridge process that you build yourself, and a stock build usually
needs patching before media downloads work. If that is more than you want to
take on, Signal alone is a complete setup. See
[The WhatsApp bridge](docs/SETUP.md#the-whatsapp-bridge).

## What it does

Backchannel runs one supervisor process, `backchannel daemon`, that owns a
fixed schedule of core jobs per source (WhatsApp, Signal):

- **capture** — pulls new messages from each source every 5 minutes (a Go
  bridge for WhatsApp, `signal-cli` receive/spool/replay for Signal)
- **derive** — turns the captured messages into a Markdown corpus every 15
  minutes
- **transcribe** — transcribes voice notes with whisper.cpp, hourly
- **heartbeat** — checks each source is still capturing, every 6 hours
- **index** — builds a local qmd search collection over the corpus, nightly

Each job runs in its own thread. A failure in one job does not stop the
others, and the same job never runs twice at once.

### Image OCR

`backchannel daemon` schedules image OCR only when `BC_DESCRIBE_ENABLED` is
set to `1`, `true`, `yes`, or `on`. OCR is the newest capability and the least
proven over long runs, so an install that nobody is watching does not run it by
default. `backchannel describe --source whatsapp` works by hand whether or not
the setting is enabled.

No cloud service, no account, no telemetry. Everything happens on-device.

## Install

From source:

```bash
python3 -m venv .venv
.venv/bin/pip install .
backchannel setup
```

`backchannel setup` creates the config file if it doesn't exist, reports any
missing dependencies, and downloads the small Whisper model.

### Homebrew

A tap is coming. Once it exists, install will be:

```bash
brew install backchannel
```

That command does not work yet — install from source until the tap ships.

## See the output first

To see what the corpus looks like without linking an account, run the demo. It
builds a small fabricated message store, runs the real derivation over it, and
prints the resulting Markdown:

```bash
.venv/bin/python demo/run_demo.py
```

## Quick start

Link a Signal device:

```bash
backchannel link signal
```

Point Backchannel at a built WhatsApp bridge binary (see
[docs/SETUP.md](docs/SETUP.md) for where to get it):

```bash
export BC_WHATSAPP_BRIDGE_BIN=/path/to/whatsapp-bridge
```

Then start the daemon:

```bash
backchannel daemon
```

Once the corpus has been indexed, search it:

```bash
qmd query "dinner plans" -c backchannel -n 3
```

## How your data is stored

Backchannel draws a hard line between durable records and derivations.

The source SQLite stores (one per source) and their downloaded media are the
durable record. Everything else — the Markdown corpus, `transcripts.db`, the
qmd search index — is a derivation, rebuilt from the source stores at any
time with `backchannel derive --rebuild`. Never delete or rewrite a source
store as a shortcut; rebuilds only touch derived output.

By default:

- corpus and transcripts: `~/.local/share/backchannel/corpus`
- WhatsApp store: `~/store/messages.db`
- Signal store: `~/.local/share/backchannel/signal/messages.db`

The Markdown corpus is organized per source, under `corpus/<source>/{groups,dms}/...`.

Optional connectors can hand the archive to other tools. There is one connector,
and most people will not need it; see [docs/CONNECTORS.md](docs/CONNECTORS.md).

## Configuration

Configuration is entirely `BC_*` environment variables or the equivalent keys
in `~/.config/backchannel/config.json`, created by `backchannel setup`. A
non-empty environment value wins over the config file, which wins over the
built-in default. Full reference: [docs/CONFIGURATION.md](docs/CONFIGURATION.md).

## Requirements

- macOS (image OCR uses Apple's Vision framework, which is macOS-only)
- Python 3.11+
- `signal-cli`
- `ffmpeg`
- `whisper-cpp`
- `qmd`
- `qrencode`
- A separately built WhatsApp bridge binary, if WhatsApp capture is wanted; read
  [The WhatsApp bridge](docs/SETUP.md#the-whatsapp-bridge) first, as a stock build
  usually needs patching

## Status

This started as a personal tool and is now released publicly. Interfaces,
config keys, and defaults may still change.

## License

MIT. See [LICENSE](LICENSE).
