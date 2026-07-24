#!/usr/bin/env python3
"""
volta_tree_watch.py — Reactive watchdog for the tracked macos-app/ tree.

Problem: on 2026-07-24 the entire macos-app/ directory (237 tracked files) was
deleted from the working tree by a plain `rm`/`rm -rf`. The index still matched
HEAD, so NO git hook could have caught it (pre-commit / post-checkout only fire
on git actions, not working-tree `rm`). The loss was discovered hours later via
a confusing fastlane "directory handling" crash, with no way to identify what
deleted it.

This watcher closes that gap. It watches macos-app/ with watchfiles (Rust
`notify` / FSEvents on macOS) and, the instant a *tracked* file is deleted,
writes a crash-durable JSONL record + a full `ps` snapshot, then pings the
desktop. The `ps` snapshot is captured ~1s after the delete, while the
deleting process (shell, agent, script) is still likely alive — that is the
forensic payload that a 60s poller can never recover.

Scaffold mirrors macos-app/daemon/daemon_entry.py (buffering hardening,
Path(__file__).resolve().parents[N] repo-root, SIGTERM/SIGINT -> clean exit,
thin main() returning an int) and audit_log.py (fsync-durable JSONL,
one record per line, never raises).

Design notes:
    - watchfiles 1.0.5 is importable via the system pyenv python3
      (/Users/bretbouchard/.pyenv/shims/python3) but NOT in the repo .venv.
      The LaunchAgent plist invokes the pyenv shim directly for that reason.
    - This watcher is FORENSIC ONLY: it logs + notifies, it never restores.
      Auto-restore already lives in the fastlane beta guard
      (ensure_macos_app_present!); duplicating it here would risk fighting a
      legitimate intentional removal (e.g. a refactor that deletes the dir).

Usage:
    python3 scripts/volta_tree_watch.py            # watch forever (daemon mode)
    python3 scripts/volta_tree_watch.py --once     # one snapshot+exit (smoke test)
    python3 scripts/volta_tree_watch.py --dry-run  # log but suppress osascript

Exit codes:
    0 = clean shutdown (SIGTERM/SIGINT/--once)
    1 = unrecoverable startup error (macos-app missing, watchfiles absent)
"""

from __future__ import annotations

import argparse
import io
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

# --- PYTHONUNBUFFERED enforcement (mirrors daemon_entry.py) ------------------
os.environ["PYTHONUNBUFFERED"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"
try:
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    sys.stderr.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
except (AttributeError, ValueError):
    sys.stdout = io.TextIOWrapper(  # type: ignore[assignment]
        sys.stdout.buffer, encoding="utf-8", line_buffering=True
    )
    sys.stderr = io.TextIOWrapper(  # type: ignore[assignment]
        sys.stderr.buffer, encoding="utf-8", line_buffering=True
    )

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_MACOS_APP = _REPO_ROOT / "macos-app"
_DEFAULT_LOG = _REPO_ROOT / "logs" / "tree-watch.jsonl"


# =============================================================================
# Process snapshot — the forensic payload
# =============================================================================

def snapshot_processes() -> str:
    """Full process table, captured the instant a delete event arrives.

    `etime` (elapsed since start) and `command` are the columns that let you
    spot the deleting shell/agent/script. We do NOT filter, because the culprit
    may be a short-lived child that filtering would hide.
    """
    try:
        out = subprocess.run(
            ["ps", "-eo", "pid,ppid,user,etime,%cpu,command"],
            check=False, capture_output=True, text=True, timeout=5,
        )
        return out.stdout
    except Exception as exc:  # noqa: BLE001 — snapshot must never raise
        return f"<ps snapshot failed: {exc}>"


def notify(message: str) -> None:
    """macOS desktop notification + sound. Best-effort; never raises."""
    try:
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{message}" '
             f'with title "volta tree-watch" sound name "Basso"'],
            check=False, capture_output=True, timeout=5,
        )
    except Exception:  # noqa: BLE001
        pass


