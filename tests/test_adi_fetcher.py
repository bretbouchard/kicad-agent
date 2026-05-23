"""Integration tests for AdiFetcher.

Tests the complete fetch pipeline: search -> download -> validate -> cache -> register.
Uses mocked HTTP client and tmp_path for filesystem isolation.
"""

import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kicad_agent.project.adi_library.fetcher import AdiFetcher
from kicad_agent.project.adi_library.types import FetchResult


def _create_kicad_mod_zip(
    zip_path: Path, part_number: str, include_sym: bool = False
) -> None:
    """Create a test ZIP with a .kicad_mod file (and optionally .kicad_sym)."""
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(
            f"{part_number}.kicad_mod",
            f'(module "{part_number}" (layer "F.Cu") '
            f'(fp_text reference "REF**" (at 0 0) (layer "F.SilkS")))',
        )
        if include_sym:
            zf.writestr(
                f"{part_number}.kicad_sym",
                f'(kicad_symbol_lib (version 20220914) (generator kicad_agent) '
                f'(symbol "{part_number}"))',
            )


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """Create a temporary KiCad project directory."""
    return tmp_path / "test_project"


class TestFetchPartCacheHit:
    def test_cached_part_returns_immediately(self, project_dir: Path) -> None:
        """Cached part returns FetchResult with from_cache=True without HTTP."""
        project_dir.mkdir(parents=True, exist_ok=True)
        fetcher = AdiFetcher(project_dir)

        # Pre-populate cache
        mod_file = project_dir / "test.kicad_mod"
        mod_file.write_text('(module "AD8606ARMZ" (layer "F.Cu"))')
        fetcher._cache.add_entry("AD8606ARMZ", "manual", footprint_path=mod_file)

        result = fetcher.fetch_part("AD8606ARMZ")
        assert result.from_cache is True
        assert result.footprint_path is not None
        assert result.part_number == "AD8606ARMZ"
        fetcher.close()


class TestImportZip:
    def test_import_zip_with_footprint(self, project_dir: Path) -> None:
        """User-provided ZIP with .kicad_mod imports and caches correctly."""
        project_dir.mkdir(parents=True, exist_ok=True)
        fetcher = AdiFetcher(project_dir)

        zip_path = project_dir / "AD8606ARMZ.zip"
        _create_kicad_mod_zip(zip_path, "AD8606ARMZ")

        result = fetcher.import_zip(zip_path, "AD8606ARMZ")
        assert result.footprint_path is not None
        assert result.footprint_path.exists()
        assert result.source == "manual"
        assert not result.from_cache
        fetcher.close()

    def test_import_zip_with_footprint_and_symbol(self, project_dir: Path) -> None:
        """ZIP with both .kicad_mod and .kicad_sym imports both."""
        project_dir.mkdir(parents=True, exist_ok=True)
        fetcher = AdiFetcher(project_dir)

        zip_path = project_dir / "AD8606ARMZ.zip"
        _create_kicad_mod_zip(zip_path, "AD8606ARMZ", include_sym=True)

        result = fetcher.import_zip(zip_path, "AD8606ARMZ")
        assert result.footprint_path is not None
        assert result.symbol_path is not None
        fetcher.close()

    def test_import_zip_invalid_part_number(self, project_dir: Path) -> None:
        """Invalid part number raises ValueError."""
        project_dir.mkdir(parents=True, exist_ok=True)
        fetcher = AdiFetcher(project_dir)
        zip_path = project_dir / "test.zip"
        _create_kicad_mod_zip(zip_path, "test")

        with pytest.raises(ValueError, match="[Ii]nvalid"):
            fetcher.import_zip(zip_path, "BAD;PART")
        fetcher.close()

    def test_import_zip_nonexistent_file(self, project_dir: Path) -> None:
        """Non-existent ZIP file raises FileNotFoundError."""
        project_dir.mkdir(parents=True, exist_ok=True)
        fetcher = AdiFetcher(project_dir)

        with pytest.raises(FileNotFoundError):
            fetcher.import_zip(project_dir / "nonexistent.zip", "AD8606ARMZ")
        fetcher.close()


class TestImportFiles:
    def test_import_individual_footprint(self, project_dir: Path) -> None:
        """Direct .kicad_mod file import works without ZIP."""
        project_dir.mkdir(parents=True, exist_ok=True)
        fetcher = AdiFetcher(project_dir)

        mod_file = project_dir / "test.kicad_mod"
        mod_file.write_text(
            '(module "AD8606ARMZ" (layer "F.Cu") '
            '(fp_text reference "REF**" (at 0 0) (layer "F.SilkS")))'
        )

        result = fetcher.import_files("AD8606ARMZ", footprint_path=mod_file)
        assert result.footprint_path is not None
        fetcher.close()


