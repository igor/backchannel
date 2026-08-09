"""The source-namespaced image OCR sidecar database."""
import sqlite3
from pathlib import Path


_SCHEMA = """
CREATE TABLE IF NOT EXISTS image_text (
    source TEXT NOT NULL,
    message_id TEXT NOT NULL,
    chat_jid TEXT,
    text TEXT,
    line_count INTEGER,
    mean_confidence REAL,
    document_like INTEGER,
    model TEXT,
    status TEXT,
    extracted_at TEXT,
    revision INTEGER,
    PRIMARY KEY (source, message_id)
);
"""


def _migrate(conn) -> None:
    columns = [row[1] for row in conn.execute("PRAGMA table_info(image_text)")]
    if columns and "revision" not in columns:
        conn.execute("ALTER TABLE image_text ADD COLUMN revision INTEGER")
    # Backfill runs on every connect, not just when adding the column: a database already
    # opened under the previous release has the column but NULL revisions, which derive's
    # revision-watermark scan skips unconditionally. rowid order is a stable, deterministic
    # stand-in for write order since this table has no other monotonic column; offsetting by
    # the current max keeps backfilled revisions above anything already written.
    # One statement, evaluated under SQLite's write lock. Reading MAX(revision) into Python
    # first and updating separately leaves a gap in which a concurrent upsert can commit, so a
    # backfilled row could be handed the same revision as that new row — and derive's
    # `revision <= since` scan would then skip it forever.
    conn.execute(
        "UPDATE image_text SET revision = "
        "(SELECT COALESCE(MAX(revision), 0) FROM image_text) + rowid "
        "WHERE revision IS NULL"
    )
    conn.commit()


def connect(db_path: Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    _migrate(conn)
    return conn


_COMPARED = "chat_jid, text, line_count, mean_confidence, document_like, model, status"


def upsert(conn, source, message_id, chat_jid, text, line_count, mean_confidence, document_like, model, status, when) -> None:
    # revision is a per-write monotonic counter, distinct from extracted_at: a whole OCR
    # run shares one wall-clock timestamp, so derive's dirty-scan needs a value that still
    # increases across rows written in the same run to avoid treating an already-processed
    # batch as dirty forever.
    #
    # Skip the write entirely when nothing semantic changed. describe retries every row whose
    # media file is absent on every run, and an unconditional write bumps `revision`, which
    # tells derive the chat-day changed and triggers a re-render of identical content. Measured
    # in production: 3,672 no-op upserts and 1,022 rewritten files per hourly cycle.
    #
    # extracted_at is excluded from the comparison on purpose — it changes on every look, so
    # including it would make this check never fire. It now records when a result was produced
    # rather than when the row was last examined.
    current = conn.execute(
        f"SELECT {_COMPARED} FROM image_text WHERE source = ? AND message_id = ?",
        (source, message_id),
    ).fetchone()
    if current is not None and tuple(current) == (
        chat_jid, text, line_count, mean_confidence, int(document_like), model, status,
    ):
        return
    conn.execute(
        "INSERT INTO image_text (source, message_id, chat_jid, text, line_count, mean_confidence, document_like, model, status, extracted_at, revision) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, (SELECT COALESCE(MAX(revision), 0) + 1 FROM image_text)) "
        "ON CONFLICT(source, message_id) DO UPDATE SET "
        "chat_jid=excluded.chat_jid, text=excluded.text, line_count=excluded.line_count, "
        "mean_confidence=excluded.mean_confidence, document_like=excluded.document_like, "
        "model=excluded.model, status=excluded.status, extracted_at=excluded.extracted_at, "
        "revision=(SELECT COALESCE(MAX(revision), 0) + 1 FROM image_text)",
        (source, message_id, chat_jid, text, line_count, mean_confidence, int(document_like), model, status, when),
    )
    conn.commit()


def done_ids(conn, source: str) -> set[str]:
    return {row[0] for row in conn.execute(
        "SELECT message_id FROM image_text WHERE source = ? AND status IN ('ok', 'empty')", (source,)
    )}
