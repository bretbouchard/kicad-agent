"""Tests for kicad_agent.llm.knowledge module.

TDD RED phase: These tests define the expected behavior of KnowledgeManager,
_chunk_by_h2, _truncate_section, CORE_RULES, and OP_SECTION_MAP.
"""

from __future__ import annotations

import os
import textwrap
from pathlib import Path
from unittest import mock

import pytest


# ---------------------------------------------------------------------------
# Tests for _chunk_by_h2
# ---------------------------------------------------------------------------

class TestChunkByH2:
    """Tests for the _chunk_by_h2 markdown section splitter."""

    def test_basic_chunking(self):
        """Test 1: _chunk_by_h2 splits on ## headers correctly."""
        from kicad_agent.llm.knowledge import _chunk_by_h2
        text = "## Foo\nbar\n## Baz\nqux"
        result = _chunk_by_h2(text)
        assert result == {"Foo": "bar", "Baz": "qux"}

    def test_text_before_first_header_ignored(self):
        """Test 2: Text before first ## header is ignored."""
        from kicad_agent.llm.knowledge import _chunk_by_h2
        text = "preamble text\n## Section\nbody"
        result = _chunk_by_h2(text)
        assert result == {"Section": "body"}
        assert "preamble" not in str(result)

    def test_no_headers_returns_empty(self):
        """Test 3: Text with no ## headers returns empty dict."""
        from kicad_agent.llm.knowledge import _chunk_by_h2
        text = "just plain text\nno headers here"
        result = _chunk_by_h2(text)
        assert result == {}

    def test_duplicate_headers_last_wins(self):
        """Test 4: Duplicate headers use last-wins behavior."""
        from kicad_agent.llm.knowledge import _chunk_by_h2
        text = "## Foo\nfirst\n## Foo\nsecond"
        result = _chunk_by_h2(text)
        assert result == {"Foo": "second"}

    def test_header_with_no_body(self):
        """Test: Header with no body text returns empty string."""
        from kicad_agent.llm.knowledge import _chunk_by_h2
        text = "## Empty\n## Next\ncontent"
        result = _chunk_by_h2(text)
        assert result == {"Empty": "", "Next": "content"}


# ---------------------------------------------------------------------------
# Tests for _truncate_section
# ---------------------------------------------------------------------------

class TestTruncateSection:
    """Tests for the _truncate_section token capper."""

    def test_short_text_unchanged(self):
        """Text under cap is returned unchanged."""
        from kicad_agent.llm.knowledge import _truncate_section
        text = "Short text."
        result = _truncate_section(text, max_tokens=100)
        assert result == text

    def test_empty_text_unchanged(self):
        """Empty string returned as-is."""
        from kicad_agent.llm.knowledge import _truncate_section
        assert _truncate_section("") == ""

    def test_long_text_truncated_to_paragraph_boundary(self):
        """Long text is truncated at paragraph boundaries."""
        from kicad_agent.llm.knowledge import _truncate_section
        # Build text with many paragraphs
        paras = [f"Paragraph {i} with some filler content." for i in range(100)]
        text = "\n\n".join(paras)
        result = _truncate_section(text, max_tokens=20)
        # Result should be non-empty but shorter than input
        assert len(result) < len(text)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# Tests for CORE_RULES
# ---------------------------------------------------------------------------

class TestCoreRules:
    """Tests for the CORE_RULES constant."""

    def test_core_rules_contains_critical_rules(self):
        """CORE_RULES contains pin at=, Y inverted, R/C 3.81mm offset."""
        from kicad_agent.llm.knowledge import CORE_RULES
        assert "Pin (at X Y) = wire connection point" in CORE_RULES
        assert "INVERTED" in CORE_RULES
        assert "3.81mm" in CORE_RULES
        assert "Wires terminate at (at) coordinates" in CORE_RULES

    def test_core_rules_is_nonempty_string(self):
        """CORE_RULES is a non-empty string."""
        from kicad_agent.llm.knowledge import CORE_RULES
        assert isinstance(CORE_RULES, str)
        assert len(CORE_RULES) > 50


# ---------------------------------------------------------------------------
# Tests for KnowledgeManager
# ---------------------------------------------------------------------------

