"""Phase 159 TRAIN-01: SKIDL corpus converter.

Batch-converts crawled KiCad repos to SKIDL Python code (L2 form).
Reads discovered_repos.json for the repo list, converts each .kicad_sch
to SKIDL via Phase 156 build_circuit + emit_build_py.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def convert_repo_to_skidl(
    repo_path: Path | str,
    output_dir: Path | str,
) -> tuple[int, int]:
    """Convert all .kicad_sch files in a repo to SKIDL.

    Args:
        repo_path: Path to the repo root.
        output_dir: Where to write build_*.py files.

    Returns:
        (success_count, failure_count)
    """
    from kicad_agent.circuit_ir import build_circuit, emit_build_py

    repo_path = Path(repo_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    sch_files = list(repo_path.rglob("*.kicad_sch"))
    success = 0
    failure = 0

    for sch_path in sch_files:
        try:
            circuit, circuit_ir = build_circuit(sch_path)
            if len(circuit_ir.parts) < 2:
                continue  # Skip trivial circuits
            out_name = f"build_{sch_path.stem}.py"
            emit_build_py(circuit_ir, mode="L2", out_path=output_dir / out_name)
            success += 1
        except Exception as e:
            logger.debug("Failed %s: %s", sch_path.name, e)
            failure += 1

    return success, failure


def load_discovered_repos(json_path: Path | str, limit: int = 0) -> list[str]:
    """Load repo paths from discovered_repos.json.

    Args:
        json_path: Path to discovered_repos.json.
        limit: Max repos to return (0 = all).

    Returns:
        List of repo clone URLs or local paths.
    """
    json_path = Path(json_path)
    if not json_path.exists():
        logger.warning("discovered_repos.json not found: %s", json_path)
        return []

    with open(json_path, "r", encoding="utf-8") as f:
        # The file may be JSONL or one big JSON array.
        first_char = f.read(1)
        f.seek(0)

        if first_char == "[":
            data = json.load(f)
        else:
            # JSONL format — one JSON object per line.
            data = []
            for line in f:
                line = line.strip()
                if line:
                    try:
                        data.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

    repos = []
    for entry in data:
        if isinstance(entry, dict):
            url = entry.get("clone_url") or entry.get("url") or entry.get("repo")
            if url:
                repos.append(url)
        elif isinstance(entry, str):
            repos.append(entry)

    if limit > 0:
        repos = repos[:limit]

    return repos


def batch_convert_corpus(
    discovered_repos_path: Path | str,
    output_dir: Path | str,
    repo_cache_dir: Path | str | None = None,
    limit: int = 100,
) -> dict:
    """Batch convert repos from discovered_repos.json to SKIDL.

    Args:
        discovered_repos_path: Path to discovered_repos.json.
        output_dir: Where to write SKIDL build_*.py files.
        repo_cache_dir: Directory where repos are cloned (default: output_dir/repos).
        limit: Max repos to process.

    Returns:
        Dict with success/failure counts and stats.
    """
    repos = load_discovered_repos(discovered_repos_path, limit=limit)
    output_dir = Path(output_dir)
    repo_cache_dir = Path(repo_cache_dir or output_dir / "repos")
    repo_cache_dir.mkdir(parents=True, exist_ok=True)

    total_success = 0
    total_failure = 0
    total_schematics = 0

    for i, repo_url in enumerate(repos):
        # Try to find local repo path (repos may be pre-cloned).
        repo_name = repo_url.split("/")[-1].replace(".git", "")
        local_path = repo_cache_dir / repo_name

        if not local_path.exists():
            logger.debug("Repo not cached locally: %s — skipping", repo_name)
            continue

        success, failure = convert_repo_to_skidl(local_path, output_dir)
        total_success += success
        total_failure += failure
        total_schematics += success + failure

        if (i + 1) % 100 == 0:
            logger.info(
                "Corpus progress: %d/%d repos, %d converted, %d failed",
                i + 1, len(repos), total_success, total_failure,
            )

    return {
        "repos_processed": len(repos),
        "schematics_converted": total_success,
        "schematics_failed": total_failure,
        "output_dir": str(output_dir),
    }
