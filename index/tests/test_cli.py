from pathlib import Path
from subprocess import CompletedProcess

from index import cli


def test_adds_missing_backchannel_collection_then_updates_and_embeds(tmp_path):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        if argv[-2:] == ["collection", "list"]:
            return CompletedProcess(argv, 0, stdout="other\n", stderr="")
        return CompletedProcess(argv, 0, stdout="", stderr="")

    root = tmp_path / "corpus"
    root.mkdir()
    assert cli.main([], {"BC_CORPUS_ROOT": str(root), "BC_QMD_BIN": "fixture-qmd"}, run=run) == 0
    assert calls[0][0] == ["fixture-qmd", "collection", "list"]
    assert calls[1][0] == ["fixture-qmd", "collection", "add", str(root), "--name", "backchannel", "--pattern", "**/*.md"]
    assert calls[2][0] == ["fixture-qmd", "update"]
    assert calls[3][0] == ["fixture-qmd", "embed", "-f"]


def test_does_not_add_existing_backchannel_collection(tmp_path):
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return CompletedProcess(argv, 0, stdout="backchannel Files: 0\n", stderr="")

    root = tmp_path / "corpus"
    root.mkdir()
    assert cli.main([], {"BC_CORPUS_ROOT": str(root), "BC_QMD_BIN": "fixture-qmd"}, run=run) == 0
    assert ["fixture-qmd", "collection", "add", str(root), "--name", "backchannel", "--pattern", "**/*.md"] not in calls


def test_returns_one_when_qmd_update_fails(tmp_path):
    def run(argv, **kwargs):
        if argv[-1] == "update":
            return CompletedProcess(argv, 9, stdout="", stderr="fixture failure")
        return CompletedProcess(argv, 0, stdout="backchannel\n", stderr="")

    root = tmp_path / "corpus"
    root.mkdir()
    assert cli.main([], {"BC_CORPUS_ROOT": str(root), "BC_QMD_BIN": "fixture-qmd"}, run=run) == 1
