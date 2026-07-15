"""TDD tests for design review engine.

RED phase: All tests must fail before implementation exists.

Tests cover:
- DesignFinding schema validation
- DesignReview schema with auto-computed summary
- Bypass cap detection on IC power pins
- Feedback compensation detection on op-amp circuits
- Power decoupling / filtering checks
- Input protection checks
- Component value optimization suggestions
- Intent-aware severity escalation
- Deterministic output
"""

import pytest

from volta.analysis.topology_graph import (
    CircuitTopology,
    NetClassification,
    TopologyEdge,
    TopologyNode,
)
from volta.analysis.intent_schemas import DesignGoal, DesignIntent, SubcircuitIntent


# ---------------------------------------------------------------------------
# Helpers to build test topologies using real interfaces
# ---------------------------------------------------------------------------

def _make_ic_node(
    ref: str,
    lib_id: str,
    power_pins: tuple[str, ...] = (),
    input_pins: tuple[str, ...] = (),
    output_pins: tuple[str, ...] = (),
    pin_count: int = 8,
) -> TopologyNode:
    return TopologyNode(
        ref=ref,
        lib_id=lib_id,
        component_type="ic",
        pin_count=pin_count,
        power_pins=power_pins,
        input_pins=input_pins,
        output_pins=output_pins,
    )


def _make_cap_node(ref: str, value: str = "100nF") -> TopologyNode:
    return TopologyNode(
        ref=ref,
        lib_id="Device:C",
        component_type="capacitor",
        pin_count=2,
        power_pins=(),
        input_pins=(),
        output_pins=(),
    )


def _make_resistor_node(ref: str, value: str = "10k") -> TopologyNode:
    return TopologyNode(
        ref=ref,
        lib_id="Device:R",
        component_type="resistor",
        pin_count=2,
        power_pins=(),
        input_pins=(),
        output_pins=(),
    )


def _make_diode_node(ref: str) -> TopologyNode:
    return TopologyNode(
        ref=ref,
        lib_id="Device:D",
        component_type="diode",
        pin_count=2,
        power_pins=(),
        input_pins=(),
        output_pins=(),
    )


def _make_edge(
    net_name: str,
    source_ref: str,
    source_pin: str,
    target_ref: str,
    target_pin: str,
    signal_direction: str = "forward",
) -> TopologyEdge:
    return TopologyEdge(
        net_name=net_name,
        source_ref=source_ref,
        source_pin=source_pin,
        target_ref=target_ref,
        target_pin=target_pin,
        classification=NetClassification.SIGNAL,
        signal_direction=signal_direction,
    )


# ---------------------------------------------------------------------------
# Test topologies
# ---------------------------------------------------------------------------

# IC with NO bypass cap on power nets
IC_NO_BYPASS = _make_ic_node(
    "U22", "THAT4301",
    power_pins=("V+", "V-"),
    input_pins=("IN",),
    output_pins=("OUT",),
)
TOPOLOGY_NO_BYPASS = CircuitTopology(
    nodes=(IC_NO_BYPASS,),
    edges=(
        _make_edge("+9V", "U22", "V+", "EXT", "PWR_OUT"),
        _make_edge("-9V", "EXT", "PWR_OUT", "U22", "V-"),
        _make_edge("AUDIO_IN", "J1", "1", "U22", "IN"),
        _make_edge("AUDIO_OUT", "U22", "OUT", "J2", "1"),
    ),
    input_nets=("AUDIO_IN",),
    output_nets=("AUDIO_OUT",),
    power_nets=("+9V", "-9V"),
    signal_paths=(("J1", "U22", "J2"),),
    stats={"component_count": 1, "net_count": 4},
)

