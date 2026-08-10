"""Read-only access to a snapshot of the bridge's messages.db."""
import sqlite3
from datetime import datetime, timezone, date
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from derive.model import Chat, Message
from derive import __version__


def snapshot_db(src: Path, dst: Path) -> None:
    """Online .backup of a (possibly live) SQLite DB. Consistent under concurrent writes."""
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    src_conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    try:
        dst_conn = sqlite3.connect(str(dst))
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
    finally:
        src_conn.close()


def connect_ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def media_path(media_root: Path, chat_jid: str, filename: str) -> Path:
    """Resolve a media file. wacli projects an absolute local_path into filename; the
    bridge stores a basename under <media_root>/<chat_jid>/<filename>. An absolute
    filename wins, so both backends resolve through one rule with no backend flag."""
    f = Path(filename)
    return f if f.is_absolute() else Path(media_root) / chat_jid / f


def parse_ts(raw: str) -> datetime:
    """Parse the bridge format, e.g. '2026-06-15 15:26:28+02:00'."""
    s = (raw or "").strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def get_chats(conn: sqlite3.Connection) -> Dict[str, Chat]:
    rows = conn.execute("SELECT jid, COALESCE(name, '') FROM chats").fetchall()
    return {jid: Chat(jid=jid, name=name) for jid, name in rows}


def scan_affected(conn: sqlite3.Connection,
                  since: Optional[datetime]) -> Tuple[List[Tuple[str, date]], Optional[datetime]]:
    """(sorted (chat_jid, local_date) with messages newer than `since`, max UTC seen).
    `since` is aware UTC, or None for everything. Full scan — cheap at this corpus size,
    and robust against per-row offset/DST quirks that lexical SQL comparison would miss."""
    rows = conn.execute("SELECT chat_jid, timestamp FROM messages").fetchall()
    affected: Set[Tuple[str, date]] = set()
    max_utc: Optional[datetime] = None
    for chat_jid, ts_raw in rows:
        try:
            dt = parse_ts(ts_raw)
        except (ValueError, TypeError):
            continue
        utc = dt.astimezone(timezone.utc)
        if max_utc is None or utc > max_utc:
            max_utc = utc
        if since is None or utc > since:
            affected.add((chat_jid, dt.date()))
    return sorted(affected), max_utc


def scan_sidecar_dirty(conn: sqlite3.Connection, transcripts_db: Path, image_text_db: Path,
                        source: str, transcripts_since: Optional[int],
                        image_text_since: Optional[int]
                        ) -> Tuple[List[Tuple[str, date]], Optional[int], Optional[int]]:
    """(sorted (chat_jid, local_date) whose transcript/OCR sidecar row changed after its
    own watermark, max transcripts revision seen, max image_text revision seen). Enrichment
    can land after the message watermark has already moved past a day's messages, so
    scan_affected's message-timestamp watermark alone would silently drop it. transcripts.db
    and image_text.db are independently written pipelines, so each gets its own cursor —
    sharing one would let a lagging pipeline's rows fall behind the other's watermark and
    never be picked up. The cursor is each row's `revision` (a per-write monotonic counter),
    not its wall-clock timestamp: a whole enrichment run stamps every row with the same
    timestamp, so a timestamp-based watermark would mark the latest batch's day dirty on
    every scan forever. `revision` increases on every write (insert or update), so rows
    already covered by the watermark are excluded while still-later writes are detected."""
    id_to_chat_day: Dict[str, Tuple[str, date]] = {}
    for message_id, chat_jid, ts_raw in conn.execute("SELECT id, chat_jid, timestamp FROM messages"):
        try:
            dt = parse_ts(ts_raw)
        except (ValueError, TypeError):
            continue
        id_to_chat_day[message_id] = (chat_jid, dt.date())

    affected: Set[Tuple[str, date]] = set()
    maxes: Dict[str, Optional[int]] = {"transcripts": None, "image_text": None}

    def _scan(key: str, db_path: Path, table: str, since: Optional[int]) -> None:
        db_path = Path(db_path)
        if not db_path.exists():
            return
        sconn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            try:
                rows = sconn.execute(
                    f"SELECT message_id, revision FROM {table} WHERE source = ?", (source,)).fetchall()
            except sqlite3.Error:
                return
        finally:
            sconn.close()
        for message_id, revision in rows:
            if revision is None:
                continue
            if maxes[key] is None or revision > maxes[key]:
                maxes[key] = revision
            if since is not None and revision <= since:
                continue
            chat_day = id_to_chat_day.get(message_id)
            if chat_day is not None:
                affected.add(chat_day)

    _scan("transcripts", transcripts_db, "transcripts", transcripts_since)
    _scan("image_text", image_text_db, "image_text", image_text_since)
    return sorted(affected), maxes["transcripts"], maxes["image_text"]


def messages_for_chat_day(conn: sqlite3.Connection, chat_jid: str, day: date) -> List[Message]:
    rows = conn.execute(
        "SELECT id, chat_jid, sender, COALESCE(content,''), timestamp, is_from_me, "
        "COALESCE(media_type,''), COALESCE(filename,'') FROM messages WHERE chat_jid = ?",
        (chat_jid,)).fetchall()
    out: List[Message] = []
    for r in rows:
        try:
            dt = parse_ts(r[4])
        except (ValueError, TypeError):
            continue
        if dt.date() != day:
            continue
        out.append(Message(id=r[0], chat_jid=r[1], sender=r[2], content=r[3], timestamp=dt,
                           is_from_me=bool(r[5]), media_type=r[6], filename=r[7]))
    out.sort(key=lambda m: m.timestamp)
    return out


