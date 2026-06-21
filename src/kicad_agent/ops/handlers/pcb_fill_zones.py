"""Fill copper zones on a PCB using KiCad's bundled pcbnew Python API.

This handler uses a subprocess re-exec pattern: it writes a temporary Python
script that imports pcbnew (KiCad's native module) and runs ZONE_FILLER,
then executes that script with KiCad's bundled Python interpreter.

pcbnew.SaveBoard uses KiCad's native serialization -- this is the ONLY
safe way to write PCB files with filled zone geometry. The kiutils
corruption risk (per D-01) does not apply to pcbnew operations.

See: fill_zones.py reference implementation in analog-ecosystem.
"""

import json
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

from kicad_agent.ir.pcb_ir import PcbIR

logger = logging.getLogger(__name__)

_FILL_ZONES_HANDLERS: dict[str, Callable] = {}


def register_fill_zones(op_type: str) -> Callable:
    """Decorator to register a fill_zones operation handler."""
    def decorator(fn: Callable) -> Callable:
        _FILL_ZONES_HANDLERS[op_type] = fn
        return fn
    return decorator


# ---------------------------------------------------------------------------
# KiCad path detection (macOS)
# ---------------------------------------------------------------------------

KICAD_APP = "/Applications/KiCad/KiCad.app"
KICAD_PYTHON = os.path.join(
    KICAD_APP,
    "Contents/Frameworks/Python.framework/Versions/3.9/bin/python3",
)
KICAD_DYLD = os.path.join(KICAD_APP, "Contents/Frameworks")


def _detect_kicad_python() -> str | None:
    """Detect KiCad's bundled Python interpreter.

    Returns the path to the Python binary if found, None otherwise.
    Currently supports macOS (KiCad.app bundle).
    """
    if os.path.exists(KICAD_PYTHON):
        return KICAD_PYTHON
    return None


# ---------------------------------------------------------------------------
# Subprocess helper script
# ---------------------------------------------------------------------------

_FILL_SCRIPT = """
import json
import os
import sys

board_path = sys.argv[1]
result_path = sys.argv[2]
dry_run = sys.argv[3] == "true"

import wx
wx.App(False)

import pcbnew

board = pcbnew.LoadBoard(board_path)
zones = board.Zones()
zone_list = []

for i, zone in enumerate(zones):
    layer = zone.GetLayerName()
    net = zone.GetNetname()
    zone_list.append({"index": i, "layer": layer, "net": net})

result = {
    "zones": zone_list,
    "filled_count": len(zone_list),
    "dry_run": dry_run,
}

if not dry_run:
    filler = pcbnew.ZONE_FILLER(board)
    filler.Fill(zones)
    pcbnew.SaveBoard(board_path, board)
    result["filled"] = True

with open(result_path, "w") as f:
    json.dump(result, f, indent=2)
"""


@register_fill_zones("fill_zones")
def _handle_fill_zones(
    op: Any,
    ir: PcbIR,
    file_path: Path,
) -> dict[str, Any]:
    """Fill copper zones on a PCB using pcbnew ZONE_FILLER.

    Creates a backup before modification, then spawns a subprocess
    using KiCad's bundled Python to run pcbnew operations.

    pcbnew's ZONE_FILLER fills ALL zones unconditionally; per-layer
    filtering is not supported by the underlying engine.

    Args:
        op: FillZonesOp with target_file, dry_run.
        ir: PcbIR (not used -- pcbnew operates directly on file).
        file_path: Resolved path to the .kicad_pcb file.

    Returns:
        Dict with filled_count, zones list, and dry_run status.
    """
    kicad_python = _detect_kicad_python()
    if kicad_python is None:
        return {
            "success": False,
            "error": (
                "KiCad bundled Python not found. "
                "Install KiCad 10+ to /Applications/KiCad/KiCad.app"
            ),
            "filled_count": 0,
            "zones": [],
        }

    dry_run = op.dry_run

    # Backup before any mutation (unless dry run)
    if not dry_run:
        backup_path = str(file_path) + ".bak"
        try:
            shutil.copy2(file_path, backup_path)
            logger.info("Backup created: %s", backup_path)
        except OSError as exc:
            return {
                "success": False,
                "error": f"Failed to create backup: {exc}",
                "filled_count": 0,
                "zones": [],
            }

    # Write temporary script and result file
    script_dir = tempfile.mkdtemp(prefix="kicad_fill_zones_")
    try:
        script_path = os.path.join(script_dir, "fill_zones_runner.py")
        result_path = os.path.join(script_dir, "result.json")

        with open(script_path, "w") as f:
            f.write(_FILL_SCRIPT)

        # Execute with KiCad's Python, setting DYLD_LIBRARY_PATH
        env = os.environ.copy()
        env["DYLD_LIBRARY_PATH"] = KICAD_DYLD

        cmd = [kicad_python, script_path, str(file_path), result_path, "true" if dry_run else "false"]

        proc = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )

        if proc.returncode != 0:
            logger.error("fill_zones subprocess failed: %s", proc.stderr)
            return {
                "success": False,
                "error": f"pcbnew subprocess failed (exit {proc.returncode}): {proc.stderr.strip()}",
                "filled_count": 0,
                "zones": [],
            }

        # Read result JSON
        if not os.path.exists(result_path):
            return {
                "success": False,
                "error": "pcbnew subprocess completed but did not write result file",
                "filled_count": 0,
                "zones": [],
            }

        with open(result_path, "r") as f:
            result = json.load(f)

        # Mark IR as raw-written so execute_pcb skips kiutils serialization.
        # pcbnew.SaveBoard already wrote the file; we don't need to write again.
        if not dry_run:
            ir._raw_written = True

        return {
            "success": True,
            "filled_count": result.get("filled_count", 0),
            "zones": result.get("zones", []),
            "dry_run": dry_run,
        }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": "pcbnew subprocess timed out (120s)",
            "filled_count": 0,
            "zones": [],
        }
    except Exception as exc:
        logger.exception("fill_zones unexpected error")
        return {
            "success": False,
            "error": str(exc),
            "filled_count": 0,
            "zones": [],
        }
    finally:
        # Cleanup temp directory
        try:
            shutil.rmtree(script_dir, ignore_errors=True)
        except OSError:
            pass
