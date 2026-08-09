from datetime import datetime, timezone
from sources.signal import spool


def test_append_fsynced_keeps_original_complete_lines(tmp_path):
    now = datetime(2026, 7, 27, 9, 0, tzinfo=timezone.utc)
    path, count = spool.append_fsynced(tmp_path, ['{"a":1}\n', '', '{"b":2}'], now)
    assert path == tmp_path / "spool" / "2026-07-27.jsonl"
    assert count == 2
    assert path.read_text() == '{"a":1}\n{"b":2}\n'


def test_read_lines_respects_byte_offset(tmp_path):
    path, _ = spool.append_fsynced(
        tmp_path, ['{"a":1}', '{"b":2}'], datetime(2026, 7, 27, tzinfo=timezone.utc))
    first, second = spool.read_lines(path)
    assert first[1] == '{"a":1}'
    assert spool.read_lines(path, second[0]) == [second]