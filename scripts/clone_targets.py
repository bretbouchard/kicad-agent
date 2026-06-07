#!/usr/bin/env python3
"""Shallow-clone a list of GitHub repos into kicad_staging with checkpointing.

Usage:
    python3 scripts/clone_targets.py /tmp/clone_targets.json
    python3 scripts/clone_targets.py /tmp/clone_targets.json --resume
"""

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [clone_targets] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

STAGING_DIR = Path("kicad_staging")
TIMEOUT = 120  # seconds per clone


def repo_to_dirname(full_name: str) -> str:
    return full_name.replace("/", "_")


def clone_repo(full_name: str, staging_dir: Path) -> bool:
    """Shallow clone a repo. Returns True on success."""
    dirname = repo_to_dirname(full_name)
    target = staging_dir / dirname

    if target.is_dir() and any(target.iterdir()):
        return True  # already cloned

    url = f"https://github.com/{full_name}.git"
    try:
        result = subprocess.run(
            ["git", "clone", "--depth", "1", "--filter=blob:none", url, str(target)],
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )
        if result.returncode == 0:
            return True
        stderr = result.stderr.strip()[:200]
        # Common non-fatal conditions
        if "not found" in stderr.lower() or "does not exist" in stderr.lower():
            logger.debug("Repo gone: %s", full_name)
        else:
            logger.warning("Clone failed %s: %s", full_name, stderr)
        # Cleanup failed clone dir
        if target.is_dir():
            import shutil
            shutil.rmtree(target, ignore_errors=True)
        return False

    except subprocess.TimeoutExpired:
        logger.warning("Timeout cloning %s", full_name)
        if target.is_dir():
            import shutil
            shutil.rmtree(target, ignore_errors=True)
        return False
    except Exception as e:
        logger.warning("Error cloning %s: %s", full_name, e)
        return False


def main():
    if len(sys.argv) < 2:
        print("Usage: clone_targets.py <targets.json> [--resume]")
        sys.exit(1)

    targets_file = Path(sys.argv[1])
    resume = "--resume" in sys.argv

    repos = json.load(open(targets_file))
    checkpoint_file = targets_file.parent / "clone_checkpoint.json"

    # Load checkpoint
    done = set()
    if checkpoint_file.exists() and resume:
        ckpt = json.load(open(checkpoint_file))
        done = set(ckpt.get("cloned", []))
        logger.info("Resuming: %d repos already cloned", len(done))

    # Filter out already-done repos
    remaining = [r for r in repos if r["full_name"] not in done]
    logger.info(
        "Targets: %d total, %d done, %d remaining",
        len(repos), len(done), len(remaining),
    )

    cloned = list(done)
    failed = []
    start = time.time()

    for i, repo in enumerate(remaining):
        name = repo["full_name"]
        ok = clone_repo(name, STAGING_DIR)
        if ok:
            cloned.append(name)
        else:
            failed.append(name)

        # Checkpoint every 50 repos
        if (i + 1) % 50 == 0:
            with open(checkpoint_file, "w") as f:
                json.dump({"cloned": cloned, "failed": failed}, f)
            elapsed = time.time() - start
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            eta = (len(remaining) - i - 1) / rate if rate > 0 else 0
            logger.info(
                "Progress: %d/%d cloned, %d failed | %d/%d remaining | %.1f/s, ETA %.0f min",
                len(cloned), len(repos), len(failed),
                i + 1, len(remaining),
                rate, eta / 60,
            )

    # Final checkpoint
    with open(checkpoint_file, "w") as f:
        json.dump({"cloned": cloned, "failed": failed}, f)

    elapsed = time.time() - start
    logger.info(
        "Done: %d cloned, %d failed in %.1f min (%.1f/s)",
        len(cloned), len(failed), elapsed / 60,
        len(remaining) / elapsed if elapsed > 0 else 0,
    )


if __name__ == "__main__":
    main()
