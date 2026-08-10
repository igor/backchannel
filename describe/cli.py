"""Extract pending source-image OCR into image_text.db."""
import argparse
import logging
import os

import config
from datetime import datetime, timezone
from pathlib import Path

from derive import store as derive_store
from describe import extracts, store, text


log = logging.getLogger("backchannel.describe")
_SOURCES = ("whatsapp", "signal")


def _pick(env, canonical, default):
    return env.get(canonical) or default


def resolve_config(source: str, env) -> dict:
    root = Path(_pick(env, "BC_CORPUS_ROOT", os.path.expanduser("~/.local/share/backchannel/corpus")))
    backend = "bridge"
    wacli_store = None
    if source == "whatsapp":
        if config.resolve_backend(_pick(env, "BC_WHATSAPP_BACKEND", "bridge")) == "wacli":
            backend = "wacli"
            wacli_store = Path(_pick(env, "BC_WACLI_STORE", os.path.expanduser("~/.wacli"))).expanduser()
            store_db = wacli_store / "wacli.db"
            media_root = wacli_store / "media"
        else:
            store_db = Path(_pick(env, "BC_WHATSAPP_STORE", os.path.expanduser("~/store/messages.db")))
            media_root = Path(_pick(env, "BC_WHATSAPP_MEDIA", str(store_db.parent)))
    else:
        store_root = Path(_pick(env, "BC_SIGNAL_STORE_ROOT", os.path.expanduser("~/.local/share/backchannel/signal")))
        store_db = Path(_pick(env, "BC_SIGNAL_STORE", str(store_root / "messages.db")))
        media_root = Path(_pick(env, "BC_SIGNAL_MEDIA", str(store_root / "media")))
    return {
        "source": source,
        "store_db": store_db,
        "snapshot": root / ".derive" / source / "describe-snapshot.db",
        "image_text_db": root / "image_text.db",
        "media_root": media_root,
        "backend": backend,
        "wacli_store": wacli_store,
    }


def _result(rows):
    kept = [(value.strip(), confidence) for value, confidence in rows if value.strip()]
    values = [value for value, _confidence in kept]
    confidence = sum(item[1] for item in kept) / len(kept) if kept else 0.0
    full_text = "\n".join(values)
    document_like = len(values) >= 3 and len(full_text) >= 80 and confidence >= 0.5
    return full_text, len(values), confidence, document_like


def main(argv=None, env=None, recognize_fn=None) -> int:
    parser = argparse.ArgumentParser(prog="backchannel-describe")
    parser.add_argument("--source", required=True, choices=_SOURCES)
    args = parser.parse_args(argv)
    env = os.environ if env is None else env
    cfg = resolve_config(args.source, env)
    if not cfg["store_db"].exists():
        raise SystemExit(f"backchannel-describe: {cfg['source']} store DB not found at {cfg['store_db']}")
    recognize_fn = text.recognize if recognize_fn is None else recognize_fn
    if cfg["backend"] == "wacli":
        from derive import wacli
        wacli.project(cfg["wacli_store"], cfg["snapshot"])
    else:
        derive_store.snapshot_db(cfg["store_db"], cfg["snapshot"])
    source_conn = derive_store.connect_ro(cfg["snapshot"])
    extracts_conn = extracts.connect(cfg["image_text_db"])
    try:
        done = extracts.done_ids(extracts_conn, cfg["source"])
        counts = {"ok": 0, "empty": 0, "missing": 0, "failed": 0}
        now = datetime.now(timezone.utc).isoformat()
        for message_id, chat_jid, filename in store.image_messages(source_conn):
            if message_id in done:
                continue
            image_path = derive_store.media_path(cfg["media_root"], chat_jid, filename)
            if not filename or not image_path.exists():
                extracts.upsert(extracts_conn, cfg["source"], message_id, chat_jid, "", 0, 0.0, False, "apple-vision", "missing", now)
                counts["missing"] += 1
                continue
            try:
                full_text, line_count, mean_confidence, document_like = _result(recognize_fn(image_path))
            except text.VisionUnavailableError as exc:
                log.error("backchannel describe unavailable: %s", exc)
                break
            except Exception as exc:
                log.warning("describe failed for %s: %s", message_id, exc)
                extracts.upsert(extracts_conn, cfg["source"], message_id, chat_jid, "", 0, 0.0, False, "apple-vision", "failed", now)
                counts["failed"] += 1
                continue
            status = "ok" if full_text else "empty"
            extracts.upsert(extracts_conn, cfg["source"], message_id, chat_jid, full_text, line_count, mean_confidence, document_like, "apple-vision", status, now)
            counts[status] += 1
        log.info("backchannel describe %s: %d ok, %d empty, %d missing, %d failed", cfg["source"], counts["ok"], counts["empty"], counts["missing"], counts["failed"])
        return counts["ok"]
    finally:
        source_conn.close()
        extracts_conn.close()