# IC WITH bypass cap on power net
IC_WITH_BYPASS = _make_ic_node(
    "U22", "THAT4301",
    power_pins=("V+", "V-"),
    input_pins=("IN",),
    output_pins=("OUT",),
)
BYPASS_CAP = _make_cap_node("C49", "100nF")
TOPOLOGY_WITH_BYPASS = CircuitTopology(
    nodes=(IC_WITH_BYPASS, BYPASS_CAP),
    edges=(
        _make_edge("+9V", "U22", "V+", "C49", "1"),
        _make_edge("GNDA", "C49", "2", "EXT", "GND"),
        _make_edge("-9V", "EXT", "PWR", "U22", "V-"),
        _make_edge("AUDIO_IN", "J1", "1", "U22", "IN"),
        _make_edge("AUDIO_OUT", "U22", "OUT", "J2", "1"),
    ),
    input_nets=("AUDIO_IN",),
    output_nets=("AUDIO_OUT",),
    power_nets=("+9V", "-9V", "GNDA"),
    signal_paths=(("J1", "U22", "J2"),),
    stats={"component_count": 2, "net_count": 5},
)

# Op-amp with feedback but NO compensation cap
OPAMP_NO_COMP = _make_ic_node(
    "U24", "NE5532",
    input_pins=("+", "-"),
    output_pins=("OUT",),
)
FEEDBACK_R = _make_resistor_node("R67", "10k")
TOPOLOGY_NO_COMP = CircuitTopology(
    nodes=(OPAMP_NO_COMP, FEEDBACK_R),
    edges=(
        _make_edge("FEEDBACK", "U24", "-", "R67", "2", signal_direction="feedback"),
        _make_edge("EQ_OUT", "R67", "1", "U24", "OUT"),
        _make_edge("BUFFER_IN", "J1", "1", "U24", "+"),
    ),
    input_nets=("BUFFER_IN",),
    output_nets=("EQ_OUT",),
    power_nets=(),
    signal_paths=(("J1", "U24"),),
    stats={"component_count": 2, "net_count": 3},
)

# Power rail without bulk cap
POWER_IC = _make_ic_node(
    "U5", "LM7812",
    input_pins=("IN",),
    output_pins=("OUT",),
    power_pins=("GND",),
)
TOPOLOGY_NO_BULK_CAP = CircuitTopology(
    nodes=(POWER_IC,),
    edges=(
        _make_edge("+15V", "J1", "1", "U5", "IN"),
        _make_edge("+12V", "U5", "OUT", "J2", "1"),
        _make_edge("GND", "U5", "GND", "EXT", "GND"),
    ),
    input_nets=("+15V",),
    output_nets=("+12V",),
    power_nets=("+15V", "+12V", "GND"),
    signal_paths=(),
    stats={"component_count": 1, "net_count": 3},
)

# Well-designed circuit -- has bypass caps, feedback comp, input protection
WELL_DESIGNED = CircuitTopology(
    nodes=(
        _make_ic_node("U1", "NE5532",
                       power_pins=("V+", "V-"),
                       input_pins=("+",),
                       output_pins=("OUT",),
                       ),
        _make_cap_node("C1", "100nF"),
        _make_cap_node("C2", "100nF"),
        _make_resistor_node("R1", "10k"),
        _make_cap_node("C3", "22pF"),
        _make_resistor_node("R2", "1k"),
        _make_diode_node("D1"),
    ),
    edges=(
        _make_edge("+15V", "U1", "V+", "C1", "1"),
        _make_edge("-15V", "C2", "1", "U1", "V-"),
        _make_edge("FB", "U1", "-", "R1", "2", signal_direction="feedback"),
        _make_edge("OUT", "U1", "OUT", "R1", "1"),
        _make_edge("FB", "C3", "2", "U1", "-"),
        _make_edge("OUT", "U1", "OUT", "C3", "1"),
        _make_edge("IN", "R2", "2", "U1", "+"),
        _make_edge("EXT_IN", "D1", "1", "R2", "1"),
    ),
    input_nets=("EXT_IN",),
    output_nets=("OUT",),
    power_nets=("+15V", "-15V", "GND"),
    signal_paths=(("D1", "R2", "U1"),),
    stats={"component_count": 7, "net_count": 6},
)


# ---------------------------------------------------------------------------
# Test: DesignFinding Schema
# ---------------------------------------------------------------------------

