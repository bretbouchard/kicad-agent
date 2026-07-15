#!/usr/bin/env python3
"""
Phase 250: Portable build setup.

Detects or downloads the canonical Volta v2 adapter, creates the
`volta-12b-v2` symlink at the repo root, and verifies the build
environment (Python version, kicad-cli presence).

Search order for canonical adapter:
1. /Volumes/Storage/models/kicad-agent/adapters/kicad-vision-v2
2. /Volumes/Storage/models/kicad-agent/adapters/volta-pcb-adapter-v2
3. ~/Library/Application Support/VoltaPCB/models/volta-pcb-adapter-v2/
4. HuggingFace cache: ~/.cache/huggingface/hub/bretbouchard--volta-pcb-adapter-v2/
5. Optional: download from HF (if --download flag set)

Usage:
    python3 scripts/setup_local.py             # detect and link only
    python3 scripts/setup_local.py --download  # detect, link, download if missing
    python3 scripts/setup_local.py --verify    # verify environment only, no changes
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SYMLINK_NAME = "volta-12b-v2"

# Candidate paths for the canonical Volta v2 adapter (in priority order)
STORAGE_PATHS = [
    Path("/Volumes/Storage/models/kicad-agent/adapters/kicad-vision-v2"),
    Path("/Volumes/Storage/models/kicad-agent/adapters/volta-pcb-adapter-v2"),
]

APP_CACHE_PATHS = [
    Path("~/Library/Application Support/VoltaPCB/models/volta-pcb-adapter-v2").expanduser(),
]

HF_CACHE_PATHS = [
    Path("~/.cache/huggingface/hub/bretbouchard--volta-pcb-adapter-v2").expanduser(),
]


def find_adapter() -> Path | None:
    """Find canonical Volta v2 adapter across known locations."""
    for paths in (STORAGE_PATHS, APP_CACHE_PATHS, HF_CACHE_PATHS):
        for p in paths:
            if p.exists() and (p / "adapter_config.json").exists():
                return p
    return None


def ensure_symlink(target: Path) -> bool:
    """Create or update the volta-12b-v2 symlink at repo root."""
    link_path = REPO_ROOT / SYMLINK_NAME
    if link_path.is_symlink():
        existing = link_path.resolve()
        if existing == target.resolve():
            print(f"  Symlink already correct: {SYMLINK_NAME} -> {target}")
            return True
        print(f"  Removing stale symlink: {SYMLINK_NAME} -> {existing}")
        link_path.unlink()
    if link_path.exists():
        print(f"  WARNING: {SYMLINK_NAME} exists but is not a symlink. Skipping.")
        return False
    os.symlink(target, link_path)
    print(f"  Created symlink: {SYMLINK_NAME} -> {target}")
    return True


def download_from_hf(target_dir: Path) -> bool:
    """Download adapter from HuggingFace (requires huggingface-cli)."""
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "huggingface-cli", "download",
        "bretbouchard/volta-pcb-adapter-v2",
        "--local-dir", str(target_dir),
    ]
    print(f"  Running: {' '.join(cmd)}")
    try:
        subprocess.run(cmd, check=True)
        return target_dir.exists()
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"  Download failed: {e}")
        return False


def verify_environment() -> dict:
    """Check Python version, kicad-cli, and base model availability."""
    results = {}

    # Python version
    py_ver = sys.version_info
    results["python"] = {
        "version": f"{py_ver.major}.{py_ver.minor}.{py_ver.micro}",
        "ok": py_ver >= (3, 11),
        "required": ">=3.11",
    }

    # kicad-cli presence
    kicad = shutil.which("kicad-cli")
    results["kicad-cli"] = {
        "path": kicad,
        "ok": kicad is not None,
        "required": "optional (only for kicad-cli features)",
    }

    # symlink status
    link_path = REPO_ROOT / SYMLINK_NAME
    if link_path.is_symlink():
        target = link_path.resolve()
        results["adapter-symlink"] = {
            "target": str(target),
            "exists": target.exists(),
            "ok": target.exists() and (target / "adapter_config.json").exists(),
        }
    else:
        results["adapter-symlink"] = {
            "target": None,
            "exists": False,
            "ok": False,
        }

    return results


def main():
    parser = argparse.ArgumentParser(description="Setup local build environment")
    parser.add_argument("--download", action="store_true",
                        help="Download from HuggingFace if adapter not found locally")
    parser.add_argument("--verify", action="store_true",
                        help="Verify environment only, no changes")
    args = parser.parse_args()

    print("=" * 60)
    print("Phase 250: Portable build setup")
    print("=" * 60)

    # Verify environment
    print("\n[1/3] Verifying environment...")
    env = verify_environment()
    for key, info in env.items():
        status = "OK" if info["ok"] else "FAIL"
        print(f"  {key}: {status}")
        for k, v in info.items():
            if k != "ok":
                print(f"    {k}: {v}")

    if args.verify:
        print("\n[verify] Environment check complete.")
        return 0 if all(i["ok"] for i in env.values() if i.get("required", "yes") != "optional") else 1

    # Find adapter
    print("\n[2/3] Locating Volta v2 adapter...")
    adapter_path = find_adapter()
    if adapter_path:
        print(f"  Found: {adapter_path}")
    elif args.download:
        print("  Not found locally. Downloading from HuggingFace...")
        target = Path("~/.cache/huggingface/hub/bretbouchard--volta-pcb-adapter-v2").expanduser()
        if download_from_hf(target):
            adapter_path = target
        else:
            print("  ERROR: Download failed. Set up adapter manually.")
            return 1
    else:
        print("  ERROR: Adapter not found.")
        print("  Hint: pass --download to fetch from HuggingFace,")
        print("        or place adapter at one of:")
        for p in STORAGE_PATHS + APP_CACHE_PATHS + HF_CACHE_PATHS:
            print(f"          - {p}")
        return 1

    # Create symlink
    print("\n[3/3] Setting up symlink...")
    if ensure_symlink(adapter_path):
        print(f"\n  Setup complete. Adapter: {adapter_path}")
        return 0
    print("\n  Setup failed at symlink step.")
    return 1


if __name__ == "__main__":
    sys.exit(main())