# =============================================================================
# Tracked-file set — cross-checked so we log only real losses
# =============================================================================

def repo_root_for(path: Path) -> Path | None:
    """Resolve the git repo root containing `path`. None if not in a repo."""
    try:
        out = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            check=False, capture_output=True, text=True, timeout=10,
        )
        if out.returncode != 0 or not out.stdout.strip():
            return None
        return Path(out.stdout.strip())
    except Exception:  # noqa: BLE001
        return None


def tracked_files_under(repo_root: Path, sub: Path) -> set[str]:
    """Git-tracked paths under `sub`, relative to repo root.

    Fallback to an empty set on any git error rather than raising: a missing
    tracked-set means we cannot distinguish tracked from untracked, so the
    classifier treats every delete as potentially tracked (logs it).
    """
    try:
        rel = sub.resolve().relative_to(repo_root.resolve())
        prefix = str(rel).replace(os.sep, "/") + "/"
        out = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files", prefix],
            check=False, capture_output=True, text=True, timeout=10,
        )
        if out.returncode != 0:
            return set()
        return {line.strip() for line in out.stdout.splitlines() if line.strip()}
    except Exception:  # noqa: BLE001
        return set()


# =============================================================================
# JSONL audit log (fsync-durable, mirrors audit_log.py discipline)
# =============================================================================

def append_record(log_path: Path, record: dict[str, Any]) -> None:
    """Append one JSON object + newline, flush, fsync. Never raises."""
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, separators=(",", ":")) + "\n"
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())
    except Exception as exc:  # noqa: BLE001 — logging must never raise
        sys.stderr.write(f"[tree-watch] log write failed: {exc}\n")
        sys.stderr.flush()


# =============================================================================
# Classifier — pure-ish; testable without watchfiles
# =============================================================================

def classify_and_log(
    changes: list[tuple[Any, str]],
    *,
    repo_root: Path,
    macos_app: Path,
    tracked: set[str],
    log_path: Path,
    dry_run: bool = False,
    snapshot_fn=snapshot_processes,
    notify_fn=notify,
) -> int:
    """Classify a watchfiles changes batch; log tracked deletes.

    Returns the count of tracked-delete records written. Filters out:
      - paths not under macos_app/
      - non-delete change types (watchfiles.Change.modify / .add)
      - deletes of files NOT git-tracked (build artifacts, .build/, *.xcodeproj)

    When `tracked` is empty (git unavailable), we cannot filter, so every delete
    under macos_app/ is logged — fail-open toward recording too much.
    """
    # Derive the repo-relative prefix for the tracked-set cross-check. Falls
    # back to "" when macos_app is outside repo_root (e.g. --macos-app pointed
    # elsewhere); in that case tracked-set filtering is skipped (fail-open).
    try:
        rel = macos_app.resolve().relative_to(repo_root.resolve())
        prefix = str(rel).replace(os.sep, "/") + "/"
    except ValueError:
        prefix = ""
    app_resolved = macos_app.resolve()
    deleted_paths: list[str] = []
    for change_type, raw_path in changes:
        # Only deletes. watchfiles.Change is an IntEnum: added=1, modified=2,
        # deleted=3. Match on the name as well as the value so this stays
        # correct if the enum numbering ever changes.
        try:
            is_delete = int(change_type) == 3
        except (TypeError, ValueError):
            is_delete = "delete" in str(change_type).lower()
        if not is_delete:
            continue
        # Normalize to a repo-relative posix path. Resolve raw_path so the
        # /var vs /private/var symlink distinction (macOS) doesn't break
        # matching against app_prefix or the tracked set.
        try:
            resolved = Path(raw_path).resolve()
            rel_to_app = resolved.relative_to(app_resolved)
        except ValueError:
            continue  # path not under macos-app/
        rel_path = prefix + str(rel_to_app).replace(os.sep, "/")
        if tracked and rel_path not in tracked:
            continue  # untracked file (build output, generated xcodeproj)
        deleted_paths.append(rel_path)

    if not deleted_paths:
        return 0

    record = {
        "ts": _now_iso(),
        "event": "tracked_delete",
        "deleted_count": len(deleted_paths),
        "paths": deleted_paths,
        "process_snapshot": snapshot_fn(),
        "watcher_pid": os.getpid(),
        "dry_run": dry_run,
    }
    append_record(log_path, record)
    msg = (f"{len(deleted_paths)} tracked file(s) under macos-app/ just deleted — "
           f"see logs/tree-watch.jsonl")
    if not dry_run:
        notify_fn(msg)
    sys.stderr.write(f"[tree-watch] {msg}\n")
    sys.stderr.flush()
    return len(deleted_paths)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


