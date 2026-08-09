from derive import store as derive_store
from describe import store


def test_image_messages_returns_only_image_rows(messages_db, tmp_path):
    snapshot = tmp_path / "snapshot.db"
    derive_store.snapshot_db(messages_db, snapshot)
    conn = derive_store.connect_ro(snapshot)
    assert store.image_messages(conn) == [
        ("image-document", "fixture-chat", "document.png"),
        ("image-short", "fixture-chat", "short.jpg"),
        ("image-missing", "fixture-chat", "missing.webp"),
    ]
    conn.close()


def test_image_messages_coalesces_null_filename(messages_db, tmp_path):
    import sqlite3

    conn = sqlite3.connect(messages_db)
    conn.execute("INSERT INTO messages VALUES (?,?,?,?)", ("image-null", "fixture-chat", "image", None))
    conn.commit()
    conn.close()
    snapshot = tmp_path / "snapshot.db"
    derive_store.snapshot_db(messages_db, snapshot)
    read = derive_store.connect_ro(snapshot)
    assert ("image-null", "fixture-chat", "") in store.image_messages(read)
    read.close()
