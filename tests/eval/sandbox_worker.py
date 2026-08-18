"""Sandbox worker — executes SKiDL predictions in an isolated child process.

Volta-ko7: tests/eval/metrics.py previously exec'd model predictions
in-process. skidl keeps process-global state (default_circuit, library
cache, tool config), so every executed prediction polluted the test
process and broke later suites (volta.sim RecursionError, 'library
UNKNOWN'). This worker owns ALL skidl usage for the eval harness; the
parent never imports skidl.

Protocol (JSON lines on stdin/stdout):
    request:  {"id": <int>, "code": <str>}
    response: {"id": <int>, "ok": true}
            | {"id": <int>, "ok": false, "error": "<error_class: msg>"}

Each request runs against a FRESH skidl.Circuit (default_circuit swap),
so predictions never accumulate onto one graph. CR-01 import restriction
is enforced identically to the previous in-process sandbox.

Run manually: .venv/bin/python -m tests.eval.sandbox_worker
"""

from __future__ import annotations

import json
import sys


def _restricted_builtins() -> dict:
    """Builtins for the exec namespace — CR-01: skidl-only imports."""

    def _safe_import(name, *args, **kwargs):
        if not (name == "skidl" or name.startswith("skidl.")):
            raise ImportError(
                f"Import of '{name}' is not permitted in eval sandbox"
            )
        return __import__(name, *args, **kwargs)

    return {"__import__": _safe_import}


def main() -> int:
    # Import volta's skidl environment FIRST: stable backup-lib config +
    # library-path memoization + the symbol dir env vars that make
    # Part("Device", ...) resolvable. Bare skidl cannot find KiCad libs.
    import volta.circuit_ir  # noqa: F401

    import skidl

    from skidl import KICAD, Net, Part, ERC, generate_netlist, set_default_tool

    set_default_tool(KICAD)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except ValueError:
            continue

        rid = request.get("id", 0)
        code = request.get("code", "")

        try:
            # Fresh circuit graph per prediction — Parts/Nets register on
            # default_circuit at creation; swapping (not reset()) gives each
            # request a pristine graph without disturbing skidl's caches.
            skidl.default_circuit = skidl.Circuit()

            ns = {
                "Part": Part,
                "Net": Net,
                "generate_netlist": generate_netlist,
                "ERC": ERC,
                "KICAD": KICAD,
                "set_default_tool": set_default_tool,
                "__builtins__": _restricted_builtins(),
            }
            exec(code, ns)  # noqa: S102 — the entire point, restricted ns
            ERC()
            response = {"id": rid, "ok": True}
        except Exception as exc:  # noqa: BLE001 — sandbox boundary
            error_msg = str(exc) if str(exc) else type(exc).__name__
            response = {"id": rid, "ok": False, "error": f"skidl_erc_failed: {error_msg}"}

        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()

    return 0


if __name__ == "__main__":
    sys.exit(main())
