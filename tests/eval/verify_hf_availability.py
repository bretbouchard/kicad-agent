"""Verify Volta v2 adapter is published on HuggingFace.

Run as a prerequisite to the eval harness. Exits 0 if adapter is
available with the required files, 2 if not.
"""
import sys
import os
from pathlib import Path

ADAPTER_REPO = "bretbouchard/volta-pcb-adapter-v2"
REQUIRED_FILES = [
    "adapter_config.json",
    "adapter_model.safetensors",
    "tokenizer.json",
    "tokenizer_config.json",
    "chat_template.jinja",
]
EXPECTED_SAFETENSORS_SIZE = 524649216  # 524MB, observed in Phase 245

def check_local_path(local_path: str) -> tuple[bool, list[str]]:
    """Check local adapter directory for required files."""
    path = Path(local_path)
    if not path.exists():
        return False, [f"Local path {local_path} does not exist"]
    missing = []
    for f in REQUIRED_FILES:
        if not (path / f).exists():
            missing.append(f)
    return len(missing) == 0, missing

def check_hf_api() -> tuple[bool, list[str]]:
    """Check HuggingFace API for adapter files."""
    try:
        import requests
    except ImportError:
        return False, ["requests not installed"]

    try:
        r = requests.get(f"https://huggingface.co/api/models/{ADAPTER_REPO}", timeout=10)
        if r.status_code == 404:
            return False, [f"HF repo {ADAPTER_REPO} not found"]
        r.raise_for_status()
        data = r.json()
        files = {s["rfilename"] for s in data.get("siblings", [])}
        missing = [f for f in REQUIRED_FILES if f not in files]
        return len(missing) == 0, missing
    except Exception as e:
        return False, [f"HF API error: {e}"]

def main():
    # First check local path (for offline/air-gapped environments)
    local_path = os.environ.get("VOLTA_ADAPTER_LOCAL_PATH",
                                  "/Volumes/Storage/models/kicad-agent/adapters/volta-12b-v2")
    ok, issues = check_local_path(local_path)
    if ok:
        safetensors = Path(local_path) / "adapter_model.safetensors"
        actual_size = safetensors.stat().st_size
        print(f"OK: Local adapter at {local_path} has all {len(REQUIRED_FILES)} required files")
        print(f"  adapter_model.safetensors size: {actual_size} bytes (expected: {EXPECTED_SAFETENSORS_SIZE})")
        if actual_size != EXPECTED_SAFETENSORS_SIZE:
            print(f"  WARNING: Size mismatch! (security check failed)")
            return 2
        return 0
    elif issues and "does not exist" in issues[0]:
        # Local path not found, try HF API
        print(f"Local adapter not found, checking HuggingFace...")
        ok, issues = check_hf_api()
        if not ok:
            print(f"FAIL: {', '.join(issues)}")
            return 2
    # Note: If local path exists but has missing files, report that
    if not ok:
        print(f"FAIL: Local adapter missing files: {issues}")
        return 2
    return 0

if __name__ == "__main__":
    sys.exit(main())