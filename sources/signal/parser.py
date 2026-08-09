"""Parse only already-spooled signal-cli envelopes into the local store."""
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from sources.signal import spool, store


@dataclass
class ReplayResult:
    parsed: int = 0
    skipped: int = 0
    offset: int = 0


def _timestamp_ms(envelope, data):
    value = data.get("timestamp") or envelope.get("timestamp")
    return int(value) if value is not None else None


def _timestamp_text(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).astimezone().isoformat(sep=" ", timespec="seconds")


def _identity(envelope):
    return envelope.get("sourceUuid") or envelope.get("destinationUuid") or ""


def _event(envelope):
    data = envelope.get("dataMessage") or {}
    if not data and (envelope.get("syncMessage") or {}).get("sentMessage"):
        data = envelope["syncMessage"]["sentMessage"]
        return data, True
    return data, False


def _content(data):
    if data.get("reaction"):
        return f"[signal reaction {data['reaction'].get('emoji', '')} of {data['reaction'].get('targetSentTimestamp', '')}]"
    if data.get("remoteDelete"):
        return f"[signal remote-delete of {data['remoteDelete'].get('targetSentTimestamp', '')}]"
    if data.get("editMessage"):
        return f"[signal edit of {data['editMessage'].get('targetSentTimestamp', '')}] {data.get('message', '')}".strip()
    info = data.get("groupInfo") or {}
    if info.get("type") == "UPDATE":
        return f"[signal group update] {info.get('name', '')}".strip()
    return data.get("message", "")


def _chat(envelope, data, contacts, groups, chat_aci):
    """Resolve the chat a message belongs to. `chat_aci` is the OTHER party's UUID --
    never the archive's own account -- so an inbound message and the outbound reply to
    it land in the same DM chat instead of splitting into two."""
    info = data.get("groupInfo") or {}
    group_id = info.get("groupId")
    if group_id:
        jid = f"{group_id}@group.signal"
        return jid, info.get("name") or groups.get(group_id) or group_id[:8]
    return f"{chat_aci}@signal", contacts.get(chat_aci) or envelope.get("sourceName") or chat_aci[:8]


def _attachment(data, signal_data):
    attachments = data.get("attachments") or []
    if not attachments:
        return "", "", None
    first = attachments[0] or {}
    stored = first.get("storedFilename") or first.get("filename") or ""
    source = Path(stored)
    if not source.is_absolute():
        source = Path(signal_data) / source
    name = source.name
    content_type = first.get("contentType") or ""
    lower_name = name.lower()
    if content_type.startswith("image/") or lower_name.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic")):
        kind = "image"
    elif content_type.startswith("audio/") or lower_name.endswith((".aac", ".m4a")):
        kind = "audio"
    else:
        kind = "document"
    return kind, name, source


def replay(path, db_path, contacts, groups, media_root=None, signal_data=None, fail_after=None, offset=0):
    """Replay complete lines idempotently. A transaction rolls back on parser crash."""
    conn = store.connect(db_path)
    result = ReplayResult()
    try:
        with conn:
            for aci, name in contacts.items():
                conn.execute("INSERT INTO chats (jid,name) VALUES (?,?) ON CONFLICT(jid) DO UPDATE SET name=excluded.name", (f"{aci}@signal", name))
            for group_id, name in groups.items():
                conn.execute("INSERT INTO chats (jid,name) VALUES (?,?) ON CONFLICT(jid) DO UPDATE SET name=excluded.name", (f"{group_id}@group.signal", name))
            for _position, raw in spool.read_lines(path, offset):
                try:
                    envelope = json.loads(raw).get("envelope", {})
                    data, from_me = _event(envelope)
                    # sender == who wrote it (own account on outbound sync);
                    # chat == the other party, so both directions share one chat_jid.
                    sender_aci = _identity(envelope)
                    chat_aci = sender_aci
                    if from_me:
                        chat_aci = data.get("destinationUuid") or envelope.get("destinationUuid") or sender_aci
                    ms = _timestamp_ms(envelope, data)
                    if not sender_aci or not chat_aci or ms is None:
                        result.skipped += 1
                        continue
                    jid, name = _chat(envelope, data, contacts, groups, chat_aci)
                    kind = "reaction" if data.get("reaction") else "delete" if data.get("remoteDelete") else "edit" if data.get("editMessage") else "message"
                    mid = f"{sender_aci}:{ms}:{kind}"
                    media_type, filename, source = _attachment(data, signal_data or ".")
                    if filename and media_root:
                        if source is None or not source.exists():
                            filename = ""
                        else:
                            try:
                                target = Path(media_root) / jid / source.name
                                target.parent.mkdir(parents=True, exist_ok=True)
                                shutil.copy2(source, target)
                            except OSError:
                                filename = ""
                    conn.execute("INSERT INTO chats (jid,name) VALUES (?,?) ON CONFLICT(jid) DO UPDATE SET name=excluded.name", (jid, name))
                    if not from_me:
                        # Name row so the renderer can resolve a group sender's display
                        # name. Skipped outbound: it would mint a phantom self-DM chat.
                        sender_name = contacts.get(sender_aci) or envelope.get("sourceName") or sender_aci[:8]
                        conn.execute("INSERT INTO chats (jid,name) VALUES (?,?) ON CONFLICT(jid) DO UPDATE SET name=excluded.name", (f"{sender_aci}@signal", sender_name))
                    conn.execute("INSERT OR IGNORE INTO messages VALUES (?,?,?,?,?,?,?,?)", (mid, jid, sender_aci, _content(data), _timestamp_text(ms), int(from_me), media_type, filename))
                    result.parsed += 1
                    if fail_after is not None and result.parsed == fail_after:
                        raise RuntimeError("injected parser crash")
                except (ValueError, TypeError, json.JSONDecodeError):
                    result.skipped += 1
        result.offset = Path(path).stat().st_size
        return result
    finally:
        conn.close()