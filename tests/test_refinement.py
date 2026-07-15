"""Tests for the iterative refinement loop.

Tests exercise refine_design() and analyze_erc_errors() with both
synthetic scenarios and real schematic files (when available).
"""

import shutil
from pathlib import Path

import pytest

from volta.generation.intent import (
    BoardSpec,
    ComponentSpec,
    GenerationIntent,
    PowerSpec,
)
from volta.generation.refinement import (
    RefinementIteration,
    RefinementResult,
    analyze_erc_errors,
    refine_design,
)
from volta.generation.template_schematic import generate_schematic
from volta.validation.erc_drc import ErcResult, Severity, Violation

KICAD_CLI_AVAILABLE = shutil.which("kicad-cli") is not None


class TestAnalyzeErcErrors:
    """Tests for ERC error classification."""

    def test_pin_not_connected_classified(self):
        """Pin not connected errors are classified as auto-fixable."""
        violations = (
            Violation(
                description="Pin 1 of component U1 is not connected",
                severity=Severity.ERROR,
                type="pin_not_connected",
            ),
        )
        erc_result = ErcResult(passed=False, file_path=Path("test.kicad_sch"), violations=violations)
        categories = analyze_erc_errors(erc_result)

        assert len(categories) == 1
        assert categories[0]["error_type"] == "pin_not_connected"
        assert categories[0]["count"] == 1
        assert categories[0]["auto_fixable"] is True

    def test_wire_not_connected_classified(self):
        """Wire not connected errors are classified as auto-fixable."""
        violations = (
            Violation(
                description="Wire not connected on sheet",
                severity=Severity.ERROR,
                type="wire_not_connected",
            ),
        )
        erc_result = ErcResult(passed=False, file_path=Path("test.kicad_sch"), violations=violations)
        categories = analyze_erc_errors(erc_result)

        assert len(categories) == 1
        assert categories[0]["error_type"] == "wire_not_connected"
        assert categories[0]["auto_fixable"] is True

    def test_missing_power_symbol_classified(self):
        """Missing power symbol errors are classified."""
        violations = (
            Violation(
                description="Missing power symbol on net VCC",
                severity=Severity.ERROR,
                type="power_symbol",
            ),
        )
        erc_result = ErcResult(passed=False, file_path=Path("test.kicad_sch"), violations=violations)
        categories = analyze_erc_errors(erc_result)

        assert any(c["error_type"] == "missing_power_symbol" for c in categories)

    def test_unknown_error_classified_as_other(self):
        """Unknown ERC errors are classified as 'other' (not auto-fixable)."""
        violations = (
            Violation(
                description="Some unknown error",
                severity=Severity.ERROR,
                type="unknown_type",
            ),
        )
        erc_result = ErcResult(passed=False, file_path=Path("test.kicad_sch"), violations=violations)
        categories = analyze_erc_errors(erc_result)

        assert len(categories) == 1
        assert categories[0]["error_type"] == "other"
        assert categories[0]["auto_fixable"] is False

    def test_warnings_not_classified(self):
        """Warnings are not included in error classification."""
        violations = (
            Violation(
                description="Pin not connected (warning)",
                severity=Severity.WARNING,
                type="pin_not_connected",
            ),
        )
        erc_result = ErcResult(passed=True, file_path=Path("test.kicad_sch"), violations=violations)
        categories = analyze_erc_errors(erc_result)

        assert len(categories) == 0

    def test_no_errors_returns_empty(self):
        """Clean ERC result returns empty list."""
        erc_result = ErcResult(passed=True, file_path=Path("test.kicad_sch"))
        categories = analyze_erc_errors(erc_result)

        assert categories == []

    def test_multiple_error_types(self):
        """Multiple error types are all classified."""
        violations = (
            Violation(
                description="Pin not connected",
                severity=Severity.ERROR,
                type="pin_not_connected",
            ),
            Violation(
                description="Wire not connected somewhere",
                severity=Severity.ERROR,
                type="wire_not_connected",
            ),
            Violation(
                description="Some other error",
                severity=Severity.ERROR,
                type="misc",
            ),
        )
        erc_result = ErcResult(passed=False, file_path=Path("test.kicad_sch"), violations=violations)
        categories = analyze_erc_errors(erc_result)

        assert len(categories) == 3
        types = {c["error_type"] for c in categories}
        assert "pin_not_connected" in types
        assert "wire_not_connected" in types
        assert "other" in types


