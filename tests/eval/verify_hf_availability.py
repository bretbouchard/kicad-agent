"""Verify Volta v2 adapter is published on HuggingFace.

Run as a prerequisite to the eval harness. Exits 0 if adapter is
available with the required files, 2 if not.

WR-02 fix: SHA256 hash verification for adapter_model.safetensors,
not exact byte-size comparison. Size is brittle across rebuilds; SHA256
binds the file contents to the published artifact.
"""
import hashlib
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
# SHA256 of the published adapter_model.safetensors.
# Set this to the actual hash once the v2 adapter is published to HF.
# If unset, we fall back to size verification (which is logged as a warning).
EXPECTED_SAFETENSORS_SHA256 = os.environ.get(
    "VOLTA_ADAPTER_SHA256", ""
)
# Fallback observed size (524MB) for environments without SHA256 verification
EXPECTED_SAFETENSORS_SIZE = 524649216


def sha256_of_file(path: Path) -> str:
    """Compute SHA256 of a file. Streamed to avoid loading 524MB into memory."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


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


def verify_local_adapter(local_path: str) -> int:
    """Verify local adapter file integrity. Returns exit code."""
    safetensors = Path(local_path) / "adapter_model.safetensors"
    if EXPECTED_SAFETENSORS_SHA256:
        # Preferred: SHA256 verification
        actual = sha256_of_file(safetensors)
        print(f"  adapter_model.safetensors sha256: {actual}")
        if actual != EXPECTED_SAFETENSORS_SHA256:
            print(f"  EXPECTED: {EXPECTED_SAFETENSORS_SHA256}")
            print(f"  FAIL: SHA256 mismatch (security check failed)")
            return 2
    else:
        # Fallback: size verification (logs warning to encourage SHA256 setup)
        actual_size = safetensors.stat().st_size
        print(f"  adapter_model.safetensors size: {actual_size} bytes "
              f"(expected: {EXPECTED_SAFETENSORS_SIZE})")
        print(f"  NOTE: Size verification is fragile. Set VOLTA_ADAPTER_SHA256 "
              f"env var to enable SHA256 verification.")
        if actual_size != EXPECTED_SAFETENSORS_SIZE:
            print(f"  WARNING: Size mismatch! (security check failed)")
            return 2
    return 0


def main():
    # First check local path (for offline/air-gapped environments)
    local_path = os.environ.get("VOLTA_ADAPTER_LOCAL_PATH",
                                  "/Volumes/Storage/models/volta/adapters/volta-12b-v2")
    ok, issues = check_local_path(local_path)
    if ok:
        print(f"OK: Local adapter at {local_path} has all {len(REQUIRED_FILES)} required files")
        rc = verify_local_adapter(local_path)
        return rc
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