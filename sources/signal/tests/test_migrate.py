import sqlite3

from sources.signal import migrate


def _db(tmp_path):
    path = tmp_path / "messages.db"
    conn = sqlite3.connect(path)
    conn.executescript("CREATE TABLE messages (id TEXT, media_type TEXT, filename TEXT)")
    conn.executemany(
        "INSERT INTO messages VALUES (?,?,?)",
        [
            ("fixture-png", "document", "fixture.png"),
            ("fixture-heic", "document", "fixture.HEIC"),
            ("fixture-pdf", "document", "fixture.pdf"),
            ("already-image", "image", "already.jpg"),
        ],
    )
    conn.commit()
    conn.close()
    return path


def test_reclassify_updates_only_misclassified_image_extensions(tmp_path):
    path = _db(tmp_path)
    assert migrate.reclassify_image_rows(path) == 2
    conn = sqlite3.connect(path)
    assert dict(conn.execute("SELECT id, media_type FROM messages")) == {
        "fixture-png": "image", "fixture-heic": "image", "fixture-pdf": "document", "already-image": "image"
    }
    conn.close()


def test_reclassify_is_idempotent(tmp_path):
    path = _db(tmp_path)
    migrate.reclassify_image_rows(path)
    assert migrate.reclassify_image_rows(path) == 0
