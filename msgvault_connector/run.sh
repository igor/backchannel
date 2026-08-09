#!/bin/bash
# run.sh — scheduler wrapper: project the bridge store into a synthetic
# WhatsApp msgstore.db, then import it into msgvault.
#
# Two steps, one job:
#   1. python -m msgvault_connector   → <out>/msgstore.db + <out>/contacts.vcf
#   2. msgvault import-whatsapp <out>/msgstore.db --media-dir … --contacts …
# Both are idempotent: msgvault dedups on the WhatsApp key_id, so a re-run
# upserts in place. A failed run is repaired by the next one.
#
# Required:
#   BC_MSGVAULT_PHONE     your own number in E.164 form (msgvault's "me" identity)
# Optional:
#   BC_MSGVAULT_BIN       msgvault binary (default: msgvault on PATH)
#   BC_MSGVAULT_HOME      msgvault data dir; passed as --home when set. Set this
#                         whenever the daemon does not use the default home, or
#                         the CLI will start a SECOND daemon on the wrong archive.
#   BC_MSGVAULT_OUT       projection output dir (default: ~/msgvault-export)
#   BC_MSGVAULT_NAME      display name for the phone owner
#   BC_MSGVAULT_WRAPPER   heavy-job mutex prefix — wraps BOTH steps by
#                         re-exec'ing this script under it
#   BC_WHATSAPP_MEDIA     media root passed as --media-dir (default: ~/store)
#   BC_WHATSAPP_STORE, BC_WHATSAPP_CONTACTS, BC_TRANSCRIPTS_DB — source overrides
#                         for the projection (module defaults apply when unset)
#
# Keep the output dir on internal storage: launchd jobs can be TCC-blocked from
# writing to external volumes.
#
# This is a tracked, static script (NOT a rendered output): every host that runs
# the job needs it, including ones where rendered files do not survive a one-way
# sync. It self-locates the venv relative to the repo root (msgvault_connector/
# and .venv/ are siblings).
#
# Fired by your scheduler of choice (launchd, cron); not run by `backchannel daemon`.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$REPO/.venv/bin/python"
OUT="${BC_MSGVAULT_OUT:-$HOME/msgvault-export}"
STORE_ROOT="${BC_WHATSAPP_MEDIA:-$HOME/store}"
MSGVAULT="${BC_MSGVAULT_BIN:-msgvault}"

PHONE="${BC_MSGVAULT_PHONE:-}"
: "${PHONE:?set BC_MSGVAULT_PHONE to your own number in E.164 form (+…)}"

# Re-exec under the heavy-job mutex so the lock covers projection AND import.
WRAPPER="${BC_MSGVAULT_WRAPPER:-}"
if [ -n "$WRAPPER" ] && [ -z "${BC_MSGVAULT_LOCKED:-}" ]; then
  export BC_MSGVAULT_LOCKED=1
  # shellcheck disable=SC2086  # intentional word-split of the wrapper spec
  exec ${WRAPPER} /bin/bash "${BASH_SOURCE[0]}"
fi

"$PYTHON" -m msgvault_connector --out-dir "$OUT"

args=(import-whatsapp "$OUT/msgstore.db"
      --phone "$PHONE"
      --media-dir "$STORE_ROOT"
      --contacts "$OUT/contacts.vcf")
NAME="${BC_MSGVAULT_NAME:-}"
[ -n "$NAME" ] && args+=(--display-name "$NAME")
MV_HOME="${BC_MSGVAULT_HOME:-}"
[ -n "$MV_HOME" ] && args=(--home "$MV_HOME" "${args[@]}")

exec "$MSGVAULT" "${args[@]}"
