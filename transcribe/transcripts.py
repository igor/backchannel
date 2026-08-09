"""The shared transcript database, namespaced by capture source."""
import sqlite3
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS transcripts (
    source TEXT NOT NULL,
    message_id TEXT NOT NULL,
    chat_jid TEXT,
    text TEXT,
    lang TEXT,
    model TEXT,
    status TEXT,
    transcribed_at TEXT,
    revision INTEGER,
    PRIMARY KEY (source, message_id)
);
"""


def _migrate_legacy(conn) -> None:
    columns = [row[1] for row in conn.execute("PRAGMA table_info(transcripts)")]
    if not columns:
        return
    if "source" not in columns:
        conn.executescript(
            "ALTER TABLE transcripts RENAME TO transcripts_legacy;"
            + _SCHEMA
            + "INSERT INTO transcripts (source, message_id, chat_jid, text, lang, model, status, transcribed_at) "
              "SELECT 'whatsapp', message_id, chat_jid, text, lang, model, status, transcribed_at "
              "FROM transcripts_legacy;"
            + "DROP TABLE transcripts_legacy;"
        )
        columns = [row[1] for row in conn.execute("PRAGMA table_info(transcripts)")]
    if "revision" not in columns:
        conn.execute("ALTER TABLE transcripts ADD COLUMN revision INTEGER")


def _backfill_revisions(conn) -> None:
    # Runs on every connect, not just when adding the column: a database already opened under
    # the previous release (or rebuilt by the legacy migration, which creates the column and
    # inserts NULLs) has NULL revisions, which derive's revision-watermark scan skips
    # unconditionally. rowid order is a stable, deterministic stand-in for write order since
    # this table has no other monotonic column; offsetting by the current max keeps backfilled
    # revisions above anything already written.
    # One statement, evaluated under SQLite's write lock. See the identical note in
    # describe/extracts.py: a separate read-then-update lets a concurrent upsert land in the
    # gap and collide revisions, which derive's watermark scan then skips permanently.
    conn.execute(
        "UPDATE transcripts SET revision = "
        "(SELECT COALESCE(MAX(revision), 0) FROM transcripts) + rowid "
        "WHERE revision IS NULL"
    )
    conn.commit()


def connect(db_path: Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    _migrate_legacy(conn)
    conn.executescript(_SCHEMA)
    _backfill_revisions(conn)
    return conn


_COMPARED = "chat_jid, text, lang, model, status"


def upsert(conn, source, message_id, chat_jid, text, lang, model, status, when) -> None:
    # revision is a per-write monotonic counter, distinct from transcribed_at: a whole
    # enrichment run shares one wall-clock timestamp, so derive's dirty-scan needs a value
    # that still increases across rows written in the same run to avoid treating an
    # already-processed batch as dirty forever.
    #
    # Skip the write entirely when nothing semantic changed. Rows with status "missing" or
    # "failed" are retried on every run, and an unconditional write bumps `revision`, which
    # makes derive re-render a chat-day whose content is identical. Same defect as the one
    # measured in describe/extracts.py.
    #
    # transcribed_at is excluded from the comparison on purpose — it changes on every look, so
    # including it would make this check never fire.
    current = conn.execute(
        f"SELECT {_COMPARED} FROM transcripts WHERE source = ? AND message_id = ?",
        (source, message_id),
    ).fetchone()
    if current is not None and tuple(current) == (chat_jid, text, lang, model, status):
        return
    conn.execute(
        "INSERT INTO transcripts (source, message_id, chat_jid, text, lang, model, status, transcribed_at, revision) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, (SELECT COALESCE(MAX(revision), 0) + 1 FROM transcripts)) "
        "ON CONFLICT(source, message_id) DO UPDATE SET "
        "chat_jid=excluded.chat_jid, text=excluded.text, lang=excluded.lang, "
        "model=excluded.model, status=excluded.status, transcribed_at=excluded.transcribed_at, "
        "revision=(SELECT COALESCE(MAX(revision), 0) + 1 FROM transcripts)",
        (source, message_id, chat_jid, text, lang, model, status, when),
    )
    conn.commit()


def done_ids(conn, source: str) -> set[str]:
    return {row[0] for row in conn.execute(
        "SELECT message_id FROM transcripts WHERE source = ? AND status IN ('ok', 'empty')", (source,)
    )}
