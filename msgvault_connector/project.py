"""Project a bridge messages.db into a synthetic Android WhatsApp msgstore.db.

msgvault's `import-whatsapp` reads Android WhatsApp's schema and nothing else, so
this module writes that schema from the bridge store and lets the stock importer do
the work.

Read-only with respect to the bridge: every source is snapshotted first.
"""
import mimetypes
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from derive.store import (connect_ro, load_sender_names, load_transcripts,
                          parse_ts, snapshot_db)

# bridge media_type -> WhatsApp message_type int. 'audio' maps to 5 (voice_note),
# not 3 (audio): every audio row this bridge stores is a .ogg push-to-talk note.
MESSAGE_TYPE = {"": 0, "image": 1, "video": 2, "audio": 5, "document": 13}

# Status posts are not correspondence; msgvault rejects the JID anyway.
SKIP_CHATS = {"status@broadcast"}

SCHEMA = """
CREATE TABLE jid (_id INTEGER PRIMARY KEY, user TEXT, server TEXT, raw_string TEXT);
CREATE TABLE chat (_id INTEGER PRIMARY KEY, jid_row_id INTEGER, subject TEXT,
                   group_type INTEGER DEFAULT 0, hidden INTEGER DEFAULT 0,
                   sort_timestamp INTEGER DEFAULT 0);
CREATE TABLE message (_id INTEGER PRIMARY KEY, chat_row_id INTEGER, from_me INTEGER,
                      key_id TEXT, sender_jid_row_id INTEGER, timestamp INTEGER,
                      message_type INTEGER, text_data TEXT,
                      status INTEGER DEFAULT 0, starred INTEGER DEFAULT 0);
CREATE TABLE message_media (message_row_id INTEGER, mime_type TEXT, media_caption TEXT,
                            file_size INTEGER, file_path TEXT, width INTEGER,
                            height INTEGER, media_duration INTEGER);
-- Present but empty: the bridge captures none of this. group_participants MUST
-- exist even empty -- msgvault's reader has no missing-table guard for it, and
-- with the table present it derives group members from observed senders instead.
CREATE TABLE message_quoted (message_row_id INTEGER, key_id TEXT);
CREATE TABLE message_add_on (_id INTEGER PRIMARY KEY, parent_message_row_id INTEGER,
                             sender_jid_row_id INTEGER);
CREATE TABLE message_add_on_reaction (message_add_on_row_id INTEGER, reaction TEXT,
                                      sender_timestamp INTEGER);
CREATE TABLE group_participants (gjid TEXT, jid TEXT, admin INTEGER DEFAULT 0);
CREATE TABLE jid_map (lid_row_id INTEGER, jid_row_id INTEGER);
"""


@dataclass
class Counts:
    chats: int = 0
    messages: int = 0
    media: int = 0
    transcripts: int = 0
    contacts: int = 0
    skipped_chats: int = 0
    collisions: int = 0


def _epoch_ms(raw) -> Optional[int]:
    """Bridge timestamp text -> epoch milliseconds. None when unparseable."""
    try:
        return int(parse_ts(raw).timestamp() * 1000)
    except (ValueError, TypeError):
        return None


def _lid_map(contacts_db: Optional[Path]) -> Dict[str, str]:
    """{lid -> phone} from the whatsmeow store; {} when absent or unreadable."""
    if contacts_db is None or not Path(contacts_db).exists():
        return {}
    conn = connect_ro(Path(contacts_db))
    try:
        return {lid: pn for lid, pn in
                conn.execute("SELECT lid, pn FROM whatsmeow_lid_map")}
    except sqlite3.Error:
        return {}
    finally:
        conn.close()


def _phone_jid(sender: str) -> str:
    """A bridge sender is a bare phone; tolerate one that already carries a server."""
    return sender if "@" in sender else f"{sender}@s.whatsapp.net"


def _write_vcf(path: Path, names: Dict[str, str]) -> int:
    """vCard 3.0 per contact. msgvault matches on E.164, so every TEL gets a '+'."""
    lines = []
    for phone, name in sorted(names.items()):
        clean = " ".join(str(name).split())
        if not clean or not phone.isdigit():
            continue
        lines += ["BEGIN:VCARD", "VERSION:3.0", f"FN:{clean}",
                  f"TEL:+{phone}", "END:VCARD"]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return len(lines) // 5


