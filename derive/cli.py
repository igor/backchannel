"""Derive one source store into a namespaced Backchannel Markdown corpus."""
import argparse
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from derive import store
from derive.corpus import atomic_write, build_day_file, day_file_path
from derive.model import ChatView
from derive.naming import chat_type, resolve_slugs, slugify

log = logging.getLogger("backchannel.derive")
_FLOOR_YEAR = 2009
_SOURCES = ("whatsapp", "signal")


@dataclass
class Config:
    source: str
    store_db: Path
    snapshot_db: Path
    corpus_root: Path
    state_path: Path
    media_root: Path
    contacts_db: Path | None
    contacts_snapshot: Path | None


def _pick(env, canonical, default):
    return env.get(canonical) or default


def resolve_config(source: str, env) -> Config:
    root = Path(_pick(env, "BC_CORPUS_ROOT", os.path.expanduser("~/.local/share/backchannel/corpus")))
    if source == "whatsapp":
        store_db = Path(_pick(env, "BC_WHATSAPP_STORE", os.path.expanduser("~/store/messages.db")))
        media_root = Path(_pick(env, "BC_WHATSAPP_MEDIA", str(store_db.parent)))
        contacts_db = Path(_pick(env, "BC_WHATSAPP_CONTACTS", str(store_db.parent / "whatsapp.db")))
    else:
        store_root = _pick(env, "BC_SIGNAL_STORE_ROOT", os.path.expanduser("~/.local/share/backchannel/signal"))
        store_db = Path(_pick(env, "BC_SIGNAL_STORE", str(Path(store_root) / "messages.db")))
        media_root = Path(_pick(env, "BC_SIGNAL_MEDIA", str(Path(store_root) / "media")))
        contacts_db = None
    work = Path(_pick(env, "BC_DERIVE_WORK", str(root / ".derive"))) / source
    return Config(source, store_db, work / "snapshot.db", root, work / "state.json", media_root,
                  contacts_db, work / "contacts.db" if contacts_db else None)


def main(argv=None, env=None) -> int:
    parser = argparse.ArgumentParser(prog="backchannel-derive")
    parser.add_argument("--source", required=True, choices=_SOURCES)
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    env = os.environ if env is None else env
    cfg = resolve_config(args.source, env)
    if not cfg.store_db.exists():
        raise SystemExit(f"backchannel-derive: {cfg.source} store DB not found at {cfg.store_db}")

    store.snapshot_db(cfg.store_db, cfg.snapshot_db)
    conn = store.connect_ro(cfg.snapshot_db)
    try:
        chats = store.get_chats(conn)
        names = {}
        if cfg.contacts_db and cfg.contacts_snapshot and cfg.contacts_db.exists():
            store.snapshot_db(cfg.contacts_db, cfg.contacts_snapshot)
            names = store.load_sender_names(cfg.contacts_snapshot)
        slugs = resolve_slugs(cfg.source, chats)
        since = None if args.rebuild else store.load_watermark(cfg.state_path)
        transcripts_since = None if args.rebuild else store.load_transcripts_watermark(cfg.state_path)
        image_text_since = None if args.rebuild else store.load_image_text_watermark(cfg.state_path)
        affected, max_utc = store.scan_affected(conn, since)
        transcripts_db = cfg.corpus_root / "transcripts.db"
        image_text_db = cfg.corpus_root / "image_text.db"
        sidecar_affected, max_transcripts_rev, max_image_text_rev = store.scan_sidecar_dirty(
            conn, transcripts_db, image_text_db, cfg.source, transcripts_since, image_text_since)
        affected = sorted(set(affected) | set(sidecar_affected))
        transcripts = store.load_transcripts(transcripts_db, cfg.source)
        image_text = store.load_image_text(image_text_db, cfg.source)
        written = skipped = 0
        for jid, day in affected:
            kind = chat_type(cfg.source, jid)
            if kind is None:
                skipped += 1
                continue
            name = chats[jid].name if jid in chats and chats[jid].name else jid.split("@", 1)[0]
            view = ChatView(cfg.source, jid, kind, name, slugs.get(jid) or slugify(jid.split("@", 1)[0]) or "chat")
            messages = [m for m in store.messages_for_chat_day(conn, jid, day) if m.timestamp.year >= _FLOOR_YEAR]
            if not messages:
                continue
            text = build_day_file(view, day, messages, chats, transcripts, image_text, names=names)
            path = day_file_path(cfg.corpus_root, view, day)
            if args.dry_run:
                log.info("would write %s (%d messages)", path, len(messages))
            else:
                atomic_write(path, text)
            written += 1
        watermark = max_utc if max_utc is not None else since
        transcripts_watermark = max_transcripts_rev if max_transcripts_rev is not None else transcripts_since
        image_text_watermark = max_image_text_rev if max_image_text_rev is not None else image_text_since
        if not args.dry_run and watermark is not None:
            store.save_watermark(cfg.state_path, watermark, transcripts_watermark, image_text_watermark)
        log.info("backchannel derive %s: %d written, %d skipped", cfg.source, written, skipped)
        return written
    finally:
        conn.close()
