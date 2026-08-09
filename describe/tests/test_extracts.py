import sqlite3

from describe import extracts


def test_connect_creates_image_text_table(tmp_path):
    conn = extracts.connect(tmp_path / "image_text.db")
    assert conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='image_text'"
    ).fetchall() == [("image_text",)]
    conn.close()


def test_upsert_updates_one_source_row_without_duplicates(tmp_path):
    conn = extracts.connect(tmp_path / "image_text.db")
    extracts.upsert(conn, "whatsapp", "fixture-id", "fixture-chat", "first", 1, 0.8, False, "apple-vision", "ok", "2026-08-08T09:00:00+00:00")
    extracts.upsert(conn, "whatsapp", "fixture-id", "fixture-chat", "second", 2, 0.9, True, "apple-vision", "ok", "2026-08-08T09:01:00+00:00")
    assert conn.execute(
        "SELECT text, line_count, document_like, extracted_at FROM image_text"
    ).fetchall() == [("second", 2, 1, "2026-08-08T09:01:00+00:00")]
    conn.close()


def test_done_ids_contains_only_ok_and_empty(tmp_path):
    conn = extracts.connect(tmp_path / "image_text.db")
    for message_id, status in [("ok-id", "ok"), ("empty-id", "empty"), ("missing-id", "missing"), ("failed-id", "failed")]:
        extracts.upsert(conn, "signal", message_id, "fixture-chat", "", 0, 0.0, False, "apple-vision", status, "now")
    assert extracts.done_ids(conn, "signal") == {"ok-id", "empty-id"}
    conn.close()


def test_migration_backfills_revision_for_pre_existing_rows(tmp_path):
    # Simulates a row written before the revision column existed: without a backfill it
    # stays NULL forever and derive's revision-watermark scan skips NULL rows unconditionally,
    # so the OCR result would never be picked up post-upgrade.
    db = tmp_path / "image_text.db"
    pre_conn = sqlite3.connect(db)
    pre_conn.execute(
        "CREATE TABLE image_text (source TEXT, message_id TEXT, chat_jid TEXT, text TEXT, "
        "line_count INTEGER, mean_confidence REAL, document_like INTEGER, model TEXT, "
        "status TEXT, extracted_at TEXT, PRIMARY KEY (source, message_id))")
    pre_conn.execute(
        "INSERT INTO image_text VALUES ('whatsapp', 'OLD1', 'c@x', 'old text', 1, 0.8, 0, 'apple-vision', 'ok', 'now')")
    pre_conn.commit()
    pre_conn.close()

    conn = extracts.connect(db)
    old_revision = conn.execute(
        "SELECT revision FROM image_text WHERE message_id='OLD1'").fetchone()[0]
    assert old_revision is not None

    extracts.upsert(conn, "whatsapp", "NEW1", "c@x", "new text", 1, 0.8, False, "apple-vision", "ok", "later")
    new_revision = conn.execute(
        "SELECT revision FROM image_text WHERE message_id='NEW1'").fetchone()[0]
    assert new_revision > old_revision
    conn.close()


def test_same_message_id_is_independent_by_source(tmp_path):
    conn = extracts.connect(tmp_path / "image_text.db")
    extracts.upsert(conn, "whatsapp", "shared-id", "demo-chat", "receipt total 12.40", 1, 0.8, False, "apple-vision", "ok", "now")
    extracts.upsert(conn, "signal", "shared-id", "signal-chat", "signal text", 1, 0.8, False, "apple-vision", "ok", "now")
    assert conn.execute("SELECT source, text FROM image_text ORDER BY source").fetchall() == [
        ("signal", "signal text"), ("whatsapp", "receipt total 12.40"),
    ]
    conn.close()


def test_backfill_runs_when_column_exists_with_null_rows(tmp_path):
    # A database already opened under the previous release has the column but NULL revisions;
    # the backfill must still run, persist without an upsert, and stay above existing values.
    db = tmp_path / "image_text.db"
    pre_conn = sqlite3.connect(db)
    pre_conn.executescript(extracts._SCHEMA)
    pre_conn.execute(
        "INSERT INTO image_text VALUES ('whatsapp', 'OLD1', 'c@x', 'old', 1, 0.8, 0, 'v', 'ok', 'now', NULL)")
    pre_conn.execute(
        "INSERT INTO image_text VALUES ('whatsapp', 'HAS1', 'c@x', 'kept', 1, 0.8, 0, 'v', 'ok', 'now', 7)")
    pre_conn.commit()
    pre_conn.close()

    extracts.connect(db).close()

    conn = sqlite3.connect(db)
    revisions = dict(conn.execute("SELECT message_id, revision FROM image_text"))
    conn.close()
    assert revisions["HAS1"] == 7
    assert revisions["OLD1"] > 7


