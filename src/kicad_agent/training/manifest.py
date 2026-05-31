"""Content-addressed data manifest for training data versioning.

TRAIN-01: Records SHA256 hashes of all JSONL files in a directory,
verifies content integrity, and assigns reproducible train/val/test splits.

Usage:
    from kicad_agent.training.manifest import DataManifest

    manifest = DataManifest.from_directory(Path("training_data/"))
    manifest.save(Path("training_data/manifest.json"))

    # Later, verify data hasn't changed
    loaded = DataManifest.load(Path("training_data/manifest.json"))
    assert loaded.verify(Path("training_data/"))
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class DataManifest:
    """Content-addressed manifest for training data files.

    Attributes:
        files: Mapping of filename to SHA256 hex digest.
        split_seed: Random seed for reproducible split assignments.
        split_assignments: Mapping of sample_id to split label
            ("train", "val", "test"). Empty until assign_splits is called.
        generation_config: Optional config metadata.
        created_at: ISO 8601 timestamp of manifest creation.
    """

    files: dict[str, str] = field(default_factory=dict)
    split_seed: int = 42
    split_assignments: dict[int, str] = field(default_factory=dict)
    generation_config: dict = field(default_factory=dict)
    created_at: str = ""

    @classmethod
    def from_directory(
        cls,
        data_dir: Path,
        config: dict | None = None,
        split_seed: int = 42,
    ) -> DataManifest:
        """Create a manifest by hashing all JSONL files in a directory.

        Args:
            data_dir: Directory containing JSONL files.
            config: Optional generation config metadata.
            split_seed: Seed for reproducible split assignments.

        Returns:
            DataManifest with file hashes populated.
        """
        data_dir = Path(data_dir)
        files: dict[str, str] = {}
        for path in sorted(data_dir.glob("*.jsonl")):
            content = path.read_bytes()
            sha = hashlib.sha256(content).hexdigest()
            files[path.name] = sha

        return cls(
            files=files,
            split_seed=split_seed,
            generation_config=config or {},
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def save(self, path: Path) -> None:
        """Save manifest as JSON.

        Args:
            path: Output file path.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "files": self.files,
            "split_seed": self.split_seed,
            "split_assignments": self.split_assignments,
            "generation_config": self.generation_config,
            "created_at": self.created_at,
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    @classmethod
    def load(cls, path: Path) -> DataManifest:
        """Load manifest from JSON file.

        Args:
            path: Path to manifest JSON.

        Returns:
            DataManifest with all fields restored.
        """
        path = Path(path)
        with open(path) as f:
            data = json.load(f)

        # Convert string keys in split_assignments back to int
        assignments = {int(k): v for k, v in data.get("split_assignments", {}).items()}

        return cls(
            files=data["files"],
            split_seed=data["split_seed"],
            split_assignments=assignments,
            generation_config=data.get("generation_config", {}),
            created_at=data.get("created_at", ""),
        )

    def verify(self, data_dir: Path) -> bool:
        """Verify files against stored hashes.

        Rehashes all files in data_dir and compares against stored hashes.
        Returns False if any file is missing or has a different hash.

        Args:
            data_dir: Directory to verify.

        Returns:
            True if all files match, False otherwise.
        """
        data_dir = Path(data_dir)

        # Every stored file must exist and match its hash
        for filename, expected_hash in self.files.items():
            filepath = data_dir / filename
            if not filepath.exists():
                return False
            actual_hash = hashlib.sha256(filepath.read_bytes()).hexdigest()
            if actual_hash != expected_hash:
                return False

        return True

    def assign_splits(
        self,
        n_samples: int,
        train: float = 0.8,
        val: float = 0.1,
        test: float = 0.1,
    ) -> DataManifest:
        """Assign train/val/test splits deterministically.

        Uses the manifest's split_seed to produce reproducible assignments.
        Returns a new DataManifest with split_assignments populated.

        Args:
            n_samples: Number of samples to assign.
            train: Fraction for training set.
            val: Fraction for validation set.
            test: Fraction for test set.

        Returns:
            New DataManifest with split_assignments populated.
        """
        indices = list(range(n_samples))
        rng = random.Random(self.split_seed)
        rng.shuffle(indices)

        train_end = int(n_samples * train)
        val_end = train_end + int(n_samples * val)

        assignments: dict[int, str] = {}
        for i, idx in enumerate(indices):
            if i < train_end:
                assignments[idx] = "train"
            elif i < val_end:
                assignments[idx] = "val"
            else:
                assignments[idx] = "test"

        return replace(self, split_assignments=assignments)
