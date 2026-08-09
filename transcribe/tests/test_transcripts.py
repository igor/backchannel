import sqlite3
from pathlib import Path

from transcribe import transcripts


def test_connect_creates_table(tmp_path):
    db = tmp_path / "transcripts.db"
    conn = transcripts.connect(db)
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='transcripts'"
    ).fetchall()
    assert rows == [("transcripts",)]
    conn.close()


def test_upsert_is_idempotent_update(tmp_path):
    conn = transcripts.connect(tmp_path / "transcripts.db")
    transcripts.upsert(conn, "whatsapp", "A1", "c@x", "hallo", "de", "m.bin", "ok", "2026-06-15T09:00:00+00:00")
    transcripts.upsert(conn, "whatsapp", "A1", "c@x", "hallo welt", "de", "m.bin", "ok", "2026-06-15T09:01:00+00:00")
    rows = conn.execute(
        "SELECT message_id, text, transcribed_at FROM transcripts WHERE message_id='A1'"
    ).fetchall()
    assert len(rows) == 1  # no duplicate
    assert rows[0] == ("A1", "hallo welt", "2026-06-15T09:01:00+00:00")
    conn.close()


def test_done_ids_returns_only_ok_and_empty(tmp_path):
    conn = transcripts.connect(tmp_path / "transcripts.db")
    for mid, status in [("OK1", "ok"), ("EM1", "empty"), ("FA1", "failed"), ("MI1", "missing")]:
        transcripts.upsert(conn, "whatsapp", mid, "c@x", "t", "de", "m.bin", status, "now")
    done = transcripts.done_ids(conn, "whatsapp")
    assert done == {"OK1", "EM1"}
    assert "FA1" not in done and "MI1" not in done
    conn.close()


def test_connect_makes_parent_dirs(tmp_path):
    db = tmp_path / "nested" / "dir" / "transcripts.db"
    conn = transcripts.connect(db)
    assert db.exists()
    conn.close()


def test_migration_backfills_revision_for_pre_existing_rows(tmp_path):
    # Simulates a row written before the revision column existed: without a backfill it
    # stays NULL forever and derive's revision-watermark scan skips NULL rows unconditionally,
    # so the enrichment would never be picked up post-upgrade.
    db = tmp_path / "transcripts.db"
    pre_conn = sqlite3.connect(db)
    pre_conn.execute(
        "CREATE TABLE transcripts (source TEXT, message_id TEXT, chat_jid TEXT, text TEXT, "
        "lang TEXT, model TEXT, status TEXT, transcribed_at TEXT, PRIMARY KEY (source, message_id))")
    pre_conn.execute(
        "INSERT INTO transcripts VALUES ('whatsapp', 'OLD1', 'c@x', 'hallo', 'de', 'm', 'ok', 'now')")
    pre_conn.commit()
    pre_conn.close()

    conn = transcripts.connect(db)
    old_revision = conn.execute(
        "SELECT revision FROM transcripts WHERE message_id='OLD1'").fetchone()[0]
    assert old_revision is not None

    transcripts.upsert(conn, "whatsapp", "NEW1", "c@x", "welt", "de", "m", "ok", "later")
    new_revision = conn.execute(
        "SELECT revision FROM transcripts WHERE message_id='NEW1'").fetchone()[0]
    assert new_revision > old_revision
    conn.close()


def test_same_message_id_is_independent_per_source(tmp_path):
    conn = transcripts.connect(tmp_path / "transcripts.db")
    transcripts.upsert(conn, "whatsapp", "same-id", "chat-a", "wa words", "en", "m", "ok", "now")
    transcripts.upsert(conn, "signal", "same-id", "chat-b", "signal words", "en", "m", "ok", "now")
    assert transcripts.done_ids(conn, "whatsapp") == {"same-id"}
    assert transcripts.done_ids(conn, "signal") == {"same-id"}
    assert conn.execute("SELECT source, text FROM transcripts ORDER BY source").fetchall() == [
        ("signal", "signal words"), ("whatsapp", "wa words"),
    ]
    conn.close()


def test_backfill_runs_when_column_exists_with_null_rows(tmp_path):
    # A database already opened under the previous release has the column but NULL revisions;
    # the backfill must still run, persist without an upsert, and stay above existing values.
    db = tmp_path / "transcripts.db"
    pre_conn = sqlite3.connect(db)
    pre_conn.executescript(transcripts._SCHEMA)
    pre_conn.execute(
        "INSERT INTO transcripts VALUES ('whatsapp', 'OLD1', 'c@x', 'hallo', 'de', 'm', 'ok', 'now', NULL)")
    pre_conn.execute(
        "INSERT INTO transcripts VALUES ('whatsapp', 'HAS1', 'c@x', 'kept', 'de', 'm', 'ok', 'now', 7)")
    pre_conn.commit()
    pre_conn.close()

    transcripts.connect(db).close()

    conn = sqlite3.connect(db)
    revisions = dict(conn.execute("SELECT message_id, revision FROM transcripts"))
    conn.close()
    assert revisions["HAS1"] == 7
    assert revisions["OLD1"] > 7


