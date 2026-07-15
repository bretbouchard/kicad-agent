"""Tests for generation template modules."""

import pytest


class TestTemplateBoardDetailed:
    """Detailed tests for template board generation."""

    def test_import(self):
        """BoardTemplate is importable."""
        from volta.generation.template_board import BoardTemplate
        assert BoardTemplate is not None

    def test_generate_board_callable(self):
        """generate_board is callable."""
        from volta.generation.template_board import generate_board
        assert callable(generate_board)


class TestTemplateSchematicDetailed:
    """Detailed tests for template schematic generation."""

    def test_import(self):
        """SchematicTemplate is importable."""
        from volta.generation.template_schematic import SchematicTemplate
        assert SchematicTemplate is not None

    def test_generate_schematic_callable(self):
        """generate_schematic is callable."""
        from volta.generation.template_schematic import generate_schematic
        assert callable(generate_schematic)
