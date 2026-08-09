# Architecture

## Durable records and derivations

Backchannel keeps a WhatsApp store and a Signal store separate because their capture
semantics differ. Both expose the same SQLite schema to the downstream source-aware
pipeline. The stores and downloaded media are durable; the Markdown corpus,
`transcripts.db`, qmd collection, and private-consumer output are derivations.

```text
WhatsApp bridge  -> whatsapp/messages.db -┐
                                           ├-> derive -> corpus/<source>/{groups,dms}/...
Signal signal-cli -> signal/messages.db --┘              -> transcripts.db
                                                            -> qmd collection: backchannel
```

## Runtime boundary

`backchannel daemon` is one long-running standard-library process. It owns
source capture (five minutes), derive (15 minutes), transcription (hourly), heartbeat
(six hours), and nightly indexing. Each job is a thread; failure is isolated, a running
job is not started twice, and SIGTERM waits for in-flight work before exit.

WhatsApp capture runs the Go bridge binary directly, with stdin at `/dev/null` and no
tty, so the bridge stays in daemon mode instead of starting its REPL. Signal capture
runs its existing receive/spool/replay implementation. Derive and transcribe keep their
existing `main()` functions. When `BC_TRANSCRIBE_WRAPPER` is non-empty, the daemon
prefixes the existing transcribe module command with that mutex command.

## Configuration and state

`config.py` resolves `BC_*` settings: environment first, then the config file, then a
portable default. The default corpus root is `~/.local/share/backchannel/corpus`; derive
watermarks live at `.derive/<source>/state.json`; heartbeat writes
`WARNING-<source>.md`; shared transcripts are keyed by `(source, message_id)`.

## Consumer boundary

Consumers read the corpus and the source stores but are not daemon jobs. They run on their
own schedule, and Backchannel works without them. `msgvault_connector` is the one that ships
here; see [CONNECTORS.md](CONNECTORS.md).