class TestLibraryRegistration:
    def test_footprint_library_registered_in_fp_lib_table(
        self, project_dir: Path
    ) -> None:
        """After import, fp-lib-table contains ADI_Local entry."""
        project_dir.mkdir(parents=True, exist_ok=True)
        fetcher = AdiFetcher(project_dir)

        mod_file = project_dir / "test.kicad_mod"
        mod_file.write_text(
            '(module "AD8606ARMZ" (layer "F.Cu") '
            '(fp_text reference "REF**" (at 0 0) (layer "F.SilkS")))'
        )

        fetcher.import_files("AD8606ARMZ", footprint_path=mod_file)

        fp_table_path = project_dir / "fp-lib-table"
        assert fp_table_path.exists()
        content = fp_table_path.read_text()
        assert "ADI_Local" in content
        assert ".adi_cache/footprints" in content
        fetcher.close()

    def test_symbol_library_registered_in_sym_lib_table(
        self, project_dir: Path
    ) -> None:
        """After import, sym-lib-table contains ADI_Local entry."""
        project_dir.mkdir(parents=True, exist_ok=True)
        fetcher = AdiFetcher(project_dir)

        sym_file = project_dir / "test.kicad_sym"
        sym_file.write_text(
            "(kicad_symbol_lib (version 20220914) (generator kicad_agent))"
        )

        fetcher.import_files("AD8606ARMZ", symbol_path=sym_file)

        sym_table_path = project_dir / "sym-lib-table"
        assert sym_table_path.exists()
        content = sym_table_path.read_text()
        assert "ADI_Local" in content
        assert ".adi_cache/symbols" in content
        fetcher.close()

    def test_no_duplicate_registration(self, project_dir: Path) -> None:
        """Importing twice does not create duplicate lib table entries."""
        project_dir.mkdir(parents=True, exist_ok=True)
        fetcher = AdiFetcher(project_dir)

        mod_file = project_dir / "test.kicad_mod"
        mod_file.write_text(
            '(module "AD8606ARMZ" (layer "F.Cu") '
            '(fp_text reference "REF**" (at 0 0) (layer "F.SilkS")))'
        )

        fetcher.import_files("AD8606ARMZ", footprint_path=mod_file)
        fetcher.import_files("AD8606ARMZ", footprint_path=mod_file)

        content = (project_dir / "fp-lib-table").read_text()
        # Count occurrences of ADI_Local -- should appear exactly once
        assert content.count("ADI_Local") == 1
        fetcher.close()


class TestFetchPartAutomated:
    def test_fetch_part_samacsys_success(self, project_dir: Path) -> None:
        """Full fetch pipeline: search -> download -> extract -> cache -> register."""
        project_dir.mkdir(parents=True, exist_ok=True)
        fetcher = AdiFetcher(project_dir)

        # Mock the client methods
        search_result = MagicMock()
        search_result.error = None
        search_result.has_kicad = True
        search_result.download_url = "https://example.com/download/AD8606ARMZ.zip"

        zip_path = project_dir / "_temp" / "AD8606ARMZ.zip"
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        _create_kicad_mod_zip(zip_path, "AD8606ARMZ", include_sym=True)

        with patch.object(fetcher._client, "search_part", return_value=search_result):
            with patch.object(
                fetcher._client, "download_library", return_value=zip_path
            ):
                result = fetcher.fetch_part("AD8606ARMZ")

        assert result.footprint_path is not None or result.symbol_path is not None
        assert result.source == "samacsys"
        fetcher.close()

    def test_fetch_part_samacsys_failure_returns_empty(
        self, project_dir: Path
    ) -> None:
        """When SamacSys search fails, returns FetchResult with None paths."""
        project_dir.mkdir(parents=True, exist_ok=True)
        fetcher = AdiFetcher(project_dir)

        search_result = MagicMock()
        search_result.error = "HTTP 500"
        search_result.has_kicad = False
        search_result.download_url = None

        with patch.object(fetcher._client, "search_part", return_value=search_result):
            result = fetcher.fetch_part("UNKNOWN_PART")

        assert result.footprint_path is None
        assert result.symbol_path is None
        fetcher.close()


class TestContextManager:
    def test_context_manager(self, project_dir: Path) -> None:
        """AdiFetcher works as context manager."""
        project_dir.mkdir(parents=True, exist_ok=True)
        with AdiFetcher(project_dir) as fetcher:
            assert fetcher is not None
