"""List audio messages from a messages.db snapshot. Reuses derive.store for snapshotting."""
from typing import List, Tuple
import sqlite3


def audio_messages(conn: sqlite3.Connection) -> List[Tuple[str, str, str]]:
    """(message_id, chat_jid, filename) for every media_type='audio' row."""
    rows = conn.execute(
        "SELECT id, chat_jid, COALESCE(filename,'') FROM messages WHERE media_type='audio'").fetchall()
    return [(r[0], r[1], r[2]) for r in rows]