def _load_state_json(path: Path) -> dict:
    path = Path(path)
    if not path.exists():
        return {}
    return __import__("json").loads(path.read_text())


def load_watermark(path: Path) -> Optional[datetime]:
    s = _load_state_json(path).get("watermark_utc")
    return datetime.fromisoformat(s) if s else None


def load_transcripts_watermark(path: Path) -> Optional[int]:
    return _load_state_json(path).get("sidecar_transcripts_watermark_rev")


def load_image_text_watermark(path: Path) -> Optional[int]:
    return _load_state_json(path).get("sidecar_image_text_watermark_rev")


def save_watermark(path: Path, dt_utc: datetime, transcripts_rev: Optional[int] = None,
                    image_text_rev: Optional[int] = None, wacli_rowid: Optional[int] = None,
                    wacli_anchor: Optional[str] = None) -> None:
    from derive.corpus import atomic_write  # late import avoids a cycle
    state = _load_state_json(path)
    state["watermark_utc"] = dt_utc.isoformat()
    if transcripts_rev is not None:
        state["sidecar_transcripts_watermark_rev"] = transcripts_rev
    if image_text_rev is not None:
        state["sidecar_image_text_watermark_rev"] = image_text_rev
    if wacli_rowid is not None:
        state["wacli_rowid_cursor"] = wacli_rowid
    if wacli_anchor is not None:
        state["wacli_cursor_anchor"] = wacli_anchor
    state["derive_version"] = __version__
    atomic_write(Path(path), __import__("json").dumps(state, indent=2) + "\n")


def _pick_names(rows) -> Dict[str, str]:
    """Reduce (phone, full_name, push_name, pri) rows to {phone: name}.
    full_name beats push_name; first-seen wins within a tier. Rows must be
    pri-ordered (direct @s.whatsapp.net before lid path) so the result is
    deterministic when a phone appears via both paths."""
    out: Dict[str, tuple] = {}  # phone -> (name, is_full)
    for phone, full, push, _pri in rows:
        full = (full or "").strip()
        push = (push or "").strip()
        cand, is_full = (full, True) if full else (push, False)
        if not cand:
            continue
        cur = out.get(phone)
        if cur is None or (is_full and not cur[1]):  # set, or upgrade push->full
            out[phone] = (cand, is_full)
    return {p: name for p, (name, _is_full) in out.items()}


_NAMES_SQL = """
SELECT substr(their_jid, 1, instr(their_jid, '@') - 1) AS phone, full_name, push_name, 0 AS pri
FROM whatsmeow_contacts WHERE their_jid LIKE '%@s.whatsapp.net'
UNION ALL
SELECT m.pn AS phone, c.full_name, c.push_name, 1 AS pri
FROM whatsmeow_lid_map m JOIN whatsmeow_contacts c ON c.their_jid = m.lid || '@lid'
ORDER BY pri
"""


def load_sender_names(contacts_db: Path) -> Dict[str, str]:
    """{bare_phone -> name} from the whatsmeow store (an already-snapshotted copy).
    Resolves both the direct @s.whatsapp.net path and the lid_map -> @lid path.
    {} if the file is absent or the whatsmeow_* tables are missing (fresh bridge)."""
    contacts_db = Path(contacts_db)
    if not contacts_db.exists():
        return {}
    conn = connect_ro(contacts_db)
    try:
        rows = conn.execute(_NAMES_SQL).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        conn.close()
    return _pick_names(rows)


def group_sender_coverage(conn: sqlite3.Connection, names: Dict[str, str]) -> float:
    """Message-weighted fraction of received group-message senders present in `names`.
    1.0 when there are no group messages. The runnable guard against join breakage."""
    rows = conn.execute(
        "SELECT sender, COUNT(*) FROM messages "
        "WHERE chat_jid LIKE '%@g.us' AND is_from_me = 0 "
        "AND sender IS NOT NULL AND sender <> '' GROUP BY sender").fetchall()
    total = sum(n for _s, n in rows)
    if total == 0:
        return 1.0
    resolved = sum(n for s, n in rows if s in names)
    return resolved / total


def load_transcripts(db_path: Path, source: str) -> Dict[str, str]:
    """Return successful transcript text for one source; {} when no DB exists."""
    db_path = Path(db_path)
    if not db_path.exists():
        return {}
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        try:
            rows = conn.execute(
                "SELECT message_id, text FROM transcripts "
                "WHERE source = ? AND status = 'ok' AND text <> ''",
                (source,),
            ).fetchall()
        except sqlite3.Error:
            if source != "whatsapp":
                return {}
            rows = conn.execute(
                "SELECT message_id, text FROM transcripts WHERE status = 'ok' AND text <> ''"
            ).fetchall()
    finally:
        conn.close()
    return {message_id: text for message_id, text in rows}


def load_image_text(db_path: Path, source: str) -> Dict[str, dict]:
    """Return non-empty successful OCR records for one source; {} when absent."""
    db_path = Path(db_path)
    if not db_path.exists():
        return {}
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT message_id, text, document_like FROM image_text "
            "WHERE source = ? AND status = 'ok' AND text <> ''",
            (source,),
        ).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        conn.close()
    return {message_id: {"text": value, "document_like": bool(document_like)} for message_id, value, document_like in rows}
