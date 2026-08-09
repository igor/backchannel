import sqlite3
import subprocess
from datetime import datetime, timezone
from unittest.mock import patch

from sources.signal import cli, spool, store
from sources.signal.tests.conftest import envelope


def test_capture_replays_a_stranded_prior_day_spool_file_from_its_offset(tmp_path):
    """A parse failure before midnight must not strand the previous day's spool file
    once capture rolls onto a new daily file — every unconsumed file gets replayed,
    from its persisted offset, on every run."""
    root = tmp_path / "store"
    env = {
        "BC_SIGNAL_STORE_ROOT": str(root),
        "BC_SIGNAL_STORE": str(root / "messages.db"),
        "BC_SIGNAL_ACCOUNT": "archive-account",
    }
    stale_line = envelope(dataMessage={"timestamp": 1785135600000, "message": "stranded note"})
    stale_path, _ = spool.append_fsynced(root, [stale_line], datetime(2026, 7, 26, 9, 0, tzinfo=timezone.utc))
    store.save_state(root / ".bridge-state.json", {"spool_offsets": {}, "last_success_utc": None})

    with patch("sources.signal.cli.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "", "")):
        assert cli.main([], env=env) == 0

    state = store.load_state(root / ".bridge-state.json")
    assert state["spool_offsets"][str(stale_path)] == stale_path.stat().st_size
    conn = sqlite3.connect(root / "messages.db")
    assert conn.execute("SELECT content FROM messages WHERE content='stranded note'").fetchone() is not None


def test_receive_nonzero_does_not_parse_or_advance_state(tmp_path):
    env = {"BC_SIGNAL_STORE_ROOT": str(tmp_path / "store"), "BC_SIGNAL_STORE": str(tmp_path / "store" / "messages.db"), "BC_SIGNAL_ACCOUNT": "archive-account"}
    with patch("sources.signal.cli.subprocess.run", return_value=subprocess.CompletedProcess([], 1, "", "unlinked")):
        assert cli.main([], env=env) == 1   # explicit argv: parse_args(None) would read pytest's own sys.argv
    assert not (tmp_path / "store" / ".bridge-state.json").exists()
    assert not (tmp_path / "store" / "spool").exists()


def test_repair_image_media_types_does_not_call_signal_cli(tmp_path, monkeypatch):
    from sources.signal import cli

    calls = []
    monkeypatch.setattr(cli.migrate, "reclassify_image_rows", lambda path: calls.append(path) or 2)
    assert cli.main(["--repair-image-media-types"], {"BC_SIGNAL_STORE": str(tmp_path / "messages.db")}) == 0
    assert calls == [tmp_path / "messages.db"]


def test_offsets_persist_when_a_later_spool_file_raises(tmp_path):
    # Progress on earlier files must survive an unexpected exception on a later one, or every
    # consumed file is reparsed on every cycle for as long as the broken file exists.
    root = tmp_path / "store"
    env = {
        "BC_SIGNAL_STORE_ROOT": str(root),
        "BC_SIGNAL_STORE": str(root / "messages.db"),
        "BC_SIGNAL_ACCOUNT": "archive-account",
    }
    line_a = envelope(dataMessage={"timestamp": 1785135600000, "message": "day A note"})
    line_b = envelope(dataMessage={"timestamp": 1785222000000, "message": "day B note"})
    path_a, _ = spool.append_fsynced(root, [line_a], datetime(2026, 7, 26, 9, 0, tzinfo=timezone.utc))
    path_b, _ = spool.append_fsynced(root, [line_b], datetime(2026, 7, 27, 9, 0, tzinfo=timezone.utc))
    store.save_state(root / ".bridge-state.json", {"spool_offsets": {}, "last_success_utc": None})

    real_replay = cli.parser.replay

    def replay(spool_file, *args, **kwargs):
        if spool_file == path_b:
            raise RuntimeError("unexpected parser failure on the later file")
        return real_replay(spool_file, *args, **kwargs)

    with patch("sources.signal.cli.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "", "")):
        with patch.object(cli.parser, "replay", replay):
            try:
                cli.main([], env=env)
            except RuntimeError:
                pass

    state = store.load_state(root / ".bridge-state.json")
    assert state["spool_offsets"][str(path_a)] == path_a.stat().st_size