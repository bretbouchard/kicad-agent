#!/bin/bash
#
# install_tree_watch.sh — install/uninstall the volta tree-watch LaunchAgent.
#
# Usage:
#   bash scripts/install_tree_watch.sh           # install (idempotent)
#   bash scripts/install_tree_watch.sh status     # show load status + tail log
#   bash scripts/install_tree_watch.sh uninstall  # unload + remove plist
#
# This script touches ~/Library/LaunchAgents and launchd state. It is safe to
# re-run. It does NOT auto-start on a clean machine without user confirmation
# in interactive mode, but when run non-interactively it will load the agent.
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="org.volta.tree-watch"
SRC_PLIST="$REPO_ROOT/scripts/launchagents/$LABEL.plist"
DST_DIR="$HOME/Library/LaunchAgents"
DST_PLIST="$DST_DIR/$LABEL.plist"
LOG_DIR="$REPO_ROOT/logs"
USER_LOG_DIR="$HOME/Library/Logs"

cmd="${1:-install}"

is_loaded() {
	launchctl list 2>/dev/null | grep -q "$LABEL"
}

do_install() {
	# Sanity checks before touching launchd.
	if [[ ! -f "$SRC_PLIST" ]]; then
		echo "error: source plist not found: $SRC_PLIST" >&2
		exit 1
	fi
	if ! command -v python3 >/dev/null; then
		echo "error: python3 not on PATH" >&2
		exit 1
	fi
	if ! python3 -c "import watchfiles" 2>/dev/null; then
		echo "warning: watchfiles not importable by $(command -v python3)" >&2
		echo "  The plist invokes the pyenv shim (/Users/bretbouchard/.pyenv/shims/python3)." >&2
		echo "  If that python lacks watchfiles, run: pip3 install watchfiles" >&2
	fi

	mkdir -p "$DST_DIR" "$LOG_DIR" "$USER_LOG_DIR"
	cp "$SRC_PLIST" "$DST_PLIST"
	echo "installed: $DST_PLIST"

	# Unload if already loaded so we pick up the new plist, then load.
	if is_loaded; then
		launchctl unload "$DST_PLIST" 2>/dev/null || true
	fi
	launchctl load "$DST_PLIST"
	echo "loaded: $LABEL"
	do_status
}

do_uninstall() {
	if is_loaded; then
		launchctl unload "$DST_PLIST" 2>/dev/null || true
		echo "unloaded: $LABEL"
	else
		echo "not loaded"
	fi
	rm -f "$DST_PLIST"
	echo "removed: $DST_PLIST"
}

do_status() {
	if is_loaded; then
		echo "status: LOADED"
		launchctl list | grep "$LABEL" || true
	else
		echo "status: not loaded"
	fi
	echo "---"
	echo "log: $LOG_DIR/tree-watch.jsonl"
	if [[ -f "$LOG_DIR/tree-watch.jsonl" ]]; then
		tail -5 "$LOG_DIR/tree-watch.jsonl"
	else
		echo "(no events yet)"
	fi
}

case "$cmd" in
	install)   do_install ;;
	uninstall) do_uninstall ;;
	status)    do_status ;;
	*)
		echo "usage: $0 [install|uninstall|status]" >&2
		exit 1 ;;
esac
