"""Run a single signal-cli receive poll, spool first, then replay."""
import argparse
import json
import logging
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from sources.signal import migrate, parser, spool, store

log = logging.getLogger("sig-bridge")


def _pick(env, canonical, default):
    return env.get(canonical) or default


def resolve_config(env):
    root = Path(_pick(env, "BC_SIGNAL_STORE_ROOT", os.path.expanduser("~/.local/share/backchannel/signal")))
    return {
        "root": root,
        "db": Path(_pick(env, "BC_SIGNAL_STORE", str(root / "messages.db"))),
        "account": _pick(env, "BC_SIGNAL_ACCOUNT", ""),
        "bin": _pick(env, "BC_SIGNAL_CLI_BIN", "signal-cli"),
        "signal_data": Path(_pick(
            env, "BC_SIGNAL_CLI_DATA", os.path.expanduser("~/.local/share/signal-cli/data"),
        )),
    }


def _metadata(binary, account, command):
    result = subprocess.run([binary, "-a", account, "--output=json", command], text=True, capture_output=True)
    if result.returncode:
        return {}
    try:
        data = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return {}
    rows = data if isinstance(data, list) else [data]
    if command == "listContacts":
        return {(row.get("uuid") or row.get("aci")): row.get("name") for row in rows if (row.get("uuid") or row.get("aci")) and row.get("name")}
    return {(row.get("id") or row.get("groupId")): row.get("name") for row in rows if (row.get("id") or row.get("groupId")) and row.get("name")}


def main(argv=None, env=None):
    args = argparse.ArgumentParser(prog="sig-bridge")
    args.add_argument("--repair-image-media-types", action="store_true")
    parsed = args.parse_args(argv)
    env = os.environ if env is None else env
    cfg = resolve_config(env)
    if parsed.repair_image_media_types:
        changed = migrate.reclassify_image_rows(cfg["db"])
        log.info("sig-bridge repaired %d image media types", changed)
        return 0
    if not cfg["account"]:
        raise SystemExit("sources.signal: BC_SIGNAL_ACCOUNT is required")
    received = subprocess.run([cfg["bin"], "-a", cfg["account"], "--output=json", "receive"], text=True, capture_output=True)
    if received.returncode:
        log.error("signal-cli receive failed: %s", received.stderr.strip())
        return 1
    now = datetime.now(timezone.utc)
    path, count = spool.append_fsynced(cfg["root"], received.stdout.splitlines(), now)
    contacts = _metadata(cfg["bin"], cfg["account"], "listContacts")
    groups = _metadata(cfg["bin"], cfg["account"], "listGroups")
    state_path = cfg["root"] / ".bridge-state.json"
    state = store.load_state(state_path)
    offsets = state.get("spool_offsets", {})
    # Replay every spool file with unconsumed bytes, not just today's — a parse
    # failure before midnight would otherwise strand the previous day's messages
    # once capture rolls onto a new daily file.
    parsed = skipped = 0
    try:
        for spool_file in sorted((cfg["root"] / "spool").glob("*.jsonl")):
            start = offsets.get(str(spool_file), 0)
            if spool_file.stat().st_size <= start:
                continue
            result = parser.replay(spool_file, cfg["db"], contacts, groups, cfg["root"] / "media", cfg["signal_data"], offset=start)
            state = store.mark_success(state, spool_file, result.offset, now)
            parsed += result.parsed
            skipped += result.skipped
    finally:
        # Persist whatever progress was made. Without this, one unexpected exception on a
        # later file discards the offset advances of every earlier file in the same run, and
        # they are reparsed on every cycle until the broken file is fixed.
        store.save_state(state_path, state)
    log.info("sig-bridge done: %d spooled, %d parsed, %d skipped", count, parsed, skipped)
    return 0