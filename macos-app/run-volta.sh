#!/usr/bin/env bash
# Launcher for Volta SPM binary.
# The .build/debug/Volta binary links against @rpath/Testing.framework
# (swift-testing) but has no rpath entries pointing at the developer
# frameworks directory. swift build doesn't bundle it; Xcode does. Set
# DYLD_FRAMEWORK_PATH so the SPM-built binary can find Testing.framework
# at runtime, and any other future developer-only frameworks.

set -euo pipefail

# Pin to the same Xcode used to build (xcode-select -p)
DEVELOPER_FRAMEWORKS="$(xcode-select -p)/Platforms/MacOSX.platform/Developer/Library/Frameworks"
SHARED_FRAMEWORKS="$(xcode-select -p)/../SharedFrameworks"

if [ ! -d "$DEVELOPER_FRAMEWORKS/Testing.framework" ]; then
    echo "ERROR: Testing.framework not found at $DEVELOPER_FRAMEWORKS" >&2
    exit 1
fi

export DYLD_FRAMEWORK_PATH="$DEVELOPER_FRAMEWORKS:$SHARED_FRAMEWORKS${DYLD_FRAMEWORK_PATH:+:$DYLD_FRAMEWORK_PATH}"
export DYLD_FALLBACK_FRAMEWORK_PATH="$DEVELOPER_FRAMEWORKS:$SHARED_FRAMEWORKS"

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$DIR/.build/debug/Volta" "$@"
