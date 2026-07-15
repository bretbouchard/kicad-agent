# kicad-agent Daemon (PyInstaller Bundle)

Phase 162 — Python Daemon Bundling.

This directory builds the bundled Python daemon that ships inside the macOS
app. The Swift `ProcessManager` spawns the resulting binary on app launch;
the daemon speaks line-delimited JSON-RPC 2.0 over stdin/stdout.

## Layout

```
daemon/
├── daemon_entry.py              # asyncio entry; main loop, signal handling
├── protocol.py                  # JSON-RPC 2.0 envelopes, RpcError, parse_request
├── handlers.py                  # ping, list_operations, health_check, shutdown
├── audit_log.py                 # append-only JSONL audit trail with fsync
├── kicad-agent-daemon.spec      # PyInstaller spec (one-folder mode)
├── requirements-daemon.txt      # Python deps pinned for the bundle
├── README.md                    # this file
├── tests/                       # pytest suite (97 tests)
│   ├── conftest.py              # sys.path bootstrap
│   ├── test_protocol.py         # JSON-RPC envelope tests
│   ├── test_handlers.py         # RPC handler tests
│   ├── test_audit_log.py        # Audit logger tests
│   └── test_dispatch.py         # End-to-end dispatch tests
├── build/                       # PyInstaller intermediate artifacts (gitignored)
└── dist/
    └── kicad-agent-daemon/
        ├── kicad-agent-daemon   # executable
        ├── kicad-agent-daemon.sha256
        └── _internal/           # Python runtime + libraries
```

## Module split (Phase 162)

The daemon is split into four single-purpose modules so each layer is
independently testable:

| Module           | Responsibility                                       | Tests                   |
| ---------------- | ---------------------------------------------------- | ----------------------- |
| `protocol.py`    | JSON-RPC envelopes, RpcError, parse_request, serialize | `test_protocol.py`      |
| `handlers.py`    | RPC method handlers + HandlerContext                 | `test_handlers.py`      |
| `audit_log.py`   | Append-only JSONL audit trail with fsync durability  | `test_audit_log.py`     |
| `daemon_entry.py`| asyncio main loop, signal handling, IPC wiring       | `test_dispatch.py`      |

## Build

```bash
# From repo root — uses the project's .venv (Python 3.11) so versions match.
cd macos-app/daemon
/Users/bretbouchard/apps/kicad-agent/.venv/bin/pyinstaller --noconfirm \
    kicad-agent-daemon.spec
```

Output: `macos-app/daemon/dist/kicad-agent-daemon/`.

## Verify

```bash
# Run the daemon against a `ping` request.
echo '{"jsonrpc":"2.0","id":"1","method":"ping","params":{}}' | \
    ./dist/kicad-agent-daemon/kicad-agent-daemon
# Expect: {"jsonrpc":"2.0","id":"1","result":{"pong":true,"epoch":...}}
```

## Tests

```bash
cd macos-app/daemon
/Users/bretbouchard/apps/kicad-agent/.venv/bin/python -m pytest tests/ -v
# Expect: 97 passed in <1s
```

The test suite covers:
- `test_protocol.py` — JSON-RPC envelopes, RpcError, parse_request, serialize (29 tests)
- `test_handlers.py` — ping, list_operations, health_check, shutdown, param validation (24 tests)
- `test_audit_log.py` — JSONL format, never-raises invariant, convenience methods, file logger (20 tests)
- `test_dispatch.py` — End-to-end dispatch including parse error, method not found (12 tests)

## Checksums (APP-03)

After a successful build, emit a SHA-256 next to the executable:

```bash
cd dist/kicad-agent-daemon
shasum -a 256 kicad-agent-daemon > kicad-agent-daemon.sha256
```

`ProcessManager.spawn()` reads `kicad-agent-daemon.sha256` and compares it
to a SHA-256 computed over the bundled executable. On mismatch the
`DaemonSupervisor` transitions to `.failed(.checksumMismatch)` and the
recovery UI surfaces a "Re-download daemon" prompt.

