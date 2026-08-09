"""Render store rows into canonical Backchannel markdown lines."""
from typing import Dict
from derive.model import Message, ChatView, Chat


def media_placeholder(media_type: str, filename: str = "") -> str:
    if media_type == "image":
        return "[image]"
    if media_type == "video":
        return "[video]"
    if media_type == "audio":
        return f"[voice note · {filename}]" if filename else "[voice note]"
    if media_type == "document":
        return f"[document · {filename}]" if filename else "[document]"
    return f"[{media_type}]"


def sender_display(msg: Message, view: ChatView, chats: Dict[str, Chat],
                   names: Dict[str, str] = None, owner_label: str = "You") -> str:
    if msg.is_from_me:
        return owner_label
    if view.type == "dm":
        return view.name
    resolved = (names or {}).get(msg.sender)
    if resolved:
        return resolved
    if view.source == "whatsapp":
        c = chats.get(f"{msg.sender}@s.whatsapp.net")
        if c and c.name and c.name != msg.sender:
            return c.name
        return f"+{msg.sender}" if msg.sender.isdigit() else msg.sender
    else:
        c = chats.get(f"{msg.sender}@signal")
        if c and c.name and c.name != msg.sender:
            return c.name
        return msg.sender[:8]


def _truncate_image_text(value: str) -> str:
    collapsed = " ".join(value.split())
    if len(collapsed) <= 200:
        return collapsed
    return collapsed[:200].rsplit(" ", 1)[0] + "…"


def format_line(msg: Message, display: str, transcripts=None, image_text=None) -> str:
    hhmm = msg.timestamp.strftime("%H:%M")
    body = msg.content.strip()
    if not body and msg.media_type:
        if msg.media_type == "audio":
            transcript = (transcripts or {}).get(msg.id)
            body = f"🎙 {transcript}" if transcript else media_placeholder(msg.media_type, msg.filename)
        elif msg.media_type == "image":
            record = (image_text or {}).get(msg.id)
            body = f"🖼 {_truncate_image_text(record['text'])}" if record and record["document_like"] else media_placeholder(msg.media_type, msg.filename)
        else:
            body = media_placeholder(msg.media_type, msg.filename)
    return f"**{hhmm} — {display}**: {body}<!-- m:{msg.id} -->\n"
