"""Build and atomically write per-(chat, day) markdown files."""
import os
import re
import tempfile
from datetime import date
from pathlib import Path
from typing import Dict, List
from urllib.parse import urlparse
import yaml

from derive.model import Message, ChatView, Chat
from derive.render import format_line, sender_display

_FOLDER = {"dm": "dms", "group": "groups"}
_URL_RE = re.compile(r"https?://[^\s<>\"]+")


def day_file_path(corpus_root: Path, view: ChatView, day: date) -> Path:
    return Path(corpus_root) / view.source / _FOLDER[view.type] / view.slug / f"{day.isoformat()}.md"


def _serialize_fm(fm: dict) -> str:
    y = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True, default_flow_style=False)
    return f"---\n{y.rstrip()}\n---\n"


def _frontmatter(view: ChatView, day: date, messages: List[Message], image_text=None) -> dict:
    text = "\n".join(m.content for m in messages)
    urls = _URL_RE.findall(text)
    domains = sorted({urlparse(u).netloc.lower() for u in urls if urlparse(u).netloc})
    image_entries = []
    for message in messages:
        record = (image_text or {}).get(message.id)
        if message.media_type != "image" or not record or not record["text"]:
            continue
        value = record["text"]
        entry = {"message_id": message.id, "text": value[:2000]}
        if len(value) > 2000:
            entry["truncated"] = True
        image_entries.append(entry)
    return {
        "type": view.type, "source": view.source, "jid": view.jid, "name": view.name,
        "slug": view.slug, "date": day.isoformat(), "message_count": len(messages),
        "first_message": messages[0].timestamp.isoformat(),
        "last_message": messages[-1].timestamp.isoformat(),
        "first_message_id": messages[0].id, "last_message_id": messages[-1].id,
        "has_links": len(urls) > 0, "link_count": len(urls), "domains": domains,
        "has_media": any(m.media_type for m in messages),
        "has_image_text": bool(image_entries), "image_text": image_entries,
        "tags": [view.source],
    }


def build_day_file(view: ChatView, day: date, messages: List[Message],
                   chats: Dict[str, Chat], transcripts=None, image_text=None,
                   owner_label: str = "You", names: Dict[str, str] = None) -> str:
    fm = _serialize_fm(_frontmatter(view, day, messages, image_text))
    header = f"\n# {view.name} — {day.isoformat()}\n\n"
    lines = "".join(
        format_line(m, sender_display(m, view, chats, names, owner_label), transcripts, image_text)
        for m in messages
    )
    return fm + header + lines


def atomic_write(target: Path, content: str) -> None:
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    except Exception:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