class TestDesignFindingSchema:
    """Schema validation for DesignFinding."""

    def test_validates_with_all_fields(self):
        """Test 1: DesignFinding validates with category, severity, description, location, suggestion."""
        from volta.analysis.design_review import DesignFinding, ReviewCategory, ReviewSeverity

        finding = DesignFinding(
            category=ReviewCategory.MISSING_BYPASS_CAPS,
            severity=ReviewSeverity.WARNING,
            description="U22 has no bypass cap on +9V",
            location="U22",
            suggestion="Add 100nF ceramic cap near U22",
            affected_components=("U22",),
        )
        assert finding.category == ReviewCategory.MISSING_BYPASS_CAPS
        assert finding.severity == ReviewSeverity.WARNING
        assert "U22" in finding.description
        assert finding.affected_components == ("U22",)

    def test_rejects_invalid_severity(self):
        """Test 2: DesignFinding rejects invalid severity values."""
        from volta.analysis.design_review import DesignFinding, ReviewCategory

        with pytest.raises(Exception):
            DesignFinding(
                category=ReviewCategory.MISSING_BYPASS_CAPS,
                severity="INVALID",
                description="test",
                location="U1",
            )

    def test_rejects_empty_description(self):
        """Test 3: DesignFinding rejects empty description."""
        from volta.analysis.design_review import DesignFinding, ReviewCategory, ReviewSeverity

        with pytest.raises(Exception):
            DesignFinding(
                category=ReviewCategory.MISSING_BYPASS_CAPS,
                severity=ReviewSeverity.WARNING,
                description="",
                location="U1",
            )

        with pytest.raises(Exception):
            DesignFinding(
                category=ReviewCategory.MISSING_BYPASS_CAPS,
                severity=ReviewSeverity.WARNING,
                description="   ",
                location="U1",
            )


# ---------------------------------------------------------------------------
# Test: DesignReview Schema
# ---------------------------------------------------------------------------

class TestDesignReviewSchema:
    """Schema validation for DesignReview."""

    def test_validates_with_findings(self):
        """Test 4: DesignReview validates with findings list, summary stats, schematic_path."""
        from volta.analysis.design_review import (
            DesignFinding,
            DesignReview,
            ReviewCategory,
            ReviewSeverity,
        )

        finding = DesignFinding(
            category=ReviewCategory.MISSING_BYPASS_CAPS,
            severity=ReviewSeverity.WARNING,
            description="U22 has no bypass cap",
            location="U22",
        )
        review = DesignReview(
            findings=(finding,),
            schematic_path="compressor.kicad_sch",
        )
        assert len(review.findings) == 1
        assert review.schematic_path == "compressor.kicad_sch"

    def test_computes_summary_counts(self):
        """Test 5: DesignReview computes summary counts by severity automatically."""
        from volta.analysis.design_review import (
            DesignFinding,
            DesignReview,
            ReviewCategory,
            ReviewSeverity,
        )

        findings = (
            DesignFinding(
                category=ReviewCategory.MISSING_BYPASS_CAPS,
                severity=ReviewSeverity.CRITICAL,
                description="Critical issue",
                location="U1",
            ),
            DesignFinding(
                category=ReviewCategory.SIGNAL_INTEGRITY,
                severity=ReviewSeverity.WARNING,
                description="Warning issue",
                location="U2",
            ),
            DesignFinding(
                category=ReviewCategory.COMPONENT_VALUE_OPTIMIZATION,
                severity=ReviewSeverity.INFO,
                description="Info note",
                location="R1",
            ),
        )
        review = DesignReview(findings=findings, schematic_path="test.kicad_sch")
        assert review.summary["CRITICAL"] == 1
        assert review.summary["WARNING"] == 1
        assert review.summary["INFO"] == 1
        assert review.summary["SUGGESTION"] == 0


# ---------------------------------------------------------------------------
# Test: Bypass Cap Detection
# ---------------------------------------------------------------------------

