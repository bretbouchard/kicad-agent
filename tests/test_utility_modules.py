"""Tests for utility modules: atomic_write, cli_resolver, cache."""

from pathlib import Path
import tempfile

import pytest


class TestAtomicWrite:
    """Tests for atomic write utility."""

    def test_import(self):
        """atomic_write is importable."""
        from kicad_agent.io.atomic_write import atomic_write
        assert callable(atomic_write)

    def test_atomic_write_creates_file(self):
        """atomic_write creates the target file."""
        from kicad_agent.io.atomic_write import atomic_write
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.txt"
            atomic_write(str(path), "hello world\n")
            assert path.read_text() == "hello world\n"


class TestCliResolver:
    """Tests for KiCad CLI resolver."""

    def test_import(self):
        """cli_resolver is importable."""
        from kicad_agent.cli_resolver import find_kicad_cli
        assert callable(find_kicad_cli)

    def test_find_returns_result(self):
        """find_kicad_cli returns a result (found or not)."""
        from kicad_agent.cli_resolver import find_kicad_cli
        result = find_kicad_cli()
        assert result is not None
        # Either found or not, should have path or found=False
        assert hasattr(result, "path") or hasattr(result, "found")


class TestCacheModule:
    """Tests for cache module."""

    def test_import(self):
        """Cache module not yet implemented."""
        import importlib
        spec = importlib.util.find_spec("kicad_agent.cache")
        if spec is not None:
            from kicad_agent import cache
            assert cache is not None
        else:
            pytest.skip("kicad_agent.cache module not yet implemented")
