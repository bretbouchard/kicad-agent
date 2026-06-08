"""Tests for generation sub-modules: evaluation, pipeline, refinement, placement."""

import pytest


class TestEvaluation:
    """Tests for generation evaluation module."""

    def test_import(self):
        """Evaluation module is importable."""
        from kicad_agent.generation.evaluation import (
            EvaluationResult,
            evaluate_design,
            evaluate_intent_suite,
            get_test_intents,
        )
        assert EvaluationResult is not None
        assert callable(evaluate_design)
        assert callable(get_test_intents)


class TestPipeline:
    """Tests for generation pipeline module."""

    def test_import(self):
        """Pipeline module is importable."""
        from kicad_agent.generation.pipeline import GenerationResult, generate_design
        assert GenerationResult is not None
        assert callable(generate_design)


class TestRefinement:
    """Tests for generation refinement module."""

    def test_import(self):
        """Refinement module is importable."""
        from kicad_agent.generation.refinement import (
            RefinementIteration,
            RefinementResult,
            refine_design,
        )
        assert RefinementResult is not None
        assert callable(refine_design)


class TestPlacement:
    """Tests for generation placement module."""

    def test_import(self):
        """Placement module is importable."""
        from kicad_agent.generation.placement import (
            PlacementEngine,
            PlacementResult,
            validate_placement_clearance,
        )
        assert PlacementEngine is not None
        assert callable(validate_placement_clearance)


class TestTemplateBoard:
    """Tests for template board generation."""

    def test_import(self):
        """Template board module is importable."""
        from kicad_agent.generation.template_board import BoardTemplate, generate_board
        assert BoardTemplate is not None
        assert callable(generate_board)


class TestTemplateSchematic:
    """Tests for template schematic generation."""

    def test_import(self):
        """Template schematic module is importable."""
        from kicad_agent.generation.template_schematic import (
            SchematicTemplate,
            generate_schematic,
        )
        assert SchematicTemplate is not None
        assert callable(generate_schematic)


class TestOpPlanner:
    """Tests for operation planner module."""

    def test_import(self):
        """Op planner module is importable."""
        from kicad_agent.generation.op_planner import (
            OpPlanner,
            PlanStep,
            plan_operation_sequence,
        )
        assert OpPlanner is not None
        assert callable(plan_operation_sequence)
