"""Project a wacli.db store into the bridge schema that derive reads.

wacli (https://wacli.sh) is a maintained Go CLI on whatsmeow whose local store wacli.db
covers the same data as the third-party whatsapp-mcp bridge, under different column names
and with integer unix-epoch timestamps. This module is the only place that knows wacli's
schema; it produces a bridge-schema SQLite that derive/store.py reads unchanged, so the
derivation pipeline is identical for both backends.

Read discipline follows wacli.sh/integrations.html: wacli.db is opened read-only via a
snapshot copy (the online-backup pattern Backchannel already uses), never with immutable=1,
and never written. session.db (keys) is never touched — the contacts this needs are in
wacli.db's own contacts table.
"""
from __future__ import annotations

import hashlib
import sqlite3
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from derive import store as derive_store


_BRIDGE_SCHEMA = """
CREATE TABLE messages (
    id TEXT, chat_jid TEXT, sender TEXT, content TEXT, timestamp TEXT,
    is_from_me INTEGER, media_type TEXT, filename TEXT
);
CREATE TABLE chats (jid TEXT PRIMARY KEY, name TEXT, last_message_time TEXT);
CREATE TABLE whatsmeow_contacts (their_jid TEXT, full_name TEXT, push_name TEXT);
CREATE TABLE whatsmeow_lid_map (lid TEXT, pn TEXT);
"""

_MSG_SELECT = (
    "SELECT rowid, msg_id, chat_jid, sender_jid, text, ts, from_me, "
    "media_type, filename, local_path, payload_purged_at FROM messages ORDER BY rowid"
)


def _wacli_db(store_dir) -> Path:
    return Path(store_dir) / "wacli.db"


def _local_dt(ts: int) -> datetime:
    # wacli stores UTC unix epoch. Convert to a local-aware datetime so derive's day
    # bucketing (dt.date()) matches the bridge's local-offset behaviour, and the ISO string
    # parse_ts consumes carries an explicit offset.
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).astimezone()


def _bare_sender(sender_jid: Optional[str]) -> str:
    # The bridge stores the bare phone in messages.sender; derive resolves names and chats
    # against the bare phone. wacli stores the full JID, so strip the host.
    if not sender_jid:
        return ""
    return sender_jid.split("@", 1)[0]


def _load_cursor(state_path: Path) -> Tuple[Optional[int], Optional[str]]:
    state = derive_store._load_state_json(Path(state_path))
    raw = state.get("wacli_rowid_cursor")
    return (int(raw) if raw is not None else None), state.get("wacli_cursor_anchor")


def _fingerprint(conn: sqlite3.Connection, upto_rowid: int) -> str:
    """Identity fingerprint of every row at or below a rowid: sha256 over (chat_jid,
    msg_id) in rowid order. Row identity never changes in place (deletions are in-place
    column updates and the rowid is the AUTOINCREMENT primary key, stable under VACUUM),
    so any mismatch means wacli.db was recreated — a single-row anchor could collide if a
    re-linked store happened to land the same message at the same rowid."""
    h = hashlib.sha256()
    for chat_jid, msg_id in conn.execute(
            "SELECT chat_jid, msg_id FROM messages WHERE rowid <= ? ORDER BY rowid",
            (upto_rowid,)):
        h.update(chat_jid.encode()); h.update(b"\x00")
        h.update(msg_id.encode()); h.update(b"\x00")
    return h.hexdigest()


def _snapshot_wacli(store_dir, dst: Path) -> None:
    # wacli sync's shutdown can transiently fail a concurrent mode=ro open with
    # SQLITE_CANTOPEN (14). Capture and derive run as separate daemon jobs and can overlap,
    # so a short retry resolves it here where msgvault's single attempt would not.
    last: Optional[sqlite3.OperationalError] = None
    for _ in range(3):
        try:
            derive_store.snapshot_db(_wacli_db(store_dir), dst)
            return
        except sqlite3.OperationalError as exc:
            last = exc
            time.sleep(0.2)
    assert last is not None
    raise last


