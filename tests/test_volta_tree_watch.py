"""Unit tests for the macos-app/ tree watcher (scripts/volta_tree_watch.py).

Tests the pure classifier/log logic without importing watchfiles, so they run
in any environment (watchfiles is absent from the repo .venv). The classifier
is exercised against a throwaway git repo so the "tracked vs untracked" filter
is verified for real.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Load the watcher as a module from scripts/ (no package init there).
_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
import volta_tree_watch as vw  # noqa: E402


# watchfiles.Change is an IntEnum: added=1, modified=2, deleted=3. The
# classifier reads change_type as an int, so bare ints are the simplest
# stand-in (verified against watchfiles 1.0.5).
DELETE = 3
MODIFY = 2
ADD = 1


@pytest.fixture
def fake_repo(tmp_path: Path) -> tuple[Path, Path, set[str]]:
    """A throwaway repo with macos-app/ containing one tracked + one untracked file.

    Returns (repo_root, macos_app_dir, tracked_set). The tracked file lives at
    macos_app_dir/Sources/tracked.swift; the untracked at Sources/untracked.swift.
    """
    repo = tmp_path / "repo"
    macos_app = repo / "macos-app"
    sources = macos_app / "Sources"
    sources.mkdir(parents=True)
    (sources / "tracked.swift").write_text("tracked\n")
    (sources / "untracked.swift").write_text("untracked\n")

    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "add", "macos-app/Sources/tracked.swift"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
    tracked = vw.tracked_files_under(repo, macos_app)
    return repo, macos_app, tracked


def _read_records(log_path: Path) -> list[dict]:
    return [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]


# -----------------------------------------------------------------------------
# snapshot_processes
# -----------------------------------------------------------------------------

def test_snapshot_processes_includes_self_pid() -> None:
    snap = vw.snapshot_processes()
    assert isinstance(snap, str)
    assert str(os.getpid()) in snap  # the test process is in the table


def test_snapshot_processes_never_raises_on_failure() -> None:
    # If ps were missing, the function must return a placeholder, not raise.
    with patch("subprocess.run", side_effect=FileNotFoundError("no ps")):
        snap = vw.snapshot_processes()
    assert snap.startswith("<ps snapshot failed")


# -----------------------------------------------------------------------------
# classify_and_log — the core classifier
# -----------------------------------------------------------------------------

def test_tracked_delete_logs_record(fake_repo, tmp_path: Path) -> None:
    repo, app, tracked = fake_repo
    log = tmp_path / "tree-watch.jsonl"
    calls = []

    n = vw.classify_and_log(
        [(DELETE, str(app / "Sources" / "tracked.swift"))],
        repo_root=repo, macos_app=app, tracked=tracked, log_path=log,
        snapshot_fn=lambda: "SNAP", notify_fn=calls.append,
    )
    assert n == 1
    recs = _read_records(log)
    assert len(recs) == 1
    assert recs[0]["event"] == "tracked_delete"
    assert recs[0]["deleted_count"] == 1
    assert "tracked.swift" in recs[0]["paths"][0]
    assert recs[0]["process_snapshot"] == "SNAP"
    assert calls == ["1 tracked file(s) under macos-app/ just deleted — see logs/tree-watch.jsonl"]


def test_untracked_delete_is_ignored(fake_repo, tmp_path: Path) -> None:
    repo, app, tracked = fake_repo
    log = tmp_path / "tree-watch.jsonl"
    n = vw.classify_and_log(
        [(DELETE, str(app / "Sources" / "untracked.swift"))],
        repo_root=repo, macos_app=app, tracked=tracked, log_path=log,
        snapshot_fn=lambda: "SNAP", notify_fn=lambda _: None,
    )
    assert n == 0
    assert not log.exists()  # nothing written


def test_modify_and_add_are_ignored(fake_repo, tmp_path: Path) -> None:
    repo, app, tracked = fake_repo
    log = tmp_path / "tree-watch.jsonl"
    n = vw.classify_and_log(
        [(MODIFY, str(app / "Sources" / "tracked.swift")), (ADD, str(app / "Sources" / "new.swift"))],
        repo_root=repo, macos_app=app, tracked=tracked, log_path=log,
        snapshot_fn=lambda: "SNAP", notify_fn=lambda _: None,
    )
    assert n == 0
    assert not log.exists()


def test_path_outside_macos_app_is_ignored(fake_repo, tmp_path: Path) -> None:
    repo, app, tracked = fake_repo
    log = tmp_path / "tree-watch.jsonl"
    n = vw.classify_and_log(
        [(DELETE, str(repo / "src" / "main.py"))],
        repo_root=repo, macos_app=app, tracked=tracked, log_path=log,
        snapshot_fn=lambda: "SNAP", notify_fn=lambda _: None,
    )
    assert n == 0


def test_dry_run_suppresses_notification(fake_repo, tmp_path: Path) -> None:
    repo, app, tracked = fake_repo
    log = tmp_path / "tree-watch.jsonl"
    calls = []
    n = vw.classify_and_log(
        [(DELETE, str(app / "Sources" / "tracked.swift"))],
        repo_root=repo, macos_app=app, tracked=tracked, log_path=log,
        dry_run=True, snapshot_fn=lambda: "SNAP", notify_fn=calls.append,
    )
    assert n == 1            # still logged
    assert calls == []       # but no notification
    assert _read_records(log)[0]["dry_run"] is True


def test_empty_tracked_set_fails_open(fake_repo, tmp_path: Path) -> None:
    """When git is unavailable (empty tracked set), every delete under macos-app is logged."""
    repo, app, _ = fake_repo
    log = tmp_path / "tree-watch.jsonl"
    n = vw.classify_and_log(
        [(DELETE, str(app / "Sources" / "untracked.swift"))],
        repo_root=repo, macos_app=app, tracked=set(), log_path=log,
        snapshot_fn=lambda: "SNAP", notify_fn=lambda _: None,
    )
    assert n == 1  # would be 0 if tracked set were populated


# -----------------------------------------------------------------------------
# fsync durability
# -----------------------------------------------------------------------------

def test_one_record_per_batch_multiple_deletes(fake_repo, tmp_path: Path) -> None:
    repo, app, tracked = fake_repo
    # Stage a second tracked file so both deletes are tracked.
    second = app / "Sources" / "tracked2.swift"
    second.write_text("tracked2\n")
    subprocess.run(["git", "add", "macos-app/Sources/tracked2.swift"], cwd=repo, check=True)
    tracked.add("macos-app/Sources/tracked2.swift")
    log = tmp_path / "tree-watch.jsonl"
    vw.classify_and_log(
        [(DELETE, str(app / "Sources" / "tracked.swift")),
         (DELETE, str(app / "Sources" / "tracked2.swift"))],
        repo_root=repo, macos_app=app, tracked=tracked, log_path=log,
        snapshot_fn=lambda: "SNAP", notify_fn=lambda _: None,
    )
    recs = _read_records(log)
    assert len(recs) == 1            # one record per BATCH, not per file
    assert recs[0]["deleted_count"] == 2
    assert len(recs[0]["paths"]) == 2


# -----------------------------------------------------------------------------
# append_record never raises
# -----------------------------------------------------------------------------

def test_append_record_swallows_io_error(tmp_path: Path) -> None:
    # Point the log at a path whose parent is a file (unopenable).
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    vw.append_record(blocker / "tree-watch.jsonl", {"event": "x"})  # must not raise


# -----------------------------------------------------------------------------
# CLI: --once smoke path
# -----------------------------------------------------------------------------

def test_once_flag_emits_snapshot_and_exits_0(fake_repo, tmp_path: Path) -> None:
    repo, app, _ = fake_repo
    log = tmp_path / "tree-watch.jsonl"
    # main() imports watchfiles before the --once check; stub it so the test
    # runs in any environment (watchfiles may be absent from the test venv).
    import types
    stub = types.ModuleType("watchfiles")
    stub.watch = lambda *a, **k: iter(())
    sys.modules["watchfiles"] = stub
    try:
        rc = vw.main(["--macos-app", str(app), "--log", str(log), "--once"])
    finally:
        sys.modules.pop("watchfiles", None)
    assert rc == 0
    recs = _read_records(log)
    events = [r["event"] for r in recs]
    assert "start" in events and "snapshot" in events
