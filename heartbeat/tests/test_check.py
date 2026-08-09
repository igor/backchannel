import json
from datetime import datetime, timedelta, timezone

from heartbeat import cli

SOURCE = "signal"


def warning_path(root):
    return root / f"WARNING-{SOURCE}.md"


def run(root, hours_ago=None):
    now = datetime(2026, 8, 7, 12, tzinfo=timezone.utc)
    if hours_ago is not None:
        state = root / ".derive" / SOURCE / "state.json"
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(json.dumps({"watermark_utc": (now - timedelta(hours=hours_ago)).isoformat()}), encoding="utf-8")
    return cli.check(SOURCE, {"BC_CORPUS_ROOT": str(root)}, now=now, notify=lambda message: None)


def test_missing_state_writes_warning(tmp_path):
    assert run(tmp_path) == 0
    assert "no state file" in warning_path(tmp_path).read_text(encoding="utf-8")


def test_fresh_state_removes_warning(tmp_path):
    warning_path(tmp_path).write_text("old", encoding="utf-8")
    assert run(tmp_path, hours_ago=0) == 0
    assert not warning_path(tmp_path).exists()


def test_stale_state_warns_for_unlink_investigation(tmp_path):
    assert run(tmp_path, hours_ago=48) == 0
    assert "capture stalled" in warning_path(tmp_path).read_text(encoding="utf-8")