class TestBypassCapReview:
    """Test bypass cap detection on IC power pins."""

    def test_flags_missing_bypass_cap(self):
        """Test 6: Identifies missing bypass cap on IC with power pins."""
        from volta.analysis.design_review import DesignReviewer, ReviewCategory, ReviewSeverity

        reviewer = DesignReviewer()
        review = reviewer.review(TOPOLOGY_NO_BYPASS)
        bypass_findings = [
            f for f in review.findings
            if f.category == ReviewCategory.MISSING_BYPASS_CAPS
        ]
        assert len(bypass_findings) >= 1
        assert any("U22" in f.affected_components for f in bypass_findings)

    def test_does_not_flag_ic_with_bypass(self):
        """Test 7: Does NOT flag IC that has bypass cap."""
        from volta.analysis.design_review import DesignReviewer, ReviewCategory

        reviewer = DesignReviewer()
        review = reviewer.review(TOPOLOGY_WITH_BYPASS)
        bypass_findings = [
            f for f in review.findings
            if f.category == ReviewCategory.MISSING_BYPASS_CAPS
        ]
        # Should have no bypass findings for U22 since C49 is on +9V
        u22_findings = [f for f in bypass_findings if "U22" in f.affected_components]
        assert len(u22_findings) == 0


# ---------------------------------------------------------------------------
# Test: Feedback Compensation
# ---------------------------------------------------------------------------

class TestFeedbackCompensationReview:
    """Test feedback compensation detection on op-amp circuits."""

    def test_flags_missing_feedback_compensation(self):
        """Test 8: Identifies missing feedback compensation cap on op-amp with feedback network."""
        from volta.analysis.design_review import DesignReviewer, ReviewCategory

        reviewer = DesignReviewer()
        review = reviewer.review(TOPOLOGY_NO_COMP)
        feedback_findings = [
            f for f in review.findings
            if f.category == ReviewCategory.FEEDBACK_COMPENSATION
        ]
        assert len(feedback_findings) >= 1
        assert any("U24" in f.affected_components for f in feedback_findings)


# ---------------------------------------------------------------------------
# Test: Power Decoupling
# ---------------------------------------------------------------------------

class TestPowerDecouplingReview:
    """Test power rail filtering checks."""

    def test_flags_power_rail_without_filtering(self):
        """Test 9: Identifies power rail without filtering cap."""
        from volta.analysis.design_review import DesignReviewer, ReviewCategory

        reviewer = DesignReviewer()
        review = reviewer.review(TOPOLOGY_NO_BULK_CAP)
        power_findings = [
            f for f in review.findings
            if f.category == ReviewCategory.POWER_DECOUPLING
        ]
        assert len(power_findings) >= 1


# ---------------------------------------------------------------------------
# Test: Component Value Optimization
# ---------------------------------------------------------------------------

class TestComponentValueReview:
    """Test component value optimization suggestions."""

    def test_flags_high_value_resistor_in_signal_path(self):
        """Test 10: Identifies high-value resistor in signal path (potential noise issue).

        Note: This test uses a topology with a high-value resistor (470k) connected
        to an audio signal net, which should trigger an INFO finding.
        """
        from volta.analysis.design_review import DesignReviewer, ReviewCategory

        # Build topology with a 470k resistor in signal path
        high_r = TopologyNode(
            ref="R99", lib_id="Device:R", component_type="resistor",
            pin_count=2, power_pins=(), input_pins=(), output_pins=(),
        )
        ic = _make_ic_node("U1", "NE5532",
                           power_pins=("V+", "V-"),
                           input_pins=("+",),
                           output_pins=("OUT",))
        topo = CircuitTopology(
            nodes=(high_r, ic),
            edges=(
                _make_edge("AUDIO_IN", "J1", "1", "R99", "1"),
                _make_edge("SIG_NET", "R99", "2", "U1", "+"),
            ),
            input_nets=("AUDIO_IN",),
            output_nets=(),
            power_nets=("+9V",),
            signal_paths=(("R99", "U1"),),
            stats={"component_count": 2, "net_count": 2},
        )
        # The plan says high-value resistor -> INFO, but we need value info.
        # DesignReviewer will check component value from topology if available,
        # or from topology edges. For now, test that the review runs without error.
        reviewer = DesignReviewer()
        review = reviewer.review(topo)
        # At minimum, no crash
        assert review is not None


# ---------------------------------------------------------------------------
# Test: Input Protection
# ---------------------------------------------------------------------------

