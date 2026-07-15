"""Tests for Phase 61: Security Hardening (C-1, H-1, H-2, H-3, H-4).

C-1: eval() replaced with AST walker in circuit_templates
H-1: Upload content validation in playground API
H-2: Public binding warning in CLI
H-3: Repo name validation in BulkFetcher
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# C-1: Safe expression parser (replaces eval)
# ---------------------------------------------------------------------------


class TestSafePredicateEvaluator:
    """Verify _eval_predicate uses AST walking instead of eval()."""

    def test_simple_comparison_true(self) -> None:
        """'R > 0' with R=100 evaluates to True."""
        from volta.training.circuit_templates import _eval_predicate

        assert _eval_predicate("R > 0", {"R": 100}) is True

    def test_simple_comparison_false(self) -> None:
        """'R > 0' with R=-1 evaluates to False."""
        from volta.training.circuit_templates import _eval_predicate

        assert _eval_predicate("R > 0", {"R": -1}) is False

    def test_compound_and(self) -> None:
        """'R > 0 and C > 0' with C=0 evaluates to False."""
        from volta.training.circuit_templates import _eval_predicate

        assert _eval_predicate("R > 0 and C > 0", {"R": 100, "C": 0}) is False

    def test_compound_and_both_true(self) -> None:
        """'R > 0 and C > 0' with both positive evaluates to True."""
        from volta.training.circuit_templates import _eval_predicate

        assert _eval_predicate("R > 0 and C > 0", {"R": 100, "C": 10}) is True

    def test_arithmetic_expression(self) -> None:
        """'R * 2 > 100' with R=60 evaluates to True."""
        from volta.training.circuit_templates import _eval_predicate

        assert _eval_predicate("R * 2 > 100", {"R": 60}) is True

    def test_rejects_import_attempt(self) -> None:
        """Malicious import expression raises ValueError."""
        from volta.training.circuit_templates import _eval_predicate

        with pytest.raises(ValueError):
            _eval_predicate("__import__('os')", {})

    def test_rejects_function_call(self) -> None:
        """Function calls in predicate raise ValueError."""
        from volta.training.circuit_templates import _eval_predicate

        with pytest.raises(ValueError):
            _eval_predicate("open('file')", {})

    def test_unknown_parameter_raises(self) -> None:
        """Reference to undefined parameter raises ValueError."""
        from volta.training.circuit_templates import _eval_predicate

        with pytest.raises(ValueError, match="Unknown parameter"):
            _eval_predicate("X > 0", {"R": 100})

    def test_gte_operator(self) -> None:
        """'>=' operator works correctly."""
        from volta.training.circuit_templates import _eval_predicate

        assert _eval_predicate("R >= 100", {"R": 100}) is True
        assert _eval_predicate("R >= 101", {"R": 100}) is False

    def test_equality_operator(self) -> None:
        """'==' operator works correctly."""
        from volta.training.circuit_templates import _eval_predicate

        assert _eval_predicate("N == 2", {"N": 2}) is True
        assert _eval_predicate("N == 3", {"N": 2}) is False

    def test_subtraction(self) -> None:
        """'R - 10 > 0' with R=50 evaluates to True."""
        from volta.training.circuit_templates import _eval_predicate

        assert _eval_predicate("R - 10 > 0", {"R": 50}) is True

    def test_no_eval_in_module(self) -> None:
        """circuit_templates.py must not use eval() as a function call in code."""
        import re
        import volta.training.circuit_templates as mod

        source = Path(mod.__file__).read_text(encoding="utf-8")
        # Skip docstrings and comments, check only code lines
        in_docstring = False
        for i, line in enumerate(source.split("\n"), 1):
            stripped = line.strip()
            # Track multi-line docstrings
            if '"""' in stripped or "'''" in stripped:
                count = stripped.count('"""') + stripped.count("'''")
                if count == 1:
                    in_docstring = not in_docstring
                continue  # Skip lines with docstring markers
            if in_docstring:
                continue
            if stripped.startswith("#"):
                continue
            # Match eval( not preceded by underscore or letter
            if re.search(r'(?<![_\w])eval\s*\(', stripped):
                pytest.fail(f"Line {i}: found eval() call: {stripped}")


# ---------------------------------------------------------------------------
# H-1: Upload content validation
# ---------------------------------------------------------------------------