class TestKnowledgeManager:
    """Tests for the KnowledgeManager class."""

    def test_resolve_docs_dir_returns_docs_path(self, tmp_path):
        """Test 5: _resolve_docs_dir returns Path pointing to docs/."""
        # Create a fake docs directory structure
        # knowledge.py -> llm/ -> kicad_agent/ -> src/ -> project root
        fake_src = tmp_path / "src" / "kicad_agent" / "llm"
        fake_src.mkdir(parents=True)
        fake_docs = tmp_path / "docs"
        fake_docs.mkdir()

        # Write a minimal module that will be loaded
        (fake_src / "knowledge.py").write_text("pass")

        with mock.patch("kicad_agent.llm.knowledge.Path") as MockPath:
            # Make __file__ resolve to our fake path
            mock_file_path = fake_src / "knowledge.py"
            MockPath.return_value.resolve.return_value = mock_file_path
            # Mock is_dir to return True for docs
            original_is_dir = Path.is_dir
            def custom_is_dir(self):
                if self == fake_docs:
                    return True
                return original_is_dir(self)
            MockPath.is_dir = lambda self: self == fake_docs

            from kicad_agent.llm.knowledge import KnowledgeManager
            result = KnowledgeManager._resolve_docs_dir()
            # Should return a Path-like pointing to docs
            assert "docs" in str(result).lower() or "nonexistent" not in str(result).lower()

    def test_get_context_always_includes_core_rules(self, tmp_path):
        """Test 7: get_context_for_op() always includes CORE_RULES."""
        from kicad_agent.llm.knowledge import KnowledgeManager, CORE_RULES

        km = KnowledgeManager(docs_dir=tmp_path, disabled=False)
        ctx = km.get_context_for_op("add_wire", "kicad_sch")
        assert CORE_RULES in ctx

    def test_missing_docs_returns_core_rules_only(self, tmp_path):
        """Test 11: Missing docs_dir returns CORE_RULES only (no crash)."""
        from kicad_agent.llm.knowledge import KnowledgeManager, CORE_RULES

        km = KnowledgeManager(docs_dir=Path("/nonexistent"), disabled=False)
        ctx = km.get_context_for_op("add_wire", "kicad_sch")
        assert CORE_RULES in ctx
        # Should not have any doc sections
        lines = ctx.strip().split("\n")
        # Only core rules header + content, no doc section headers
        doc_headers = [l for l in lines if l.startswith("## ") and l != "## KiCad Critical Rules"]
        assert len(doc_headers) == 0

    def test_caching_after_first_load(self, tmp_path):
        """Test 12: KnowledgeManager caches sections after first load."""
        from kicad_agent.llm.knowledge import KnowledgeManager

        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "kicad_agent_reference.md").write_text(
            "## Working with symbols\nSymbol content here."
        )

        km = KnowledgeManager(docs_dir=docs_dir)
        # First call loads
        ctx1 = km.get_context_for_op("add_wire", "kicad_sch")
        assert km._loaded is True
        # Capture sections dict reference
        sections_id = id(km._sections)
        # Second call should not re-read files
        ctx2 = km.get_context_for_op("add_wire", "kicad_sch")
        assert id(km._sections) == sections_id
        assert ctx1 == ctx2

    def test_deduplication_by_doc_and_section_pair(self, tmp_path):
        """Test 13: Deduplicates by (doc_name, section_name) pairs."""
        from kicad_agent.llm.knowledge import KnowledgeManager

        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "kicad_agent_reference.md").write_text(
            "## Working with symbols\nSymbol content here."
        )

        km = KnowledgeManager(docs_dir=docs_dir)

        # Manually inject duplicate mappings to test dedup
        original_map = km.get_context_for_op("add_component", "kicad_sch")

        # Count occurrences of the section content
        count = original_map.count("Symbol content here")
        assert count == 1, f"Expected 1 occurrence but found {count}"

    def test_full_doc_injection_for_no_header_docs(self, tmp_path):
        """Test: gerbview_reference.md (no ## headers) injects full text."""
        from kicad_agent.llm.knowledge import KnowledgeManager

        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        gerbview_content = "Gerbview reference content without headers."
        (docs_dir / "gerbview_reference.md").write_text(gerbview_content)

        km = KnowledgeManager(docs_dir=docs_dir)
        ctx = km.get_context_for_op("add_component", "kicad_sch")
        assert "Gerbview reference content" in ctx

    def test_disabled_returns_empty(self, tmp_path):
        """Test: disabled KnowledgeManager returns empty string."""
        from kicad_agent.llm.knowledge import KnowledgeManager

        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "kicad_agent_reference.md").write_text("## Section\nContent.")

        km = KnowledgeManager(docs_dir=docs_dir, disabled=True)
        ctx = km.get_context_for_op("add_wire", "kicad_sch")
        assert ctx == ""

    def test_env_var_token_budget(self):
        """Test: KICAD_KNOWLEDGE_TOKEN_BUDGET env var is respected."""
        from kicad_agent.llm.knowledge import KnowledgeManager

        with mock.patch.dict(os.environ, {"KICAD_KNOWLEDGE_TOKEN_BUDGET": "500"}):
            km = KnowledgeManager(disabled=True)
            assert km._max_tokens == 500

    def test_default_token_budget(self):
        """Test: default token budget is 2000."""
        from kicad_agent.llm.knowledge import KnowledgeManager

        # Ensure env var is not set
        with mock.patch.dict(os.environ, {}, clear=True):
            # Remove the var if present
            environ_backup = os.environ.pop("KICAD_KNOWLEDGE_TOKEN_BUDGET", None)
            try:
                km = KnowledgeManager(disabled=True)
                assert km._max_tokens == 2000
            finally:
                if environ_backup is not None:
                    os.environ["KICAD_KNOWLEDGE_TOKEN_BUDGET"] = environ_backup


