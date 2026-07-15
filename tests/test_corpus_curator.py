"""Tests for real-world corpus curation: CuratedProject, CorpusCurator, ProjectIndex.

Covers:
- CuratedProject schema validation
- CorpusCurator pipeline with mock repos (download -> validate -> parse -> classify)
- License compatibility checking
- ProjectIndex search/filter
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Plan 53-01 Task 1: CuratedProject Schema and CorpusCurator
# ---------------------------------------------------------------------------


class TestCuratedProjectSchema:
    """Validate CuratedProject Pydantic schema."""

    def test_validates_with_all_required_fields(self):
        """CuratedProject validates with all required fields."""
        from volta.training.corpus_curator import CuratedProject

        project = CuratedProject(
            name="arduino-nano",
            source_url="https://github.com/arduino/ArduinoCore-avr",
            license="LGPL-3.0",
            category="microcontroller",
            complexity_score=7.5,
            erc_status="pass",
            component_count=42,
        )
        assert project.name == "arduino-nano"
        assert project.component_count == 42

    def test_rejects_missing_name(self):
        """CuratedProject rejects missing name."""
        from volta.training.corpus_curator import CuratedProject

        with pytest.raises(Exception):
            CuratedProject(
                source_url="https://github.com/example/test",
            )

    def test_rejects_missing_source_url(self):
        """CuratedProject rejects missing source_url."""
        from volta.training.corpus_curator import CuratedProject

        with pytest.raises(Exception):
            CuratedProject(name="test-project")

    def test_default_complexity_score_is_zero(self):
        """CuratedProject sets default complexity_score to 0.0."""
        from volta.training.corpus_curator import CuratedProject

        project = CuratedProject(
            name="test",
            source_url="https://github.com/example/test",
        )
        assert project.complexity_score == 0.0

    def test_metadata_allows_arbitrary_kv(self):
        """CuratedProject metadata allows arbitrary key-value pairs."""
        from volta.training.corpus_curator import CuratedProject

        project = CuratedProject(
            name="test",
            source_url="https://github.com/example/test",
            metadata={"stars": 1200, "topics": ["arduino", "mcu"]},
        )
        assert project.metadata["stars"] == 1200

    def test_rejects_empty_license(self):
        """CuratedProject rejects empty license string (too short for SPDX)."""
        from volta.training.corpus_curator import CuratedProject

        with pytest.raises(Exception):
            CuratedProject(
                name="test",
                source_url="https://github.com/example/test",
                license="",
            )

    def test_accepts_noassertion_license(self):
        """CuratedProject accepts NOASSERTION as license."""
        from volta.training.corpus_curator import CuratedProject

        project = CuratedProject(
            name="test",
            source_url="https://github.com/example/test",
            license="NOASSERTION",
        )
        assert project.license == "NOASSERTION"

    def test_erc_status_pattern(self):
        """CuratedProject accepts only valid erc_status values."""
        from volta.training.corpus_curator import CuratedProject

        for valid_status in ["pass", "fail", "unknown", "not_run"]:
            project = CuratedProject(
                name="test",
                source_url="https://github.com/example/test",
                erc_status=valid_status,
            )
            assert project.erc_status == valid_status

        with pytest.raises(Exception):
            CuratedProject(
                name="test",
                source_url="https://github.com/example/test",
                erc_status="invalid",
            )


class TestCorpusCurator:
    """Test CorpusCurator pipeline with mocked external dependencies."""

    def _make_curator(self) -> "CorpusCurator":
        from volta.training.corpus_curator import CorpusCurator
        return CorpusCurator(github_token="fake")

    def test_check_license_compatibility_mit(self):
        """MIT license is commercially compatible."""
        curator = self._make_curator()
        assert curator.check_license_compatibility("MIT") is True

    def test_check_license_compatibility_gpl(self):
        """GPL-3.0 is not in the commercially compatible set."""
        curator = self._make_curator()
        assert curator.check_license_compatibility("GPL-3.0-only") is False

    def test_check_license_compatibility_unknown(self):
        """Unknown license is not commercially compatible."""
        curator = self._make_curator()
        assert curator.check_license_compatibility("UNKNOWN") is False

    def test_classify_audio(self):
        """Classify audio project correctly."""
        curator = self._make_curator()
        category = curator.classify_project(
            "eurorack-vco",
            "Voltage controlled oscillator",
            ["synth", "audio", "eurorack"],
        )
        assert category == "audio"

    def test_classify_microcontroller(self):
        """Classify MCU project correctly."""
        curator = self._make_curator()
        category = curator.classify_project(
            "esp32-dev-board",
            "ESP32 development board",
            ["esp32", "wifi", "mcu"],
        )
        assert category == "microcontroller"

    def test_classify_unknown(self):
        """Unknown project returns 'unknown' category."""
        curator = self._make_curator()
        category = curator.classify_project(
            "random-project",
            "Something completely unrelated",
            ["random"],
        )
        assert category == "unknown"

    def test_compute_complexity_small(self):
        """Small project has low complexity."""
        curator = self._make_curator()
        score = curator.compute_complexity(component_count=10, net_count=5, sheet_count=1)
        assert 0.0 <= score <= 3.0

    def test_compute_complexity_large(self):
        """Large project has high complexity."""
        curator = self._make_curator()
        score = curator.compute_complexity(component_count=500, net_count=200, sheet_count=5)
        assert score >= 5.0

    def test_compute_complexity_bounds(self):
        """Complexity is always between 0.0 and 10.0."""
        curator = self._make_curator()
        for comps in [1, 10, 100, 1000, 10000]:
            score = curator.compute_complexity(component_count=comps, net_count=comps, sheet_count=1)
            assert 0.0 <= score <= 10.0

    def test_validate_project_passes(self):
        """Valid project passes quality gates."""
        curator = self._make_curator()
        valid, reason = curator.validate_project(component_count=42, net_count=20)
        assert valid is True

    def test_validate_project_rejects_few_components(self):
        """Project with fewer than 5 components is rejected."""
        curator = self._make_curator()
        valid, reason = curator.validate_project(component_count=2, net_count=5)
        assert valid is False
        assert "components" in reason.lower()

    def test_validate_project_rejects_parse_error(self):
        """Project that fails to parse is rejected."""
        curator = self._make_curator()
        valid, reason = curator.validate_project(component_count=50, net_count=20, parse_error=True)
        assert valid is False
        assert "parse" in reason.lower()

    def test_validate_project_rejects_few_nets(self):
        """Project with fewer than 3 nets is rejected."""
        curator = self._make_curator()
        valid, reason = curator.validate_project(component_count=10, net_count=1)
        assert valid is False
        assert "nets" in reason.lower()

    @patch("volta.training.corpus_curator.CorpusCurator.download_and_validate")
    def test_curate_batch_processes_multiple(self, mock_validate):
        """curate_batch processes multiple repos and returns curated list."""
        from volta.training.corpus_curator import CuratedProject, CorpusCurator

        curator = CorpusCurator(github_token="fake")

        mock_validate.side_effect = [
            CuratedProject(name="proj1", source_url="https://github.com/a/b", component_count=20),
            CuratedProject(name="proj2", source_url="https://github.com/c/d", component_count=30),
            None,  # Rejected
            CuratedProject(name="proj3", source_url="https://github.com/e/f", component_count=40),
        ]

        repos = [
            {"url": "https://github.com/a/b", "name": "proj1"},
            {"url": "https://github.com/c/d", "name": "proj2"},
            {"url": "https://github.com/g/h", "name": "rejected"},
            {"url": "https://github.com/e/f", "name": "proj3"},
        ]

        results = curator.curate_batch(repos)
        assert len(results) == 3

    @patch("volta.training.corpus_curator.CorpusCurator.download_and_validate")
    def test_curate_batch_deduplicates(self, mock_validate):
        """curate_batch filters out duplicate projects by source_url."""
        from volta.training.corpus_curator import CuratedProject, CorpusCurator

        curator = CorpusCurator(github_token="fake")

        mock_validate.return_value = CuratedProject(
            name="proj1", source_url="https://github.com/a/b", component_count=20,
        )

        repos = [
            {"url": "https://github.com/a/b", "name": "proj1"},
            {"url": "https://github.com/a/b", "name": "proj1-copy"},
        ]

        results = curator.curate_batch(repos)
        # Second call should be skipped (same URL)
        assert mock_validate.call_count == 1
        assert len(results) == 1

    def test_default_sources_count(self):
        """_default_sources returns 50+ projects."""
        curator = self._make_curator()
        sources = curator._default_sources()
        assert len(sources) >= 50


class TestLicenseCompatibility:
    """Test license compatibility identification."""

    def test_mit_is_commercially_compatible(self):
        """MIT license is identified as commercially compatible."""
        from volta.training.corpus_curator import CorpusCurator

        curator = CorpusCurator()
        assert curator.check_license_compatibility("MIT") is True

    def test_apache_is_commercially_compatible(self):
        """Apache-2.0 is commercially compatible."""
        from volta.training.corpus_curator import CorpusCurator

        curator = CorpusCurator()
        assert curator.check_license_compatibility("Apache-2.0") is True

    def test_cern_ohl_p_is_commercially_compatible(self):
        """CERN-OHL-P-2.0 is commercially compatible."""
        from volta.training.corpus_curator import CorpusCurator

        curator = CorpusCurator()
        assert curator.check_license_compatibility("CERN-OHL-P-2.0") is True

    def test_cc_by_nc_is_not_commercially_compatible(self):
        """CC-BY-NC-4.0 is not commercially compatible."""
        from volta.training.corpus_curator import CorpusCurator

        curator = CorpusCurator()
        assert curator.check_license_compatibility("CC-BY-NC-4.0") is False

    def test_noassertion_is_not_commercially_compatible(self):
        """NOASSERTION is not commercially compatible (unknown = assume no)."""
        from volta.training.corpus_curator import CorpusCurator

        curator = CorpusCurator()
        assert curator.check_license_compatibility("NOASSERTION") is False


class TestCorpusCuratorSerialization:
    """Test JSONL serialization."""

    def test_to_jsonl_round_trip(self):
        """to_jsonl and from_jsonl preserve project data."""
        from volta.training.corpus_curator import CorpusCurator, CuratedProject

        projects = [
            CuratedProject(name="test1", source_url="https://github.com/a/b", component_count=10),
            CuratedProject(name="test2", source_url="https://github.com/c/d", component_count=20),
        ]

        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
            path = Path(f.name)

        curator = CorpusCurator()
        count = curator.to_jsonl(projects, path)
        assert count == 2

        loaded = curator.from_jsonl(path)
        assert len(loaded) == 2
        assert loaded[0].name == "test1"
        assert loaded[1].component_count == 20

        path.unlink()


# ---------------------------------------------------------------------------
# Plan 53-01 Task 2: ProjectIndex
# ---------------------------------------------------------------------------


class TestProjectIndex:
    """Test searchable project index."""

    def _make_sample_projects(self):
        from volta.training.corpus_curator import CuratedProject

        return [
            CuratedProject(name="audio-amp", source_url="https://github.com/a/amp",
                          category="audio", complexity_score=6.5, component_count=50,
                          net_count=30, license="MIT", commercial_use_compatible=True),
            CuratedProject(name="power-supply", source_url="https://github.com/b/psu",
                          category="power", complexity_score=4.0, component_count=20,
                          net_count=15, license="GPL-3.0-only", commercial_use_compatible=False),
            CuratedProject(name="mcu-board", source_url="https://github.com/c/mcu",
                          category="microcontroller", complexity_score=8.0, component_count=100,
                          net_count=60, license="MIT", commercial_use_compatible=True),
            CuratedProject(name="simple-filter", source_url="https://github.com/d/filter",
                          category="audio", complexity_score=2.0, component_count=8,
                          net_count=5, license="Apache-2.0", commercial_use_compatible=True),
        ]

    def test_builds_from_project_list(self):
        """ProjectIndex builds from list of CuratedProject."""
        from volta.training.project_index import ProjectIndex

        index = ProjectIndex(self._make_sample_projects())
        assert len(index.projects) == 4

    def test_search_by_category(self):
        """Search by category returns matching projects."""
        from volta.training.project_index import ProjectIndex

        index = ProjectIndex(self._make_sample_projects())
        audio = index.search(category="audio")
        assert len(audio) == 2
        assert all(p.category == "audio" for p in audio)

    def test_search_by_complexity_range(self):
        """Search by complexity range filters correctly."""
        from volta.training.project_index import ProjectIndex

        index = ProjectIndex(self._make_sample_projects())
        mid = index.search(min_complexity=3.0, max_complexity=7.0)
        assert len(mid) == 2  # 6.5 and 4.0

    def test_search_commercial_only(self):
        """Search by license compatibility filters correctly."""
        from volta.training.project_index import ProjectIndex

        index = ProjectIndex(self._make_sample_projects())
        commercial = index.search(commercial_only=True)
        assert len(commercial) == 3
        assert all(p.commercial_use_compatible for p in commercial)

    def test_search_by_component_count(self):
        """Search by component count range filters correctly."""
        from volta.training.project_index import ProjectIndex

        index = ProjectIndex(self._make_sample_projects())
        large = index.search(min_components=20)
        assert len(large) == 3  # 50, 20, 100

    def test_combined_filters_anded(self):
        """Multiple filters AND together."""
        from volta.training.project_index import ProjectIndex

        index = ProjectIndex(self._make_sample_projects())
        results = index.search(category="audio", min_complexity=5.0)
        assert len(results) == 1  # Only audio-amp (6.5)
        assert results[0].name == "audio-amp"

    def test_search_empty_results(self):
        """Search returns empty list for non-matching filters."""
        from volta.training.project_index import ProjectIndex

        index = ProjectIndex(self._make_sample_projects())
        results = index.search(category="robotics")
        assert results == []

    def test_stats(self):
        """Stats returns summary statistics."""
        from volta.training.project_index import ProjectIndex

        index = ProjectIndex(self._make_sample_projects())
        stats = index.stats()
        assert stats.total_projects == 4
        assert "audio" in stats.categories
        assert stats.commercial_compatible_count == 3
        assert stats.avg_complexity > 0

    def test_json_round_trip(self):
        """ProjectIndex serializes to/from JSON."""
        from volta.training.project_index import ProjectIndex

        projects = self._make_sample_projects()
        index = ProjectIndex(projects)

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = Path(f.name)

        index.to_json(path)
        loaded = ProjectIndex.from_json(path)
        assert len(loaded.projects) == 4
        assert loaded.projects[0].name == "audio-amp"

        path.unlink()

    def test_categories_list(self):
        """categories() lists all categories."""
        from volta.training.project_index import ProjectIndex

        index = ProjectIndex(self._make_sample_projects())
        cats = index.categories()
        assert set(cats) == {"audio", "power", "microcontroller"}