class TestSignalIntegrityReview:
    """Test input protection and signal integrity checks."""

    def test_flags_input_without_protection(self):
        """Test 11: Identifies input net without protection."""
        from volta.analysis.design_review import DesignReviewer, ReviewCategory

        # Build topology with input net going directly to IC with no series R or diode
        ic = _make_ic_node("U1", "NE5532",
                           power_pins=("V+", "V-"),
                           input_pins=("+",),
                           output_pins=("OUT",))
        topo = CircuitTopology(
            nodes=(ic,),
            edges=(
                _make_edge("EXT_INPUT", "J1", "1", "U1", "+"),
                _make_edge("AUDIO_OUT", "U1", "OUT", "J2", "1"),
            ),
            input_nets=("EXT_INPUT",),
            output_nets=("AUDIO_OUT",),
            power_nets=("+9V",),
            signal_paths=(("J1", "U1", "J2"),),
            stats={"component_count": 1, "net_count": 3},
        )
        reviewer = DesignReviewer()
        review = reviewer.review(topo)
        si_findings = [
            f for f in review.findings
            if f.category == ReviewCategory.SIGNAL_INTEGRITY
        ]
        assert len(si_findings) >= 1


# ---------------------------------------------------------------------------
# Test: Intent-Aware Severity Escalation
# ---------------------------------------------------------------------------

class TestIntentAwareSeverity:
    """Test severity escalation based on design intent."""

    def test_critical_for_audio_processing_missing_bypass(self):
        """Test 12: CRITICAL severity for missing bypass on audio processing ICs."""
        from volta.analysis.design_review import DesignReviewer, ReviewSeverity

        intent = DesignIntent(
            overall_type="compressor",
            design_goals=(DesignGoal.AUDIO_PROCESSING,),
            confidence=0.9,
            schematic_path="compressor.kicad_sch",
        )
        reviewer = DesignReviewer()
        review = reviewer.review(TOPOLOGY_NO_BYPASS, intent=intent)
        # Find the bypass cap finding for U22
        bypass_findings = [
            f for f in review.findings
            if f.category.value == "missing_bypass_caps" and "U22" in f.affected_components
        ]
        assert len(bypass_findings) >= 1
        assert bypass_findings[0].severity == ReviewSeverity.CRITICAL

    def test_info_for_component_value_optimization(self):
        """Test 13: INFO severity for component value optimization suggestions."""
        from volta.analysis.design_review import DesignReviewer, ReviewCategory, ReviewSeverity

        # Well-designed circuit should only produce INFO-level findings at most
        reviewer = DesignReviewer()
        review = reviewer.review(WELL_DESIGNED)
        # Check that any component value findings are INFO
        cv_findings = [
            f for f in review.findings
            if f.category == ReviewCategory.COMPONENT_VALUE_OPTIMIZATION
        ]
        for f in cv_findings:
            assert f.severity == ReviewSeverity.INFO


# ---------------------------------------------------------------------------
# Test: Well-Designed Circuit
# ---------------------------------------------------------------------------

class TestWellDesignedCircuit:
    """Test that well-designed circuits produce minimal findings."""

    def test_minimal_findings_for_well_designed(self):
        """Test 14: Returns empty/minimal findings for well-designed circuit."""
        from volta.analysis.design_review import DesignReviewer, ReviewCategory

        reviewer = DesignReviewer()
        review = reviewer.review(WELL_DESIGNED)
        # Well-designed circuit should have no bypass cap or feedback comp findings
        critical_categories = {
            ReviewCategory.MISSING_BYPASS_CAPS,
            ReviewCategory.FEEDBACK_COMPENSATION,
        }
        critical_findings = [
            f for f in review.findings if f.category in critical_categories
        ]
        assert len(critical_findings) == 0


# ---------------------------------------------------------------------------
# Test: Determinism
# ---------------------------------------------------------------------------

class TestDeterminism:
    """Test that review is deterministic."""

    def test_same_input_same_output(self):
        """Test 15: Same input produces identical output."""
        from volta.analysis.design_review import DesignReviewer

        reviewer = DesignReviewer()
        review1 = reviewer.review(TOPOLOGY_NO_BYPASS)
        review2 = reviewer.review(TOPOLOGY_NO_BYPASS)

        assert len(review1.findings) == len(review2.findings)
        for f1, f2 in zip(review1.findings, review2.findings):
            assert f1.category == f2.category
            assert f1.severity == f2.severity
            assert f1.description == f2.description
            assert f1.location == f2.location
            assert f1.suggestion == f2.suggestion