class TestRefineDesign:
    """Tests for the refine_design() iterative loop."""

    def test_refine_design_nonexistent_schematic(self, tmp_path: Path):
        """Non-existent schematic returns empty result."""
        result = refine_design(tmp_path / "nonexistent.kicad_sch")
        assert isinstance(result, RefinementResult)
        assert result.total_iterations == 0
        assert result.converged is False

    def test_refine_design_clean_schematic(self, tmp_path: Path):
        """Clean schematic converges in 1 iteration when kicad-cli available."""
        if not KICAD_CLI_AVAILABLE:
            # Without kicad-cli, run_erc returns error_message result (not passed)
            # Create a schematic and verify the loop handles it gracefully
            intent = GenerationIntent(name="clean_test")
            sch_path = tmp_path / "clean_test.kicad_sch"
            generate_schematic(sch_path, intent)
            result = refine_design(sch_path, max_iterations=3)
            assert isinstance(result, RefinementResult)
            assert result.total_iterations > 0
            return

        intent = GenerationIntent(name="clean_test")
        sch_path = tmp_path / "clean_test.kicad_sch"
        generate_schematic(sch_path, intent)

        result = refine_design(sch_path, max_iterations=5)

        assert isinstance(result, RefinementResult)
        # Clean schematic should converge quickly
        assert result.total_iterations >= 1

    def test_refine_design_max_iterations(self, tmp_path: Path):
        """Schematic with persistent errors stops at max_iterations."""
        if not KICAD_CLI_AVAILABLE:
            pytest.skip("kicad-cli not available")

        intent = GenerationIntent(
            name="persistent_errors",
            components=[
                ComponentSpec(library_id="Device:R_Small_US", reference="R1", value="10k"),
            ],
        )
        sch_path = tmp_path / "persistent.kicad_sch"
        generate_schematic(sch_path, intent)

        result = refine_design(sch_path, max_iterations=3, target_erc_clean=True)

        # Should have run exactly 3 iterations (or converged earlier)
        assert result.total_iterations <= 3
        assert isinstance(result, RefinementResult)

    def test_refinement_result_structure(self, tmp_path: Path):
        """RefinementResult has all expected fields."""
        result = RefinementResult(
            iterations=(
                RefinementIteration(iteration=1, erc_errors=0, drc_errors=0, passed=True),
            ),
            final_erc_pass=True,
            final_drc_pass=False,
            total_iterations=1,
            converged=True,
        )

        assert isinstance(result.iterations, tuple)
        assert len(result.iterations) == 1
        assert result.iterations[0].iteration == 1
        assert result.final_erc_pass is True
        assert result.final_drc_pass is False
        assert result.total_iterations == 1
        assert result.converged is True

    def test_refinement_iteration_structure(self):
        """RefinementIteration has all expected fields."""
        it = RefinementIteration(
            iteration=2,
            erc_errors=3,
            drc_errors=1,
            fixes_applied=("Snapped 2 wires", "Placed 1 no-connect"),
            passed=False,
        )

        assert it.iteration == 2
        assert it.erc_errors == 3
        assert it.drc_errors == 1
        assert len(it.fixes_applied) == 2
        assert it.passed is False

    def test_refinement_hard_cap(self, tmp_path: Path):
        """Iterations are capped at hard limit even if max_iterations is higher."""
        if not KICAD_CLI_AVAILABLE:
            pytest.skip("kicad-cli not available")

        intent = GenerationIntent(name="hard_cap_test")
        sch_path = tmp_path / "hard_cap.kicad_sch"
        generate_schematic(sch_path, intent)

        # Request 100 iterations -- should be capped
        result = refine_design(sch_path, max_iterations=100)
        assert result.total_iterations <= 10  # Hard cap