class TestUploadContentValidation:
    """Verify _validate_content rejects non-KiCad files."""

    def test_valid_schematic_passes(self) -> None:
        """Valid .kicad_sch content is accepted."""
        from volta.playground.api import _validate_content

        # Should not raise
        _validate_content(b"(kicad_sch (version 20231120))", ".kicad_sch")

    def test_valid_pcb_passes(self) -> None:
        """Valid .kicad_pcb content is accepted."""
        from volta.playground.api import _validate_content

        _validate_content(b"(kicad_pcb (version 20231120))", ".kicad_pcb")

    def test_invalid_content_rejected(self) -> None:
        """Random bytes with .kicad_sch extension are rejected."""
        from fastapi import HTTPException
        from volta.playground.api import _validate_content

        with pytest.raises(HTTPException) as exc_info:
            _validate_content(b"NOT A KICAD FILE" * 10, ".kicad_sch")
        assert exc_info.value.status_code == 400

    def test_empty_file_accepted(self) -> None:
        """Small/empty files bypass content validation."""
        from volta.playground.api import _validate_content

        # Should not raise for tiny files
        _validate_content(b"", ".kicad_sch")

    def test_non_kicad_extension_not_validated(self) -> None:
        """Non-KiCad extensions are not content-validated (handled by filename check)."""
        from volta.playground.api import _validate_content

        # Should not raise — content validation only applies to KiCad extensions
        _validate_content(b"random bytes" * 10, ".txt")

    def test_legacy_module_format_accepted(self) -> None:
        """Legacy (module ...) footprint format is accepted."""
        from volta.playground.api import _validate_content

        _validate_content(b"(module footprint1 (layer F.Cu))", ".kicad_mod")


# ---------------------------------------------------------------------------
# H-2: Public binding warning
# ---------------------------------------------------------------------------


class TestPublicBindingWarning:
    """Verify CLI warns when binding to 0.0.0.0."""

    @staticmethod
    def _read_cli_py() -> str:
        """Read cli.py source (not the cli/ package)."""
        import importlib.util
        spec = importlib.util.find_spec("volta")
        pkg_dir = Path(spec.submodule_search_locations[0])
        return (pkg_dir / "cli.py").read_text(encoding="utf-8")

    def test_warning_on_0000(self) -> None:
        """--host 0.0.0.0 triggers warning logic in CLI source."""
        source = self._read_cli_py()
        assert '"0.0.0.0"' in source
        assert "WARNING" in source
        assert "file=sys.stderr" in source

    def test_no_warning_for_localhost(self) -> None:
        """Default host is localhost, not public."""
        source = self._read_cli_py()
        assert "127.0.0.1" in source


# ---------------------------------------------------------------------------
# H-3: Repo name validation
# ---------------------------------------------------------------------------


class TestRepoNameValidation:
    """Verify BulkFetcher._repo_dir validates repo names."""

    def test_valid_owner_repo(self, tmp_path: Path) -> None:
        """'owner/repo' is accepted."""
        from volta.crawler.bulk_fetcher import BulkFetcher

        fetcher = BulkFetcher(staging_dir=tmp_path)
        result = fetcher._repo_dir("owner/repo")
        assert result.name == "owner_repo"

    def test_path_traversal_rejected(self, tmp_path: Path) -> None:
        """'../etc/passwd' is rejected."""
        from volta.crawler.bulk_fetcher import BulkFetcher

        fetcher = BulkFetcher(staging_dir=tmp_path)
        with pytest.raises(ValueError, match="Invalid repo name"):
            fetcher._repo_dir("../etc/passwd")

    def test_triple_segment_rejected(self, tmp_path: Path) -> None:
        """'owner/repo/extra' is rejected."""
        from volta.crawler.bulk_fetcher import BulkFetcher

        fetcher = BulkFetcher(staging_dir=tmp_path)
        with pytest.raises(ValueError, match="Invalid repo name"):
            fetcher._repo_dir("owner/repo/extra")

    def test_dotdot_escape_rejected(self, tmp_path: Path) -> None:
        """'owner/../escape' is rejected."""
        from volta.crawler.bulk_fetcher import BulkFetcher

        fetcher = BulkFetcher(staging_dir=tmp_path)
        with pytest.raises(ValueError, match="Invalid repo name"):
            fetcher._repo_dir("owner/../escape")

    def test_unicode_separator_rejected(self, tmp_path: Path) -> None:
        """Unicode path separators are rejected."""
        from volta.crawler.bulk_fetcher import BulkFetcher

        fetcher = BulkFetcher(staging_dir=tmp_path)
        with pytest.raises(ValueError, match="Invalid repo name"):
            fetcher._repo_dir("owner\u202frepo")  # narrow no-break space

    def test_empty_name_rejected(self, tmp_path: Path) -> None:
        """Empty string is rejected."""
        from volta.crawler.bulk_fetcher import BulkFetcher

        fetcher = BulkFetcher(staging_dir=tmp_path)
        with pytest.raises(ValueError, match="Invalid repo name"):
            fetcher._repo_dir("")

    def test_hyphens_dots_allowed(self, tmp_path: Path) -> None:
        """Hyphens, dots, and underscores in names are accepted."""
        from volta.crawler.bulk_fetcher import BulkFetcher

        fetcher = BulkFetcher(staging_dir=tmp_path)
        result = fetcher._repo_dir("my-org/my_project.v2")
        assert result.name == "my-org_my_project.v2"
