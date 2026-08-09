# Demo

This shows what a Backchannel corpus looks like without linking a real
WhatsApp or Signal account.

`run_demo.py` builds a small fake WhatsApp message store on disk (one
group, two direct chats, a handful of messages, including an image and a
voice note), points the real derive pipeline at that fake store, and
prints the Markdown files it generates. It cleans up after itself.

Every name, phone number, and group ID in the fixture data is invented.
None of it corresponds to a real account.

## Run it

From the repo root, with the project installed into a virtualenv:

```
python3 -m venv .venv
.venv/bin/pip install .
.venv/bin/python demo/run_demo.py
```

## What it does

1. Creates a temp directory and writes a fake WhatsApp `messages.db` into
   it, using the same table schema the WhatsApp bridge produces.
2. Sets `BC_WHATSAPP_STORE`, `BC_CORPUS_ROOT`, and `BC_DERIVE_WORK` to
   paths inside that temp directory, so nothing touches a real store.
3. Calls `derive.cli.main(["--source", "whatsapp", "--rebuild"])` — the
   same entry point `backchannel-derive` uses.
4. Prints each generated day-file (frontmatter plus message lines) to
   stdout.
5. Deletes the temp directory.

The script exits non-zero if derivation produces no Markdown.