The `.sha256` file is the **source of truth at runtime**. It is regenerated
on every PyInstaller build. Phase 200 will pin a build-time checksum into
the Swift binary so a tampered `.sha256` file is also detectable.

## Code Signing (Pitfall 1)

Local dev builds use ad-hoc signing (`CODESIGN_IDENTITY="-"`). Production
builds pass a Developer ID via the env var:

```bash
CODESIGN_IDENTITY="Developer ID Application: ..." \
    /Users/bretbouchard/apps/kicad-agent/.venv/bin/pyinstaller \
    --noconfirm kicad-agent-daemon.spec
```

Phase 203 (Fastlane match) automates this.

### Verifying every embedded dylib

Before shipping, every dylib under `dist/kicad-agent-daemon/_internal/` must
show "valid on disk":

```bash
find dist/kicad-agent-daemon -name "*.dylib" -print0 | \
    while IFS= read -r -d '' lib; do
        echo "--- $lib ---"
        codesign -dv --verbose=4 "$lib" 2>&1 | grep -E "(valid on disk|Authority)"
    done
```

If any dylib is unsigned, sign it before packaging:

```bash
codesign --force --options runtime --sign "$CODESIGN_IDENTITY" \
    dist/kicad-agent-daemon/_internal/<lib>.dylib
```

## What's NOT bundled

- **kicad-cli** — GPLv3; bundling it would propagate GPL to the whole app
  and trigger certain App Store rejection. Phase 163 detects an external
  KiCad install at first run and offers a guided download if missing.
- **MLX / MLX-Swift** — separate concern; only loaded by the AI inference
  layer when FoundationModels is unavailable.
- **pytest / dev tools** — explicitly excluded in the spec file.

## Protocol

Line-delimited JSON-RPC 2.0 over stdin/stdout, UTF-8, `\n` terminator.

| Direction | Message                                                           |
| --------- | ---------------------------------------------------------------- |
| App → Daemon | `{"jsonrpc":"2.0","id":"<uuid>","method":"ping","params":{}}` |
| Daemon → App | `{"jsonrpc":"2.0","id":"<uuid>","result":{"pong":true,...}}`   |
| Daemon → App | `{"jsonrpc":"2.0","method":"heartbeat","params":{...}}`        |
| Daemon → App | `{"jsonrpc":"2.0","id":"<uuid>","error":{"code":...,}}`        |

Methods:

| Method             | Params                  | Result                                            |
| ------------------ | ----------------------- | ------------------------------------------------- |
| `ping`             | `{}`                    | `{"pong": true, "epoch": <float>}`                |
| `health`           | `{}`                    | alias for `health_check`                          |
| `health_check`     | `{}`                    | `{"ok": true, "ops_registered": <int>, ...}`      |
| `list_operations`  | `{}`                    | `{"count": <int>, "operations": [<op>, ...]}`     |
| `shutdown`         | `{}`                    | `{"shutting_down": true}` (then exits)            |
| `execute`          | `{"op": "...", ...}`    | Phase 168 — full OperationExecutor dispatch       |

Phase 167 upgrades this minimal JSON-RPC surface to full MCP; Phase 168
wires the Swift MCP client to use it.

## Troubleshooting

| Symptom                              | Likely cause                                  | Fix                                                  |
| ------------------------------------ | --------------------------------------------- | --------------------------------------------------- |
| `killed: 9` on launch                | Unsigned dylib (Pitfall 1)                    | Sign all dylibs per above                           |
| App hangs waiting for first response | stdout block-buffered (Pitfall 2)             | Verify `PYTHONUNBUFFERED=1` is set in env           |
| `Method not found`                   | Daemon version older than Swift client        | Rebuild daemon, redeploy bundle                     |
| Crash loop on launch                 | volta library missing from hidden imports | Add module to `HIDDEN_IMPORTS` in spec              |