def test_legacy_rebuild_backfills_revision(tmp_path):
    # The legacy (source-less) rebuild creates the new schema with revision already present,
    # so the backfill must key off NULL rows rather than a missing column.
    db = tmp_path / "transcripts.db"
    pre_conn = sqlite3.connect(db)
    pre_conn.execute(
        "CREATE TABLE transcripts (message_id TEXT PRIMARY KEY, chat_jid TEXT, text TEXT, "
        "lang TEXT, model TEXT, status TEXT, transcribed_at TEXT)")
    pre_conn.execute("INSERT INTO transcripts VALUES ('OLD1', 'c@x', 'hallo', 'de', 'm', 'ok', 'now')")
    pre_conn.commit()
    pre_conn.close()

    transcripts.connect(db).close()

    conn = sqlite3.connect(db)
    assert conn.execute("SELECT revision FROM transcripts WHERE message_id='OLD1'").fetchone()[0] is not None
    conn.close()


def test_backfill_computes_max_inside_a_single_update_statement(tmp_path):
    # Same TOCTOU race as describe/extracts.py: a separately-read MAX lets a concurrent
    # upsert collide revisions, and derive's `revision <= since` scan then drops the row.
    db = tmp_path / "transcripts.db"
    seed = sqlite3.connect(db)
    seed.executescript(transcripts._SCHEMA)
    seed.execute(
        "INSERT INTO transcripts VALUES ('whatsapp','L1','c@x','old','en','m','ok','now',NULL)")
    seed.commit()
    seed.close()

    statements = []

    class Recorder(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            statements.append(sql)
            return super().execute(sql, *args, **kwargs)

    conn = sqlite3.connect(db, factory=Recorder)
    transcripts._backfill_revisions(conn)
    conn.close()

    updates = [s for s in statements if "UPDATE transcripts" in s and "revision" in s]
    assert updates, "backfill must issue an UPDATE"
    assert all("MAX(revision)" in s for s in updates), \
        "MAX(revision) must be computed inside the UPDATE"
    assert not [s for s in statements
                if "MAX(revision)" in s and s.strip().upper().startswith("SELECT")], \
        "MAX(revision) must never be read into Python before the UPDATE"


def test_backfill_assigns_distinct_revisions_above_the_existing_max(tmp_path):
    db = tmp_path / "transcripts.db"
    seed = sqlite3.connect(db)
    seed.executescript(transcripts._SCHEMA)
    seed.execute(
        "INSERT INTO transcripts VALUES ('whatsapp','KEPT','c@x','k','en','m','ok','now',5)")
    seed.execute(
        "INSERT INTO transcripts VALUES ('whatsapp','L1','c@x','a','en','m','ok','now',NULL)")
    seed.execute(
        "INSERT INTO transcripts VALUES ('whatsapp','L2','c@x','b','en','m','ok','now',NULL)")
    seed.commit()
    seed.close()

    transcripts.connect(db).close()

    rows = dict(sqlite3.connect(db).execute("SELECT message_id, revision FROM transcripts"))
    assert rows["KEPT"] == 5
    assert rows["L1"] > 5 and rows["L2"] > 5
    assert len(set(rows.values())) == 3


def test_repeated_identical_upsert_does_not_bump_revision(tmp_path):
    # Rows with status missing or failed are retried on every run; a no-op write must not
    # make derive believe the chat-day changed.
    conn = transcripts.connect(tmp_path / "transcripts.db")
    transcripts.upsert(conn, "whatsapp", "M1", "c@x", "", "", "m", "missing", "t1")
    first = conn.execute("SELECT revision FROM transcripts WHERE message_id='M1'").fetchone()[0]

    for stamp in ("t2", "t3", "t4"):
        transcripts.upsert(conn, "whatsapp", "M1", "c@x", "", "", "m", "missing", stamp)

    after = conn.execute("SELECT revision FROM transcripts WHERE message_id='M1'").fetchone()[0]
    assert after == first, "an unchanged row must not bump revision"
    conn.close()


def test_a_real_transcript_still_bumps_revision(tmp_path):
    conn = transcripts.connect(tmp_path / "transcripts.db")
    transcripts.upsert(conn, "whatsapp", "M1", "c@x", "", "", "m", "missing", "t1")
    first = conn.execute("SELECT revision FROM transcripts WHERE message_id='M1'").fetchone()[0]

    transcripts.upsert(conn, "whatsapp", "M1", "c@x", "hello there", "en", "m", "ok", "t2")

    row = conn.execute(
        "SELECT revision, text, status FROM transcripts WHERE message_id='M1'").fetchone()
    assert row[0] > first, "a changed row must bump revision"
    assert row[1] == "hello there" and row[2] == "ok"
    conn.close()
