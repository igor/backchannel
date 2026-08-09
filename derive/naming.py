"""Stateless chat identity: slug, type, collision-free slug map. No persisted registry."""
import re
from collections import defaultdict
from typing import Dict, List, Optional
from derive.model import Chat

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(name: str, maxlen: int = 40) -> str:
    s = _SLUG_RE.sub("-", (name or "").lower()).strip("-")
    return s[:maxlen]


def chat_type(source: str, jid: str) -> Optional[str]:
    if source == "whatsapp":
        if jid.endswith("@s.whatsapp.net"):
            return "dm"
        if jid.endswith("@g.us"):
            return "group"
    elif source == "signal":
        if jid.endswith("@signal"):
            return "dm"
        if jid.endswith("@group.signal"):
            return "group"
    return None


def resolve_slugs(source: str, chats: Dict[str, Chat]) -> Dict[str, str]:
    buckets: Dict[str, List[str]] = defaultdict(list)
    for jid, chat in chats.items():
        if chat_type(source, jid) is None:
            continue
        base = slugify(chat.name) or slugify(jid.split("@", 1)[0]) or "chat"
        buckets[base].append(jid)
    out: Dict[str, str] = {}
    for base, jids in buckets.items():
        if len(jids) == 1:
            out[jids[0]] = base
        else:
            for jid in jids:
                suffix = jid.split("@", 1)[0]
                out[jid] = f"{base}-{suffix[:8] if source == 'signal' else suffix}"
    return out