def _build(store_dir, out_db: Path, track_dirty: bool, cursor: Optional[int],
           anchor: Optional[str] = None) -> Tuple[List[Tuple[str, date]], int, Optional[str]]:
    """Snapshot wacli.db read-only and project it into a bridge-schema SQLite at out_db.
    Returns (sorted dirty (chat_jid, local_date), max rowid seen, identity fingerprint of
    all rows). dirty is populated only when track_dirty is True; transcribe/describe pass
    False and ignore the return. A stored cursor is honoured only when the identity
    fingerprint of rows at or below it still matches: wacli.db recreated after a re-link
    restarts rowids, and a stale cursor would then skip new rows forever."""
    out_db = Path(out_db)
    out_db.parent.mkdir(parents=True, exist_ok=True)
    if out_db.exists():
        out_db.unlink()
    src_snap = out_db.with_name(out_db.name + ".wacli-src.db")
    _snapshot_wacli(store_dir, src_snap)
    src = sqlite3.connect(f"file:{src_snap}?mode=ro", uri=True)
    out = sqlite3.connect(str(out_db))
    try:
        if cursor is not None and anchor != _fingerprint(src, cursor):
            # wacli.db was recreated (re-link, new store): the identity prefix at or below
            # the stored cursor no longer matches what the cursor was saved against. Treat
            # every row as new — derive is idempotent, so the cost is one full re-derive
            # instead of silently skipping rows at or below the stale cursor.
            cursor = None
        out.executescript(_BRIDGE_SCHEMA)
        dirty = set()
        max_rowid = 0
        for (rowid, msg_id, chat_jid, sender_jid, text, ts, from_me,
             media_type, filename, local_path, purged) in src.execute(_MSG_SELECT):
            if rowid > max_rowid:
                max_rowid = rowid
            # Durable record: a purged payload is gone and was never derived, so skip it. A
            # tombstoned-but-not-purged row keeps its text as history; because a tombstone
            # does not change rowid or ts, an already-derived day is never revisited.
            if purged is not None:
                continue
            dt = _local_dt(ts)
            if track_dirty and (cursor is None or rowid > cursor):
                dirty.add((chat_jid, dt.date()))
            out.execute(
                "INSERT INTO messages (id, chat_jid, sender, content, timestamp, "
                "is_from_me, media_type, filename) VALUES (?,?,?,?,?,?,?,?)",
                (msg_id, chat_jid, _bare_sender(sender_jid), text or "", dt.isoformat(),
                 int(bool(from_me)), media_type or "", local_path or filename or ""),
            )
        for jid, name, last_ts in src.execute(
                "SELECT jid, COALESCE(name, ''), last_message_ts FROM chats"):
            last = _local_dt(last_ts).isoformat() if last_ts else ""
            out.execute("INSERT INTO chats (jid, name, last_message_time) VALUES (?,?,?)",
                        (jid, name, last))
        for their_jid, full, push in src.execute(
                "SELECT jid, COALESCE(full_name, ''), COALESCE(push_name, '') "
                "FROM contacts WHERE jid LIKE '%@s.whatsapp.net'"):
            out.execute("INSERT INTO whatsmeow_contacts (their_jid, full_name, push_name) "
                        "VALUES (?,?,?)", (their_jid, full, push))
        out.commit()
        fp = _fingerprint(src, max_rowid) if max_rowid else None
        return sorted(dirty), max_rowid, fp
    finally:
        out.close()
        src.close()
        try:
            src_snap.unlink()
        except FileNotFoundError:
            pass


def project(store_dir, out_db: Path) -> None:
    """Build a bridge-schema snapshot from wacli.db. For transcribe/describe, which only need
    to enumerate audio/image messages and resolve media via local_path."""
    _build(store_dir, out_db, track_dirty=False, cursor=None, anchor=None)


def project_for_derive(store_dir, out_db: Path, state_path: Path, rebuild: bool
                       ) -> Tuple[List[Tuple[str, date]], int, Optional[str]]:
    """Build the snapshot and return (dirty days, max rowid, anchor of that row) for
    derive's incremental scan. The rowid cursor is the authoritative incremental feed for
    wacli: messages arrive out of chronological order during history sync, so a timestamp
    watermark would miss backdated rows indefinitely. rebuild (or a first run with no
    cursor) derives everything and then advances the cursor to the current max. The anchor
    is persisted next to the cursor and re-checked on load, so a recreated wacli.db (whose
    rowids restart) triggers a full re-derive instead of a silent skip."""
    if rebuild:
        cursor, anchor = None, None
    else:
        cursor, anchor = _load_cursor(state_path)
    return _build(store_dir, out_db, track_dirty=True, cursor=cursor, anchor=anchor)
