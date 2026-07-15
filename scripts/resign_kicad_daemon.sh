#!/usr/bin/env bash
# resign_kicad_daemon.sh — re-sign the PyInstaller-bundled volta-daemon.
#
# Why this exists:
#   macOS enforces "non-platform" library signature validation when a binary
#   dlopens a non-platform dylib that has its own ad-hoc signature. If the
#   dylib was signed in a different context (different machine, different
#   build env, or just stale), the dlopen fails with:
#     "code signature ... not valid for use in process: mapping process and
#      mapped file (non-platform) have different Team IDs"
#   The ProcessManager sees an immediate crash, and after 5 in 60s the
#   crash-loop detector halts auto-restart — the user sees a persistent
#   "Daemon unavailable" alert even though the binary is fine.
#
# This script re-signs every dylib/so inside _internal/ plus the main binary
# with a single ad-hoc identity, so they match when the parent process spawns
# the daemon.
#
# Usage:
#   bash scripts/resign_kicad_daemon.sh
#
# Idempotent. Safe to re-run after every `pyinstaller` build.

set -euo pipefail

DIST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../macos-app/daemon/dist/volta-daemon" && pwd)"

if [ ! -d "$DIST_DIR" ]; then
    echo "ERROR: $DIST_DIR does not exist. Build the daemon with PyInstaller first."
    exit 1
fi

INTERNAL_DIR="$DIST_DIR/_internal"
MAIN_BIN="$DIST_DIR/volta-daemon"

if [ ! -d "$INTERNAL_DIR" ]; then
    echo "ERROR: $INTERNAL_DIR does not exist. PyInstaller bundle is incomplete."
    exit 1
fi
if [ ! -x "$MAIN_BIN" ]; then
    echo "ERROR: $MAIN_BIN not found or not executable."
    exit 1
fi

echo "Re-signing dylibs/extensions in $INTERNAL_DIR ..."
find "$INTERNAL_DIR" -type f \( -name "*.dylib" -o -name "*.so" \) -print0 \
    | xargs -0 -I{} codesign --force --sign - --timestamp=none "{}" 2>&1 \
    | tail -5 || true

echo "Re-signing main binary $MAIN_BIN ..."
codesign --force --sign - --timestamp=none "$MAIN_BIN"

echo ""
echo "Verifying libpython signature ..."
LIBPY="$INTERNAL_DIR/libpython3.11.dylib"
if [ -f "$LIBPY" ]; then
    codesign -dv --verbose=2 "$LIBPY" 2>&1 \
        | grep -E "Identifier|Signature|TeamIdentifier"
fi

echo ""
echo "Done. The daemon should now start cleanly under ProcessManager."
echo "Test: $MAIN_BIN (will emit a daemon_start event then wait for stdin)"
