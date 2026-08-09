"""Transcribe pending audio notes into the shared transcripts database."""
import argparse
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from derive import store as derive_store
from transcribe import store, transcripts, whisper

log = logging.getLogger("backchannel.transcribe")
_SOURCES = ("whatsapp", "signal")


def _pick(env, canonical, default):
    return env.get(canonical) or default


def resolve_config(source: str, env) -> dict:
    root = Path(_pick(env, "BC_CORPUS_ROOT", os.path.expanduser("~/.local/share/backchannel/corpus")))
    if source == "whatsapp":
        store_db = Path(_pick(env, "BC_WHATSAPP_STORE", os.path.expanduser("~/store/messages.db")))
        media_root = Path(_pick(env, "BC_WHATSAPP_MEDIA", str(store_db.parent)))
        model = _pick(env, "BC_WHISPER_MODEL", os.path.expanduser("~/whisper-models/ggml-large-v3-turbo.bin"))
    else:
        store_root = Path(_pick(env, "BC_SIGNAL_STORE_ROOT", os.path.expanduser("~/.local/share/backchannel/signal")))
        store_db = Path(_pick(env, "BC_SIGNAL_STORE", str(store_root / "messages.db")))
        media_root = Path(_pick(env, "BC_SIGNAL_MEDIA", str(store_root / "media")))
        model = _pick(env, "BC_WHISPER_MODEL", os.path.expanduser("~/whisper-models/ggml-large-v3-turbo.bin"))
    return {
        "source": source,
        "store_db": store_db,
        "snapshot": root / ".derive" / source / "transcribe-snapshot.db",
        "transcripts_db": root / "transcripts.db",
        "media_root": media_root,
        "model": model,
        "whisper_bin": _pick(env, "BC_WHISPER_BIN", "whisper-cli"),
        "ffmpeg_bin": _pick(env, "BC_FFMPEG_BIN", "ffmpeg"),
    }


def main(argv=None, env=None, transcribe_fn=None) -> int:
    parser = argparse.ArgumentParser(prog="backchannel-transcribe")
    parser.add_argument("--source", required=True, choices=_SOURCES)
    args = parser.parse_args(argv)
    env = os.environ if env is None else env
    cfg = resolve_config(args.source, env)
    if transcribe_fn is None:
        transcribe_fn = lambda p: whisper.transcribe(p, cfg["model"], cfg["whisper_bin"], cfg["ffmpeg_bin"])
    if not cfg["store_db"].exists():
        raise SystemExit(f"backchannel-transcribe: {cfg['source']} store DB not found at {cfg['store_db']}")

    derive_store.snapshot_db(cfg["store_db"], cfg["snapshot"])
    conn = derive_store.connect_ro(cfg["snapshot"])
    audio = store.audio_messages(conn)
    tconn = transcripts.connect(cfg["transcripts_db"])
    done = transcripts.done_ids(tconn, cfg["source"])
    now = datetime.now(timezone.utc).isoformat()
    model_name = os.path.basename(cfg["model"])

    counts = {"ok": 0, "empty": 0, "missing": 0, "failed": 0}
    for mid, chat_jid, filename in audio:
        if mid in done:
            continue
        ogg = cfg["media_root"] / chat_jid / filename
        if not filename or not ogg.exists():
            transcripts.upsert(tconn, cfg["source"], mid, chat_jid, "", "", "", "missing", now); counts["missing"] += 1; continue
        try:
            text, lang = transcribe_fn(ogg)
        except Exception as e:  # binary failure, etc. — never abort the whole run
            log.warning("transcribe failed for %s: %s", mid, e)
            transcripts.upsert(tconn, cfg["source"], mid, chat_jid, "", "", "", "failed", now); counts["failed"] += 1; continue
        status = "ok" if text.strip() else "empty"
        transcripts.upsert(tconn, cfg["source"], mid, chat_jid, text.strip(), lang, model_name, status, now)
        counts[status] += 1

    log.info(
        "backchannel transcribe %s: %d ok, %d empty, %d missing, %d failed",
        cfg["source"], counts["ok"], counts["empty"], counts["missing"], counts["failed"],
    )
    return counts["ok"]