def test_backfill_computes_max_inside_a_single_update_statement(tmp_path):
    # Pins the fix for the TOCTOU race: if MAX(revision) is read into Python first, a
    # concurrent upsert can commit in the gap and a backfilled row gets the same revision as
    # that new row. derive skips `revision <= since`, so the row is lost permanently.
    db = tmp_path / "image_text.db"
    seed = sqlite3.connect(db)
    seed.executescript(extracts._SCHEMA)
    seed.execute(
        "INSERT INTO image_text VALUES ('whatsapp','L1','c@x','old',1,0.8,0,'v','ok','now',NULL)")
    seed.commit()
    seed.close()

    statements = []

    class Recorder(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            statements.append(sql)
            return super().execute(sql, *args, **kwargs)

    conn = sqlite3.connect(db, factory=Recorder)
    extracts._migrate(conn)
    conn.close()

    updates = [s for s in statements if "UPDATE image_text" in s and "revision" in s]
    assert updates, "backfill must issue an UPDATE"
    assert all("MAX(revision)" in s for s in updates), \
        "MAX(revision) must be computed inside the UPDATE"
    assert not [s for s in statements
                if "MAX(revision)" in s and s.strip().upper().startswith("SELECT")], \
        "MAX(revision) must never be read into Python before the UPDATE"


def test_backfill_assigns_distinct_revisions_above_the_existing_max(tmp_path):
    db = tmp_path / "image_text.db"
    seed = sqlite3.connect(db)
    seed.executescript(extracts._SCHEMA)
    seed.execute(
        "INSERT INTO image_text VALUES ('whatsapp','KEPT','c@x','kept',1,0.8,0,'v','ok','now',5)")
    seed.execute(
        "INSERT INTO image_text VALUES ('whatsapp','L1','c@x','a',1,0.8,0,'v','ok','now',NULL)")
    seed.execute(
        "INSERT INTO image_text VALUES ('whatsapp','L2','c@x','b',1,0.8,0,'v','ok','now',NULL)")
    seed.commit()
    seed.close()

    extracts.connect(db).close()

    rows = dict(sqlite3.connect(db).execute("SELECT message_id, revision FROM image_text"))
    assert rows["KEPT"] == 5
    assert rows["L1"] > 5 and rows["L2"] > 5
    assert len(set(rows.values())) == 3


def test_repeated_identical_upsert_does_not_bump_revision(tmp_path):
    # describe retries every row whose media file is absent, on every run. If those no-op
    # writes bump revision, derive's dirty-scan re-renders the chat-day with identical
    # content — measured in production at 1,022 files rewritten per hourly cycle.
    conn = extracts.connect(tmp_path / "image_text.db")
    extracts.upsert(conn, "whatsapp", "M1", "c@x", "", 0, 0.0, False, "apple-vision", "missing", "t1")
    first = conn.execute("SELECT revision FROM image_text WHERE message_id='M1'").fetchone()[0]

    for stamp in ("t2", "t3", "t4"):
        extracts.upsert(conn, "whatsapp", "M1", "c@x", "", 0, 0.0, False, "apple-vision", "missing", stamp)

    after = conn.execute("SELECT revision FROM image_text WHERE message_id='M1'").fetchone()[0]
    assert after == first, "an unchanged row must not bump revision"
    conn.close()


def test_a_real_change_still_bumps_revision(tmp_path):
    # The media file appearing later, or a re-OCR producing different text, must still be seen.
    conn = extracts.connect(tmp_path / "image_text.db")
    extracts.upsert(conn, "whatsapp", "M1", "c@x", "", 0, 0.0, False, "apple-vision", "missing", "t1")
    first = conn.execute("SELECT revision FROM image_text WHERE message_id='M1'").fetchone()[0]

    extracts.upsert(conn, "whatsapp", "M1", "c@x", "receipt total 12.40", 1, 0.9, True, "apple-vision", "ok", "t2")

    row = conn.execute(
        "SELECT revision, text, status FROM image_text WHERE message_id='M1'").fetchone()
    assert row[0] > first, "a changed row must bump revision"
    assert row[1] == "receipt total 12.40" and row[2] == "ok"
    conn.close()
