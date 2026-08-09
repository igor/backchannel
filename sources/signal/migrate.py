"""One-shot repair for historic Signal image attachments misclassified as documents."""
import sqlite3
from pathlib import Path


_IMAGE_SUFFIXES = ("%.jpg", "%.jpeg", "%.png", "%.gif", "%.webp", "%.heic")


def reclassify_image_rows(db_path: Path) -> int:
    conn = sqlite3.connect(Path(db_path))
    try:
        where = " OR ".join("lower(filename) LIKE ?" for _suffix in _IMAGE_SUFFIXES)
        cursor = conn.execute(
            f"UPDATE messages SET media_type = 'image' "
            f"WHERE media_type = 'document' AND ({where})",
            _IMAGE_SUFFIXES,
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()