def _project(src: sqlite3.Connection, dst: sqlite3.Connection,
             lid_to_phone: Dict[str, str], transcripts: Dict[str, str]) -> Counts:
    counts = Counts()
    jid_ids: Dict[str, int] = {}

    def jid_id(raw_string: str) -> int:
        if raw_string not in jid_ids:
            user, _, server = raw_string.partition("@")
            jid_ids[raw_string] = len(jid_ids) + 1
            dst.execute(
                "INSERT INTO jid (_id, user, server, raw_string) VALUES (?,?,?,?)",
                (jid_ids[raw_string], user, server, raw_string))
        return jid_ids[raw_string]

    chat_rows: Dict[str, int] = {}
    for jid, name, last_ts in src.execute(
            "SELECT jid, COALESCE(name,''), COALESCE(last_message_time,'') FROM chats"):
        if jid in SKIP_CHATS:
            counts.skipped_chats += 1
            continue
        raw = jid
        if jid.endswith("@lid"):
            phone = lid_to_phone.get(jid[: -len("@lid")])
            if not phone:
                counts.skipped_chats += 1
                continue
            raw = f"{phone}@s.whatsapp.net"
        server = raw.partition("@")[2]
        # Channels have no 'g.us' server but are broadcast groups, not DMs.
        group_type = 1 if server in ("g.us", "newsletter") else 0
        chat_row_id = len(chat_rows) + 1
        dst.execute(
            "INSERT INTO chat (_id, jid_row_id, subject, group_type, hidden, "
            "sort_timestamp) VALUES (?,?,?,?,0,?)",
            (chat_row_id, jid_id(raw), name or None, group_type,
             _epoch_ms(last_ts) or 0))
        chat_rows[jid] = chat_row_id
        counts.chats += 1

    seen_keys = set()
    msg_row_id = 0
    for (mid, chat_jid, sender, content, ts_raw, from_me, media_type, filename,
         file_length) in src.execute(
            "SELECT id, chat_jid, COALESCE(sender,''), COALESCE(content,''), "
            "timestamp, COALESCE(is_from_me,0), COALESCE(media_type,''), "
            "COALESCE(filename,''), file_length FROM messages ORDER BY timestamp, id"):
        chat_row_id = chat_rows.get(chat_jid)
        if chat_row_id is None:
            continue
        ts = _epoch_ms(ts_raw)
        if ts is None:
            continue

        # The bridge keys on (id, chat_jid); msgvault keys on key_id alone. A
        # collision is emitted under a suffixed key rather than dropped, so no
        # message is lost and the anomaly stays visible.
        key_id = mid
        if key_id in seen_keys:
            key_id = f"{mid}-{chat_jid}"
            counts.collisions += 1
            print(f"msgvault_connector: key_id {mid!r} appears in more than one chat; "
                  f"emitting {key_id!r}", file=sys.stderr)
        seen_keys.add(key_id)

        text = content
        if media_type == "audio":
            transcript = transcripts.get(mid)
            if transcript:
                text = f"{content}\n\n🎙 {transcript}" if content else f"🎙 {transcript}"
                counts.transcripts += 1

        msg_row_id += 1
        dst.execute(
            "INSERT INTO message (_id, chat_row_id, from_me, key_id, "
            "sender_jid_row_id, timestamp, message_type, text_data) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (msg_row_id, chat_row_id, 1 if from_me else 0, key_id,
             jid_id(_phone_jid(sender)) if sender else None, ts,
             MESSAGE_TYPE.get(media_type, 0), text or None))
        counts.messages += 1

        if filename:
            dst.execute(
                "INSERT INTO message_media (message_row_id, mime_type, media_caption, "
                "file_size, file_path, width, height, media_duration) "
                "VALUES (?,?,NULL,?,?,NULL,NULL,NULL)",
                (msg_row_id, mimetypes.guess_type(filename)[0], file_length,
                 f"{chat_jid}/{filename}"))
            counts.media += 1

    return counts


def build(store_db, out_dir, contacts_db=None, transcripts_db=None) -> Counts:
    """Write <out_dir>/msgstore.db and <out_dir>/contacts.vcf. Full rebuild.

    Idempotent by design: msgvault dedups on key_id, so re-importing the output
    upserts in place and the job needs no watermark of its own.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    snap = out_dir / ".snap-messages.db"
    snapshot_db(Path(store_db), snap)

    contacts_snap = None
    if contacts_db is not None and Path(contacts_db).exists():
        contacts_snap = out_dir / ".snap-whatsapp.db"
        snapshot_db(Path(contacts_db), contacts_snap)

    lid_to_phone = _lid_map(contacts_snap)
    transcripts = load_transcripts(Path(transcripts_db), "whatsapp") if transcripts_db else {}

    out_path = out_dir / "msgstore.db"
    if out_path.exists():
        out_path.unlink()

    src = connect_ro(snap)
    dst = sqlite3.connect(str(out_path))
    try:
        # msgvault opens this file with 'mode=ro&_journal_mode=WAL'. On a
        # rollback-journal database that PRAGMA is a write and the import dies
        # with "attempt to write a readonly database"; a real msgstore.db is
        # already WAL, so upstream never hits it. Set WAL here to match.
        dst.execute("PRAGMA journal_mode=WAL")
        dst.executescript(SCHEMA)
        counts = _project(src, dst, lid_to_phone, transcripts)
        dst.commit()
    finally:
        dst.close()
        src.close()

    names = load_sender_names(contacts_snap) if contacts_snap else {}
    counts.contacts = _write_vcf(out_dir / "contacts.vcf", names)
    return counts
