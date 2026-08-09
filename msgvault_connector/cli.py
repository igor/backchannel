"""CLI: project the bridge store into a synthetic msgstore.db for msgvault."""
import argparse
import os
from pathlib import Path

from msgvault_connector.project import build

DEFAULT_STORE = os.environ.get("BC_WHATSAPP_STORE", os.path.expanduser("~/store/messages.db"))
DEFAULT_CONTACTS = os.environ.get("BC_WHATSAPP_CONTACTS", os.path.expanduser("~/store/whatsapp.db"))
DEFAULT_TRANSCRIPTS = os.environ.get("BC_TRANSCRIPTS_DB", os.path.expanduser("~/.local/share/backchannel/corpus/transcripts.db"))
DEFAULT_OUT = "~/msgvault-export"   # keep in step with run.sh's BC_MSGVAULT_OUT default


def _expand(value: str) -> Path:
    return Path(os.path.expanduser(value))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="msgvault_connector",
        description="Project the bridge store into a synthetic WhatsApp "
                    "msgstore.db that msgvault's import-whatsapp can read.")
    parser.add_argument("--store", default=DEFAULT_STORE,
                        help="bridge messages.db (default: %(default)s)")
    parser.add_argument("--contacts-db", default=DEFAULT_CONTACTS,
                        help="whatsmeow store for sender names (default: %(default)s)")
    parser.add_argument("--transcripts-db", default=DEFAULT_TRANSCRIPTS,
                        help="voice-note transcripts (default: %(default)s)")
    parser.add_argument("--out-dir", default=os.environ.get("BC_MSGVAULT_OUT", DEFAULT_OUT),
                        help="output directory (default: %(default)s)")
    args = parser.parse_args(argv)

    counts = build(_expand(args.store), _expand(args.out_dir),
                   contacts_db=_expand(args.contacts_db),
                   transcripts_db=_expand(args.transcripts_db))
    print(f"chats={counts.chats} messages={counts.messages} media={counts.media} "
          f"transcripts={counts.transcripts} contacts={counts.contacts} "
          f"skipped_chats={counts.skipped_chats} collisions={counts.collisions}")
    return 0
