"""Training output cleanup utility.

TRAIN-04: Removes stale training output directories, preserving the latest N
runs per type prefix. Supports dry-run mode and report consolidation.

Usage:
    from kicad_agent.training.cleanup import TrainingCleanup, CleanupConfig

    config = CleanupConfig(output_dir=Path("training_output/"), keep=3)
    cleanup = TrainingCleanup(config)
    result = cleanup.run()
    print(f"Deleted {len(result['deleted'])} old runs")
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class CleanupConfig:
    """Configuration for training output cleanup.

    Attributes:
        output_dir: Root directory containing training run outputs.
        keep: Number of runs to preserve per type prefix.
        dry_run: If True, report deletions without executing them.
        consolidate_reports: If True, merge eval_report.json into
            a single consolidated_report.json in output_dir root.
    """

    output_dir: Path = Path("training_output/")
    keep: int = 3
    dry_run: bool = False
    consolidate_reports: bool = True


class TrainingCleanup:
    """Cleanup stale training output directories.

    Scans the output directory for training run directories, groups them by
    type prefix (e.g., "grpo_", "sft_", "improved_"), and removes all but
    the latest N runs per group.

    Args:
        config: Cleanup configuration.
    """

    def __init__(self, config: CleanupConfig) -> None:
        self.config = config

    def run(self) -> dict:
        """Execute cleanup based on configuration.

        Returns:
            Dict with keys:
              - deleted: list of deleted directory paths (or would_delete in dry_run)
              - kept: list of kept directory paths
              - would_delete: list of paths that would be deleted (dry_run only)
              - consolidated: path to consolidated report (if consolidation ran)
        """
        output_dir = Path(self.config.output_dir)
        if not output_dir.exists():
            return {"deleted": [], "kept": [], "would_delete": []}

        runs = self._scan_runs(output_dir)
        if not runs:
            return {"deleted": [], "kept": [], "would_delete": []}

        groups = self._group_by_type(runs)

        if self.config.dry_run:
            to_delete = self._select_for_deletion(groups, self.config.keep)
            kept = [r["path"] for r in runs if r["path"] not in set(to_delete)]
            return {
                "would_delete": to_delete,
                "kept": kept,
                "deleted": [],
            }

        to_delete = self._select_for_deletion(groups, self.config.keep)
        kept = [r["path"] for r in runs if r["path"] not in set(to_delete)]

        # Delete old runs
        for path in to_delete:
            if path.exists():
                logger.info("Removing old run: %s", path)
                shutil.rmtree(path)

        result: dict = {
            "deleted": to_delete,
            "kept": kept,
            "would_delete": [],
        }

        # Consolidate reports if enabled
        if self.config.consolidate_reports:
            # Scan remaining runs for eval reports
            remaining_runs = self._scan_runs(output_dir)
            consolidated_path = self._consolidate_reports(remaining_runs, output_dir)
            if consolidated_path:
                result["consolidated"] = consolidated_path

        return result

    def _scan_runs(self, output_dir: Path) -> list[dict]:
        """Scan output directory for training run directories.

        A directory is considered a training run if it contains an
        eval_report.json or adapter files.

        Args:
            output_dir: Root output directory.

        Returns:
            List of dicts with keys: name, path, mtime, type_prefix, has_eval_report.
        """
        runs: list[dict] = []
        for entry in sorted(output_dir.iterdir()):
            if not entry.is_dir():
                continue
            has_eval = (entry / "eval_report.json").exists()
            has_adapter = any(entry.glob("adapters.*"))
            if has_eval or has_adapter:
                stat = entry.stat()
                runs.append({
                    "name": entry.name,
                    "path": entry,
                    "mtime": stat.st_mtime,
                    "type_prefix": self._extract_prefix(entry.name),
                    "has_eval_report": has_eval,
                })
        return runs

    def _extract_prefix(self, name: str) -> str:
        """Extract type prefix from a run directory name.

        Prefixes are determined by common training run naming conventions.
        E.g., "grpo_v1" -> "grpo", "sft_final" -> "sft".

        Args:
            name: Directory name.

        Returns:
            Type prefix string.
        """
        known_prefixes = [
            "grpo", "sft", "improved", "real_pcb", "hard_neg",
            "board", "reward", "no_bonus", "easy_only", "maze",
        ]
        lower = name.lower()
        for prefix in known_prefixes:
            if lower.startswith(prefix):
                return prefix
        # Default: everything before the first separator
        parts = name.split("_")
        return parts[0] if parts else name

    def _group_by_type(self, runs: list[dict]) -> dict[str, list[dict]]:
        """Group runs by their type prefix.

        Args:
            runs: List of run dicts from _scan_runs.

        Returns:
            Dict mapping type prefix to list of run dicts.
        """
        groups: dict[str, list[dict]] = {}
        for run in runs:
            prefix = run["type_prefix"]
            groups.setdefault(prefix, []).append(run)
        # Sort each group by mtime descending (newest first)
        for prefix in groups:
            groups[prefix].sort(key=lambda r: r["mtime"], reverse=True)
        return groups

    def _select_for_deletion(
        self, groups: dict[str, list[dict]], keep: int
    ) -> list[Path]:
        """Select directories for deletion based on retention policy.

        Args:
            groups: Runs grouped by type prefix.
            keep: Number of runs to keep per group.

        Returns:
            List of paths to delete.
        """
        to_delete: list[Path] = []
        for prefix, runs in groups.items():
            # runs is sorted newest-first; delete everything after keep
            for run in runs[keep:]:
                to_delete.append(run["path"])
        return to_delete

    def _consolidate_reports(
        self, runs: list[dict], output_dir: Path
    ) -> Path | None:
        """Merge all eval_report.json files into a single consolidated report.

        Args:
            runs: List of run dicts with has_eval_report flag.
            output_dir: Root output directory for consolidated report.

        Returns:
            Path to consolidated report, or None if no reports found.
        """
        all_reports: list[dict] = []
        for run in runs:
            report_path = run["path"] / "eval_report.json"
            if report_path.exists():
                try:
                    data = json.loads(report_path.read_text())
                    data["_run_name"] = run["name"]
                    all_reports.append(data)
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning("Could not read %s: %s", report_path, e)

        if not all_reports:
            return None

        consolidated_path = output_dir / "consolidated_report.json"
        consolidated = {
            "total_runs": len(all_reports),
            "runs": all_reports,
        }
        with open(consolidated_path, "w") as f:
            json.dump(consolidated, f, indent=2)

        logger.info(
            "Consolidated %d reports into %s", len(all_reports), consolidated_path
        )
        return consolidated_path
