"""Unit tests for ADI footprint cache management.

Tests cache operations: init, add, lookup, manifest persistence,
and ZIP extraction safety.
"""

import hashlib
import zipfile
from pathlib import Path

import pytest

from kicad_agent.project.adi_library.cache import FootprintCache
from kicad_agent.project.adi_library.types import FetchResult


class TestFootprintCacheInit:
    def test_init_creates_directories(self, tmp_path):
        """Cache initialization creates footprints/ and symbols/ subdirectories."""
        cache = FootprintCache(tmp_path / "adi_cache")
        assert (tmp_path / "adi_cache" / "footprints").is_dir()
        assert (tmp_path / "adi_cache" / "symbols").is_dir()

    def test_init_creates_manifest(self, tmp_path):
        """Cache initialization creates empty cache_manifest.json."""
        cache = FootprintCache(tmp_path / "adi_cache")
        assert (tmp_path / "adi_cache" / "cache_manifest.json").exists()


class TestCacheOperations:
    def test_add_and_lookup_footprint(self, tmp_path):
        """Add a .kicad_mod file to cache and retrieve it by part number."""
        cache = FootprintCache(tmp_path / "adi_cache")
        mod_file = tmp_path / "test.kicad_mod"
        mod_file.write_text("(module test (fp_text reference Ref) (pad 1 smd rect))")
        cache.add_entry("AD8606ARMZ", "manual", footprint_path=mod_file)
        assert cache.is_cached("AD8606ARMZ")
        paths = cache.get_cached_paths("AD8606ARMZ")
        assert paths["footprint"] is not None
        assert paths["footprint"].exists()

    def test_add_and_lookup_symbol(self, tmp_path):
        """Add a .kicad_sym file to cache and retrieve it."""
        cache = FootprintCache(tmp_path / "adi_cache")
        sym_file = tmp_path / "test.kicad_sym"
        sym_file.write_text("(kicad_symbol_lib (version 20220914) (generator kicad_agent))")
        cache.add_entry("AD8606ARMZ", "manual", symbol_path=sym_file)
        paths = cache.get_cached_paths("AD8606ARMZ")
        assert paths["symbol"] is not None
        assert paths["symbol"].exists()

    def test_uncached_part_returns_none(self, tmp_path):
        """Looking up an uncached part returns None paths."""
        cache = FootprintCache(tmp_path / "adi_cache")
        assert not cache.is_cached("UNKNOWN_PART")
        paths = cache.get_cached_paths("UNKNOWN_PART")
        assert paths["footprint"] is None
        assert paths["symbol"] is None

    def test_manifest_persists_across_sessions(self, tmp_path):
        """Cache entries survive across FootprintCache instances."""
        cache_dir = tmp_path / "adi_cache"
        cache1 = FootprintCache(cache_dir)
        mod_file = tmp_path / "test.kicad_mod"
        mod_file.write_text("(module test)")
        cache1.add_entry("AD8606ARMZ", "manual", footprint_path=mod_file)

        # New instance pointing to same directory
        cache2 = FootprintCache(cache_dir)
        assert cache2.is_cached("AD8606ARMZ")

    def test_overwrite_existing_entry(self, tmp_path):
        """Adding the same part number twice overwrites the entry."""
        cache = FootprintCache(tmp_path / "adi_cache")
        mod1 = tmp_path / "v1.kicad_mod"
        mod1.write_text("(module v1)")
        mod2 = tmp_path / "v2.kicad_mod"
        mod2.write_text("(module v2)")
        cache.add_entry("AD8606ARMZ", "manual", footprint_path=mod1)
        cache.add_entry("AD8606ARMZ", "manual", footprint_path=mod2)
        paths = cache.get_cached_paths("AD8606ARMZ")
        assert paths["footprint"].read_text() == "(module v2)"


class TestZipExtraction:
    def test_extract_zip_with_kicad_mod(self, tmp_path):
        """Extract a ZIP containing a .kicad_mod file."""
        cache = FootprintCache(tmp_path / "adi_cache")
        # Create a test ZIP
        zip_path = tmp_path / "test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("AD8606ARMZ.kicad_mod", "(module AD8606ARMZ (fp_text reference Ref))")
        result = cache.extract_zip_safe(zip_path, "AD8606ARMZ", "manual")
        assert result.part_number == "AD8606ARMZ"
        assert result.footprint_path is not None
        assert result.footprint_path.exists()
        assert result.source == "manual"
        assert not result.from_cache
        # ZIP should be deleted after extraction
        assert not zip_path.exists()

    def test_extract_zip_with_mod_and_sym(self, tmp_path):
        """Extract a ZIP containing both .kicad_mod and .kicad_sym."""
        cache = FootprintCache(tmp_path / "adi_cache")
        zip_path = tmp_path / "test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("AD8606ARMZ.kicad_mod", "(module AD8606ARMZ)")
            zf.writestr("AD8606ARMZ.kicad_sym", "(kicad_symbol_lib (version 20220914))")
        result = cache.extract_zip_safe(zip_path, "AD8606ARMZ", "samacsys")
        assert result.footprint_path is not None
        assert result.symbol_path is not None

    def test_extract_zip_rejects_path_traversal(self, tmp_path):
        """ZIP with ../ in entry path raises ValueError."""
        cache = FootprintCache(tmp_path / "adi_cache")
        zip_path = tmp_path / "evil.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("../../../etc/passwd.kicad_mod", "malicious")
        with pytest.raises(ValueError, match="path traversal"):
            cache.extract_zip_safe(zip_path, "EVIL", "manual")

    def test_extract_zip_skips_directories(self, tmp_path):
        """ZIP entries that are directories are skipped."""
        cache = FootprintCache(tmp_path / "adi_cache")
        zip_path = tmp_path / "test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("subdir/", "")  # directory entry
            zf.writestr("subdir/AD8606ARMZ.kicad_mod", "(module AD8606ARMZ)")
        result = cache.extract_zip_safe(zip_path, "AD8606ARMZ", "manual")
        assert result.footprint_path is not None

    def test_extract_zip_skips_non_kicad_files(self, tmp_path):
        """ZIP entries that are not KiCad files are skipped."""
        cache = FootprintCache(tmp_path / "adi_cache")
        zip_path = tmp_path / "test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("readme.txt", "ignore this")
            zf.writestr("AD8606ARMZ.kicad_mod", "(module AD8606ARMZ)")
        result = cache.extract_zip_safe(zip_path, "AD8606ARMZ", "manual")
        assert result.footprint_path is not None
        # readme.txt should not exist in cache
        assert not list((tmp_path / "adi_cache").rglob("readme.txt"))


class TestPartNumberValidation:
    def test_valid_part_numbers(self, tmp_path):
        """Valid part numbers with alphanumeric, dash, dot, underscore are accepted."""
        cache = FootprintCache(tmp_path / "adi_cache")
        mod_file = tmp_path / "test.kicad_mod"
        mod_file.write_text("(module test)")
        # These should not raise
        cache.add_entry("AD8606ARMZ", "manual", footprint_path=mod_file)

    def test_invalid_part_number_rejected(self, tmp_path):
        """Part numbers with special characters (spaces, semicolons, etc.) raise ValueError."""
        cache = FootprintCache(tmp_path / "adi_cache")
        mod_file = tmp_path / "test.kicad_mod"
        mod_file.write_text("(module test)")
        with pytest.raises(ValueError, match="[Ii]nvalid"):
            cache.add_entry("AD8606;RMZ", "manual", footprint_path=mod_file)
