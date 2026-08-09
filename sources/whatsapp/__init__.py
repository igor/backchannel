"""WhatsApp source — deliberately almost empty, and not a stub.

WhatsApp is fully supported. There is no Python capture code here because there is nothing
for it to do: WhatsApp has no local API, so capture is performed by a separate Go bridge
process that maintains the linked-device session and writes messages into a SQLite store.
`backchannel daemon` launches that binary and supervises it; everything downstream reads the
store read-only.

The asymmetry with `sources/signal/` is therefore real but expected. Signal capture is
implemented in this repository because `signal-cli` is a local command that has to be driven,
spooled and replayed. WhatsApp capture is a process to keep alive.

Where WhatsApp actually lives:

- `daemon.py`   `_run_whatsapp_capture` — starts and supervises the bridge
- `derive/`     reads the bridge's store into the Markdown corpus
- `transcribe/` and `describe/` — voice notes and image OCR for WhatsApp media
- `heartbeat/`  checks the source is still capturing

The store schema the bridge must provide is documented in `docs/SETUP.md`; any bridge that
satisfies it will work.
"""
