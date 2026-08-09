"""Read image rows from a source-store snapshot."""
import sqlite3


def image_messages(conn: sqlite3.Connection) -> list[tuple[str, str, str]]:
    rows = conn.execute(
        "SELECT id, chat_jid, COALESCE(filename, '') FROM messages WHERE media_type = 'image'"
    ).fetchall()
    return [(message_id, chat_jid, filename) for message_id, chat_jid, filename in rows]
