#!/bin/bash
#
# build-app.sh — Build a working .app bundle from `swift build` output
#
# The xcodebuild path keeps failing on mlx-swift CudaBuild plugin validation
# and the MLXHuggingFaceMacros strict-enable check. Both are upstream
# package quirks that don't affect macOS. We sidestep xcodebuild entirely
# and construct the .app bundle by hand from the SPM binary.
#
# This is the "real long-term fix" for the .app build — no xcodegen
# project, no xcodebuild, no plugin validation. The script is idempotent
# and runs in <5s once the build is cached.
#
# Usage:
#   ./Scripts/build-app.sh           # Debug build
#   ./Scripts/build-app.sh release   # Release build
#   CONFIG=release ./Scripts/build-app.sh
#
# Output:
#   build/VoltaPCB.app   — signable .app bundle
#

set -euo pipefail

# --- Configuration -----------------------------------------------------------

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

CONFIG="${CONFIG:-${1:-debug}}"
case "$CONFIG" in
    debug|Debug)    SWIFT_CONFIG="debug"   ;;
    release|Release) SWIFT_CONFIG="release" ;;
    *) echo "Unknown config: $CONFIG (use debug or release)"; exit 1 ;;
esac

PRODUCT_NAME="Volta PCB"
BUNDLE_ID="com.bretbouchard.volta"
APP_DIR="$ROOT/build/VoltaPCB.app"
BIN_DIR="$ROOT/.build/arm64-apple-macosx/$SWIFT_CONFIG"
BIN_SRC="$BIN_DIR/KiCadAgent"
CONTENTS="$APP_DIR/Contents"
MACOS_DIR="$CONTENTS/MacOS"
RESOURCES_DIR="$CONTENTS/Resources"

XCODE_DEV="/Applications/Xcode.app/Contents/Developer"
TESTING_FW_SRC="$XCODE_DEV/Platforms/MacOSX.platform/Developer/Library/Frameworks/Testing.framework"
TESTING_INTEROP_SRC="$XCODE_DEV/Platforms/MacOSX.platform/Developer/usr/lib/lib_TestingInterop.dylib"

# --- Sanity checks -----------------------------------------------------------

if [[ ! -d "$XCODE_DEV" ]]; then
    echo "error: Xcode not found at $XCODE_DEV" >&2
    exit 1
fi
if [[ ! -e "$TESTING_FW_SRC" ]]; then
    echo "error: Testing.framework not found at $TESTING_FW_SRC" >&2
    exit 1
fi
if [[ ! -e "$TESTING_INTEROP_SRC" ]]; then
    echo "error: lib_TestingInterop.dylib not found at $TESTING_INTEROP_SRC" >&2
    exit 1
fi

# --- Build -------------------------------------------------------------------

echo "▶ swift build -c $SWIFT_CONFIG"
swift build -c "$SWIFT_CONFIG"

if [[ ! -f "$BIN_SRC" ]]; then
    echo "error: built binary not found at $BIN_SRC" >&2
    exit 1
fi

# --- Construct .app bundle ---------------------------------------------------

echo "▶ Constructing $APP_DIR"

# Wipe any previous bundle so we're idempotent.
rm -rf "$APP_DIR"
mkdir -p "$MACOS_DIR" "$RESOURCES_DIR"

# Binary (rename to PRODUCT_NAME to match Info.plist)
cp "$BIN_SRC" "$MACOS_DIR/$PRODUCT_NAME"
chmod +x "$MACOS_DIR/$PRODUCT_NAME"

# Testing framework — binary's rpath is @loader_path, so the framework
# must live next to the executable in Contents/MacOS/, not Frameworks/.
cp -R "$TESTING_FW_SRC" "$MACOS_DIR/Testing.framework"

# Testing interop helper — same rpath-resolved location as the framework.
cp "$TESTING_INTEROP_SRC" "$MACOS_DIR/lib_TestingInterop.dylib"

# Resource bundles from SPM (mlx-swift_Cmlx, swift-crypto_Crypto, etc.)
for bundle in "$BIN_DIR"/*.bundle; do
    if [[ -d "$bundle" ]]; then
        cp -R "$bundle" "$RESOURCES_DIR/"
    fi
done

# App resources (Info.plist, AppIcon, entitlements, etc.)
cp "$ROOT/Resources/Info.plist" "$CONTENTS/Info.plist"
cp "$ROOT/Resources/AppIcon.icns" "$RESOURCES_DIR/AppIcon.icns"
cp "$ROOT/Resources/PrivacyInfo.xcprivacy" "$RESOURCES_DIR/PrivacyInfo.xcprivacy"
cp "$ROOT/Resources/KiCadAgent.entitlements" "$RESOURCES_DIR/KiCadAgent.entitlements"

# PkgInfo — required for the bundle to be recognized as an app
printf 'APPL????' > "$CONTENTS/PkgInfo"

# --- Code signing ------------------------------------------------------------

echo "▶ Ad-hoc signing"

# Ad-hoc sign without hardened runtime. We tried signing with
# --options runtime but Apple's Testing.framework carries a Developer
# ID certificate in its Mach-O even after we --force re-sign with -,
# and dyld's hardened-runtime check rejects the load (Team ID
# mismatch). Drop --options runtime so the .app loads cleanly during
# development. For App Store / TestFlight distribution, the real
# Developer ID signing (in fastlane match) replaces this step.

codesign --force --sign - --deep \
    --entitlements "$ROOT/Resources/KiCadAgent.entitlements" \
    "$MACOS_DIR/$PRODUCT_NAME"

codesign --force --sign - --deep \
    "$APP_DIR"

# --- Verify ------------------------------------------------------------------

echo "▶ Verifying"
codesign --verify --verbose=2 "$APP_DIR" 2>&1 | head -5 || true
spctl --assess --verbose=2 --type execute "$APP_DIR" 2>&1 | head -3 || true

echo ""
echo "✓ Built $APP_DIR"
echo "  Launch with: open '$APP_DIR'"
echo "  Or run:      '$MACOS_DIR/$PRODUCT_NAME'"
