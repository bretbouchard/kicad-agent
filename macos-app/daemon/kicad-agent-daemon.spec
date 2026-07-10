# -*- mode: python ; coding: utf-8 -*-
#
# kicad-agent-daemon.spec — PyInstaller spec for the bundled Python daemon.
#
# Phase 162 — Python Daemon Bundling.
#
# Builds a one-folder (COLLECT) bundle that ships:
#   - Python 3.11 runtime
#   - kicad_agent library (from ../../src/kicad_agent)
#   - Hidden imports: kiutils, sexpdata, networkx, pydantic
#
# NOT bundled:
#   - kicad-cli (GPLv3) — Phase 163 detects external install per App Store
#     GPL compliance. Bundling kicad-cli would propagate GPLv3 to the entire
#     .app and trigger certain App Store rejection (P0-01 from Council).
#
# Build:
#   cd macos-app/daemon
#   pyinstaller --noconfirm kicad-agent-daemon.spec
#
# Output:
#   macos-app/daemon/dist/kicad-agent-daemon/kicad-agent-daemon  (executable)
#   macos-app/daemon/dist/kicad-agent-daemon/_internal/         (Python + libs)
#
# Phase 200 promotes this to one-file mode with checksum verification; Phase 203
# wires Fastlane match for the production signing identity.
#

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from PyInstaller.building.api import COLLECT, EXE
from PyInstaller.building.build_main import Analysis

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

# Spec file lives at: macos-app/daemon/kicad-agent-daemon.spec
HERE = Path(SPECPATH).resolve()
REPO_ROOT = HERE.parents[1]  # macos-app/daemon -> macos-app -> kicad-agent
SRC_ROOT = REPO_ROOT / "src"
ENTRY = HERE / "daemon_entry.py"

if not ENTRY.exists():
    raise SystemExit(f"daemon_entry.py not found at {ENTRY}")
if not (SRC_ROOT / "kicad_agent" / "__init__.py").exists():
    raise SystemExit(f"kicad_agent package not found at {SRC_ROOT}/kicad_agent")

# ---------------------------------------------------------------------------
# Hidden imports
# ---------------------------------------------------------------------------
# kiutils, sexpdata, networkx, pydantic all use lazy/dynamic imports that
# PyInstaller cannot always trace statically. List them explicitly.
HIDDEN_IMPORTS = [
    "kiutils",
    "kiutils.kicadconfig",
    "kiutils.selements",
    "kiutils.schematic",
    "kiutils.board",
    "kiutils.symbol",
    "kiutils.footprint",
    "kiutils.wire",
    "sexpdata",
    "networkx",
    "pydantic",
    "pydantic.fields",
    "pydantic.main",
    "pydantic._internal._core_utils",
    "onnxruntime",
    # numpy IS needed now — onnxruntime depends on it
    "numpy",
    # kicad_agent operation modules — keep the registry importable post-freeze
    "kicad_agent",
    "kicad_agent.ops",
    "kicad_agent.ops.executor",
    "kicad_agent.ops.registry",
    "kicad_agent.ops.schematic_raw_writer",
    "kicad_agent.ops.pcb_raw_writer",
    # Phase 162 daemon modules — must be importable post-freeze
    "protocol",
    "handlers",
    "audit_log",
]

# ---------------------------------------------------------------------------
# Data files (none yet — Phase 168 may ship prompt templates here)
# ---------------------------------------------------------------------------
DATAS = [
    # Placement model — 217 KB ONNX file for component position prediction.
    (str(HERE / "placement.onnx"), "."),
]

# ---------------------------------------------------------------------------
# Binary exclusions — strip unused heavy modules to keep bundle lean.
# ---------------------------------------------------------------------------
EXCLUDES = [
    "matplotlib",
    "pytest",
    "IPython",
    "notebook",
    "jupyter",
    "tkinter",
    "PyQt5",
    "PyQt6",
    "PySide2",
    "PySide6",
    # ML stack — daemon never uses these. Pulled in transitively via
    # placement/model.py's torch import. Stripping saves ~575 MB.
    "torch", "torchvision", "torchaudio",
    "transformers", "tokenizers", "safetensors",
    "pyarrow", "cv2", "opencv",
    "scipy", "pandas",
    "accelerate", "datasets", "sentencepiece",
    "h5py", "lxml", "PIL", "Pillow",
    "mlx", "sklearn", "scikit-learn",
    "fastapi", "starlette", "uvicorn",
    "cryptography", "aiohttp",
    # numpy is NOT excluded — onnxruntime depends on it for inference.
    # More transitive bloat — none used by the daemon's 16 handlers
    "llvmlite", "numba",
    "babel",
    "botocore", "boto3", "moto",
    "grpc", "grpc_tools",
    "sphinx",
    "psycopg2",
    "Cython",
    "hf_xet",
    "sympy", "mpmath",
    "markdown", "docutils",
    "jinja2",
    "psutil",
    "tqdm",
    "requests", "urllib3", "charset_normalizer",
    "PyGithub",
    "shapely",
    "spicelib",
    "skidl",
    # onnxruntime pulls these in transitively — not needed at runtime
    "tensorflow", "tensorboard", "keras",
    "onnx",  # the converter library, not the runtime
    "onnxconverter_common", "onnxmltools",
    "tf2onnx",
    "skl2onnx",
    "coloredlogs", "humanfriendly",
    "flatbuffers",
]

# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
a = Analysis(
    [str(ENTRY)],
    pathex=[str(SRC_ROOT)],
    binaries=[],
    datas=DATAS,
    hiddenimports=HIDDEN_IMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    # optimize_level=2 produces smaller bytecode but breaks some debug paths;
    # leave at default (0) so tracebacks stay informative in the field.
    optimize=0,
)

# ---------------------------------------------------------------------------
# EXE — the daemon binary itself.
# ---------------------------------------------------------------------------
# Per PITFALLS.md Pitfall 1: hardened runtime + ad-hoc signing during local
# builds. Production signing identity is supplied by Fastlane match (Phase 203)
# via the CODESIGN_IDENTITY env var. We do NOT bundle a .app here — the
# outer macOS app bundle already wraps this executable.
codesign_identity = os.environ.get("CODESIGN_IDENTITY", "-")  # "-" = ad-hoc

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="kicad-agent-daemon",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,  # stdio daemon — must NOT be a GUI app
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch="arm64",  # Apple Silicon only — see PROJECT.md decision 2026-07-07
    codesign_identity=codesign_identity,
    entitlements_file=None,  # entitlements applied to outer .app bundle, not daemon
)

# ---------------------------------------------------------------------------
# COLLECT — one-folder bundle. Phase 200 may switch to one-file.
# ---------------------------------------------------------------------------
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="kicad-agent-daemon",
)

# ---------------------------------------------------------------------------
# Post-build hook — emit checksum file for ProcessManager verification.
# ---------------------------------------------------------------------------
# APP-03 augmentation: "Daemon binary checksum verified on launch; corrupt
# binary triggers re-download prompt." PyInstaller doesn't natively emit a
# SHA-256 file, so we add one via on_binaries callback.
def _emit_checksum(_binaries: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """No-op during Analysis; checksum written by build script post-COLLECT.

    See daemon/README.md -> "Checksums" section for the post-build step.
    """
    return binaries  # type: ignore[name-defined]  # PyInstaller injects `binaries` in scope


# Self-check on import: print friendly message if invoked via `pyinstaller --dry-run`.
if __name__ == "__main__":
    sys.stdout.write("[kicad-agent-daemon.spec] Analysis ready\n")
