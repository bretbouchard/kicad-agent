#!/bin/bash
# build_erc_cli.sh — Phase 234B Swift CLI harness build
#
# Compiles the 4 Swift files (NativeERC + parser + topology) plus the
# thin CLI wrapper into a single standalone binary. No package changes.
# Target: macOS 14+ (matches Swift 6 toolchain).
set -euo pipefail

REPO_ROOT="/Users/bretbouchard/apps/kicad-agent"
SRC_DIR="$REPO_ROOT/macos-app/Sources"
BUILD_DIR="$REPO_ROOT/.planning/phases/234b-parity-execute"
OUT="$BUILD_DIR/erc-cli"

mkdir -p "$BUILD_DIR"

echo "Compiling erc-cli (Phase 234B)..."

swiftc -O \
  -target arm64-apple-macos14.0 \
  -framework Foundation \
  "$SRC_DIR/KiCadAgent/Parsing/SExpression.swift" \
  "$SRC_DIR/KiCadAgent/Parsing/SchematicParser.swift" \
  "$SRC_DIR/KiCadAgent/Parsing/TopologyBuilder.swift" \
  "$SRC_DIR/KiCadAgent/Validation/NativeERC.swift" \
  "$SRC_DIR/erc-cli/main.swift" \
  -o "$OUT"

echo "Built: $OUT"
ls -la "$OUT"