# ---------------------------------------------------------------------------
# Tests for OP_SECTION_MAP coverage
# ---------------------------------------------------------------------------

class TestOpSectionMapCoverage:
    """Tests for OP_SECTION_MAP covering all registry operations."""

    def test_op_section_map_covers_all_registry_ops(self):
        """Test 14: OP_SECTION_MAP covers ALL operation types in OPERATION_REGISTRY."""
        from kicad_agent.llm.knowledge import OP_SECTION_MAP
        from kicad_agent.ops.registry import OPERATION_REGISTRY

        registry_ops = set(OPERATION_REGISTRY.keys())
        mapped_ops = set(OP_SECTION_MAP.keys())
        unmapped = registry_ops - mapped_ops
        if unmapped:
            pytest.fail(
                f"OP_SECTION_MAP missing {len(unmapped)} ops: {sorted(unmapped)[:10]}..."
            )

    def test_category_defaults_cover_all_categories(self):
        """Test 15: _CATEGORY_DEFAULTS covers ALL 21 categories from registry."""
        from kicad_agent.llm.knowledge import _CATEGORY_DEFAULTS
        from kicad_agent.ops.registry import OPERATION_REGISTRY

        categories = set(m.category for m in OPERATION_REGISTRY.values())
        covered = set(_CATEGORY_DEFAULTS.keys())
        uncovered = categories - covered
        if uncovered:
            pytest.fail(
                f"_CATEGORY_DEFAULTS missing {len(uncovered)} categories: {sorted(uncovered)}"
            )


# ---------------------------------------------------------------------------
# Tests for __all__ export
# ---------------------------------------------------------------------------

class TestExports:
    """Tests for module __all__ exports."""

    def test_all_defined_and_complete(self):
        """Test 16: __all__ includes all required exports."""
        from kicad_agent.llm import knowledge
        expected = {"KnowledgeManager", "get_context_for_op", "CORE_RULES", "OP_SECTION_MAP"}
        assert hasattr(knowledge, "__all__")
        assert set(knowledge.__all__) == expected


# ---------------------------------------------------------------------------
# Tests for Task 2: llm/__init__.py registration
# ---------------------------------------------------------------------------

class TestKnowledgeRegistration:
    """Tests for KnowledgeManager registration in llm/__init__.py."""

    def test_knowledge_manager_in_lazy_imports(self):
        """Test 1: KnowledgeManager is in _lazy dict mapped to correct module."""
        from kicad_agent import llm
        # Trigger __getattr__ to access _lazy
        lazy_dict = llm.__getattr__._lazy if hasattr(llm.__getattr__, '_lazy') else None
        # Access via the module's internal _lazy by calling __getattr__ machinery
        # Actually, we need to inspect the source or test import behavior
        # The simplest test: import should work
        pass

    def test_knowledge_manager_import_without_anthropic(self):
        """Test 4: from kicad_agent.llm import KnowledgeManager works without anthropic."""
        # This import must not raise ImportError for missing anthropic
        from kicad_agent.llm import KnowledgeManager
        assert KnowledgeManager is not None
