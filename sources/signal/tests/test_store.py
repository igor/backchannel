from datetime import datetime, timezone
from sources.signal import store


def test_connect_creates_wa_derive_schema_contract(tmp_path):
    conn = store.connect(tmp_path / "nested" / "messages.db")
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"chats", "messages"} <= tables
    conn.close()


def test_state_roundtrip_is_atomic_shape(tmp_path):
    path = tmp_path / ".bridge-state.json"
    state = store.load_state(path)
    updated = store.mark_success(
        state, tmp_path / "spool" / "2026-07-27.jsonl", 42,
        datetime(2026, 7, 27, tzinfo=timezone.utc))
    store.save_state(path, updated)
    assert store.load_state(path)["spool_offsets"][str(tmp_path / "spool" / "2026-07-27.jsonl")] == 42