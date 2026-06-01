"""Searchable index over curated KiCad projects.

Provides filter/search capabilities for the curated project corpus,
supporting category, complexity, license, and component-type queries.

Usage:
    from kicad_agent.training.project_index import ProjectIndex
    from kicad_agent.training.corpus_curator import CuratedProject

    index = ProjectIndex(projects)
    audio = index.search(category="audio")
    complex_commercial = index.search(
        min_complexity=5.0,
        commercial_only=True,
    )
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from kicad_agent.training.corpus_curator import CuratedProject


@dataclass
class IndexStats:
    """Summary statistics for the project index.

    Attributes:
        total_projects: Total number of indexed projects.
        categories: Dict mapping category to count.
        license_distribution: Dict mapping license to count.
        commercial_compatible_count: Count of commercially compatible projects.
        avg_complexity: Average complexity score.
        avg_component_count: Average component count.
    """

    total_projects: int = 0
    categories: dict[str, int] = field(default_factory=dict)
    license_distribution: dict[str, int] = field(default_factory=dict)
    commercial_compatible_count: int = 0
    avg_complexity: float = 0.0
    avg_component_count: float = 0.0


class ProjectIndex:
    """Searchable index over curated KiCad projects.

    Supports filtering by category, complexity range, license compatibility,
    and component types. Multiple filters are ANDed together.
    """

    def __init__(self, projects: list[CuratedProject]) -> None:
        self._projects = list(projects)
        self._by_category: dict[str, list[CuratedProject]] = {}
        self._build_index()

    def _build_index(self) -> None:
        """Build internal category index."""
        for p in self._projects:
            if p.category not in self._by_category:
                self._by_category[p.category] = []
            self._by_category[p.category].append(p)

    @property
    def projects(self) -> list[CuratedProject]:
        """All indexed projects."""
        return list(self._projects)

    def search(
        self,
        category: str | None = None,
        min_complexity: float | None = None,
        max_complexity: float | None = None,
        commercial_only: bool = False,
        min_components: int | None = None,
        max_components: int | None = None,
        license_spdx: str | None = None,
    ) -> list[CuratedProject]:
        """Search projects with optional filters (ANDed).

        Args:
            category: Filter by category (exact match).
            min_complexity: Minimum complexity score.
            max_complexity: Maximum complexity score.
            commercial_only: Only commercially compatible licenses.
            min_components: Minimum component count.
            max_components: Maximum component count.
            license_spdx: Filter by specific SPDX license.

        Returns:
            List of matching CuratedProject instances.
        """
        results = self._projects

        if category is not None:
            results = [p for p in results if p.category == category]

        if min_complexity is not None:
            results = [p for p in results if p.complexity_score >= min_complexity]

        if max_complexity is not None:
            results = [p for p in results if p.complexity_score <= max_complexity]

        if commercial_only:
            results = [p for p in results if p.commercial_use_compatible]

        if min_components is not None:
            results = [p for p in results if p.component_count >= min_components]

        if max_components is not None:
            results = [p for p in results if p.component_count <= max_components]

        if license_spdx is not None:
            results = [p for p in results if p.license == license_spdx]

        return results

    def stats(self) -> IndexStats:
        """Compute summary statistics for the index."""
        if not self._projects:
            return IndexStats()

        categories: dict[str, int] = {}
        licenses: dict[str, int] = {}
        total_complexity = 0.0
        total_components = 0
        commercial = 0

        for p in self._projects:
            categories[p.category] = categories.get(p.category, 0) + 1
            licenses[p.license] = licenses.get(p.license, 0) + 1
            total_complexity += p.complexity_score
            total_components += p.component_count
            if p.commercial_use_compatible:
                commercial += 1

        n = len(self._projects)
        return IndexStats(
            total_projects=n,
            categories=categories,
            license_distribution=licenses,
            commercial_compatible_count=commercial,
            avg_complexity=round(total_complexity / n, 2) if n > 0 else 0.0,
            avg_component_count=round(total_components / n, 1) if n > 0 else 0.0,
        )

    def categories(self) -> list[str]:
        """List all categories in the index."""
        return list(self._by_category.keys())

    def to_json(self, path: Path) -> None:
        """Serialize index to JSON file."""
        data = [p.model_dump() for p in self._projects]
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)

    @classmethod
    def from_json(cls, path: Path) -> ProjectIndex:
        """Load index from JSON file."""
        with open(path) as f:
            data = json.load(f)
        projects = [CuratedProject.model_validate(d) for d in data]
        return cls(projects)