# =============================================================================
# Main loop
# =============================================================================

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reactive watchdog for the macos-app/ tree.")
    parser.add_argument("--macos-app", type=Path, default=_DEFAULT_MACOS_APP,
                        help="Directory to watch (default: <repo>/macos-app).")
    parser.add_argument("--log", type=Path, default=_DEFAULT_LOG,
                        help="JSONL audit log path.")
    parser.add_argument("--once", action="store_true",
                        help="Write one startup snapshot and exit (smoke test).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Log events but suppress osascript notifications.")
    args = parser.parse_args(argv)

    if not args.macos_app.is_dir():
        sys.stderr.write(f"[tree-watch] not a directory: {args.macos_app}\n")
        sys.stderr.flush()
        return 1

    try:
        from watchfiles import watch  # type: ignore[import-not-found]
    except ImportError:
        sys.stderr.write(
            "[tree-watch] watchfiles not importable. Install in the system "
            "python3 (pyenv): pip3 install watchfiles\n"
        )
        sys.stderr.flush()
        return 1

    shutdown = {"requested": False}

    def _on_signal(signum: int, _frame: Any) -> None:
        sys.stderr.write(f"[tree-watch] received signal {signum}, shutting down\n")
        sys.stderr.flush()
        shutdown["requested"] = True

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _on_signal)
        except (ValueError, OSError):
            pass

    append_record(args.log, {
        "ts": _now_iso(), "event": "start", "pid": os.getpid(),
        "python": sys.version.split()[0],
        "macos_app": str(args.macos_app),
    })

    if args.once:
        append_record(args.log, {
            "ts": _now_iso(), "event": "snapshot", "process_snapshot": snapshot_processes(),
        })
        return 0

    # Resolve the git repo root from the watched path so the tracked-set
    # cross-check targets the right repo (matters when --macos-app points
    # outside this source tree). Falls back to _REPO_ROOT (this repo).
    repo_root = repo_root_for(args.macos_app) or _REPO_ROOT
    tracked = tracked_files_under(repo_root, args.macos_app)
    sys.stderr.write(
        f"[tree-watch] watching {args.macos_app} "
        f"({len(tracked)} tracked file(s)); log={args.log}\n"
    )
    sys.stderr.flush()

    # watchfiles.watch blocks until the generator is closed. On SIGTERM the
    # signal handler sets the flag; we break between batches. The never-raise
    # contract: any error inside the loop is logged and we keep watching.
    try:
        for changes in watch(str(args.macos_app), watch_filter=lambda *_: True):
            if shutdown["requested"]:
                break
            try:
                classify_and_log(
                    list(changes),
                    repo_root=repo_root, macos_app=args.macos_app,
                    tracked=tracked, log_path=args.log, dry_run=args.dry_run,
                )
            except Exception as exc:  # noqa: BLE001
                append_record(args.log, {"ts": _now_iso(), "event": "error", "error": str(exc)})
    except KeyboardInterrupt:
        pass
    except Exception as exc:  # noqa: BLE001
        append_record(args.log, {"ts": _now_iso(), "event": "fatal", "error": str(exc)})
        sys.stderr.write(f"[tree-watch] fatal: {exc}\n")
        sys.stderr.flush()

    append_record(args.log, {"ts": _now_iso(), "event": "shutdown", "pid": os.getpid()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
