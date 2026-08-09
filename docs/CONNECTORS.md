# Connectors

## What a connector is

A connector reads a Backchannel source store and writes it out in a format some
other tool expects. Connectors are optional and sit outside `backchannel daemon`.
They run on their own schedule (launchd, cron, or by hand) and Backchannel is
fully functional without them. Most users will not need one.

## msgvault_connector

msgvault is a separate, third-party tool that archives email. It can also import
WhatsApp history, but only in the schema Android WhatsApp itself uses for its
local database, `msgstore.db`. Backchannel's WhatsApp store uses its own schema,
so the two are not directly compatible.

`msgvault_connector` closes that gap: it reads Backchannel's WhatsApp store and
writes a synthetic `msgstore.db` (plus a `contacts.vcf`) in the exact shape
msgvault's stock `import-whatsapp` command expects. msgvault then imports that
file as if it came from an Android phone.

This is for people who already run msgvault and want their WhatsApp history
alongside their email in it. If you don't use msgvault, this connector does
nothing for you — skip it.

## How it works

The connector opens a read-only snapshot of the bridge's `messages.db` (and,
if present, the whatsmeow contacts store and the transcripts database). It
never mutates the source store — every read goes through a snapshot copy, and
each build is a full rebuild of the output directory, not an incremental
patch to the source.

From that snapshot it builds three synthetic tables (`jid`, `chat`, `message`)
plus the empty companion tables msgvault's reader expects to find even when
unused (`message_quoted`, `message_add_on`, `message_add_on_reaction`,
`group_participants`, `jid_map`). WhatsApp media types map to WhatsApp's
integer message types (`image` → 1, `video` → 2, `audio` → 5 as a voice note,
`document` → 13). Voice-note transcripts, when available, are appended into
the message body so msgvault indexes the spoken text along with everything
else. Contact names come out as a vCard file, keyed by E.164 phone number,
which msgvault matches against.

The output is idempotent: msgvault dedups on WhatsApp's `key_id`, so
re-running the connector and re-importing just upserts existing rows in
place. A failed or partial run is repaired by the next successful one — there
is no watermark or incremental state to corrupt.

## Running it

Two steps, run in order:

```
python -m msgvault_connector --out-dir <out-dir>
msgvault import-whatsapp <out-dir>/msgstore.db --phone <you> --media-dir <media-root> --contacts <out-dir>/contacts.vcf
```

The first step writes `msgstore.db` and `contacts.vcf` into `<out-dir>`. The
second is msgvault's own stock importer, unmodified.

`msgvault_connector/run.sh` wraps both steps for a scheduler (launchd or
cron; not `backchannel daemon`). It requires `BC_MSGVAULT_PHONE` and exits
immediately if that variable is unset. Fire it on whatever cadence suits your
own msgvault import schedule.

## Configuration

All variables are read by `run.sh`, which then invokes the connector and
`msgvault import-whatsapp`. `BC_MSGVAULT_PHONE` is the only required one.

| Variable | Default | Purpose |
| --- | --- | --- |
| `BC_MSGVAULT_PHONE` | none — required | your own number in E.164 form; msgvault's "me" identity. `run.sh` exits if unset. |
| `BC_MSGVAULT_BIN` | `msgvault` (on `PATH`) | msgvault binary to invoke |
| `BC_MSGVAULT_HOME` | none | msgvault data directory, passed as `--home`. Set this whenever the daemon you already run uses a non-default home — otherwise the CLI starts a second daemon against the wrong archive. |
| `BC_MSGVAULT_OUT` | `~/msgvault-export` | projection output directory |
| `BC_MSGVAULT_NAME` | none | display name for the phone owner, passed as `--display-name` when set |
| `BC_MSGVAULT_WRAPPER` | none | heavy-job mutex prefix; wraps both steps by re-executing `run.sh` under it |
| `BC_WHATSAPP_MEDIA` | `~/store` | media root, passed as `--media-dir` |
| `BC_WHATSAPP_STORE` | `~/store/messages.db` | bridge `messages.db` override |
| `BC_WHATSAPP_CONTACTS` | `~/store/whatsapp.db` | whatsmeow store override, for sender names and the lid-to-phone map |
| `BC_TRANSCRIPTS_DB` | `~/.local/share/backchannel/corpus/transcripts.db` | voice-note transcripts override |

The last three are not passed as flags by `run.sh` itself — they are read
directly by the connector module (`msgvault_connector/cli.py`) from its own
process environment, so setting them before `run.sh` runs still reaches the
projection step.

## Writing another connector

Follow the same shape: read the source store read-only (snapshot first, never
touch the live store or spool), write out a foreign format the target tool
already understands, and keep the whole thing outside `backchannel daemon` on
its own schedule.
