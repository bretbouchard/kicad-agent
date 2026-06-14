"""Tests for constraint propagator and completeness gate.

Covers ConstraintPropagator (writes to .kicad_dru via DesignRulesFile),
ConstraintCompletenessGate (validates nontrivial nets have constraints),
and gate registration.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from kicad_agent.analysis.types import NetClassification
from kicad_agent.project.design_rules import parse_design_rules
from kicad_agent.validation.gate_runner import get_gate_runner
from kicad_agent.validation.gates.constraint_gate import (
    ConstraintCompletenessGate,
    ConstraintPropagator,
)
from kicad_agent.validation.gates.constraint_schema import (
    DesignConstraints,
    DiffPairSpec,
    ElectricalConstraints,
    FabProfileConstraints,
    MechanicalConstraints,
)


# ---------------------------------------------------------------------------
# ConstraintPropagator
# ---------------------------------------------------------------------------

class TestConstraintPropagator:
    """Test that constraints propagate to .kicad_dru via DesignRulesFile."""

    def _propagator(self) -> ConstraintPropagator:
        return ConstraintPropagator()

    def test_propagate_creates_dru_file(self) -> None:
        """Propagator creates .kicad_dru when it does not exist."""
        constraints = DesignConstraints(
            electrical=[
                ElectricalConstraints(net_name="VCC", current_ma=500.0),
            ],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            dru_path = Path(tmpdir) / "board.kicad_dru"
            propagator = self._propagator()
            warnings = propagator.propagate(constraints, dru_path)

            assert dru_path.exists(), ".kicad_dru file should be created"
            dru = parse_design_rules(dru_path)
            assert len(dru.net_classes) == 1
            assert dru.net_classes[0].name == "VCC"

    def test_propagate_multiple_nets(self) -> None:
        """Propagator writes multiple net classes."""
        constraints = DesignConstraints(
            electrical=[
                ElectricalConstraints(net_name="VCC", current_ma=500.0),
                ElectricalConstraints(
                    net_name="USB_DP",
                    diff_pair=DiffPairSpec(pair_name="USB", gap_mm=0.15),
                    impedance_ohm=90.0,
                ),
            ],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            dru_path = Path(tmpdir) / "board.kicad_dru"
            propagator = self._propagator()
            warnings = propagator.propagate(constraints, dru_path)

            dru = parse_design_rules(dru_path)
            names = {nc.name for nc in dru.net_classes}
            assert "VCC" in names
            assert "USB_DP" in names

    def test_propagate_skips_existing_net_class(self) -> None:
        """Propagator skips nets whose class already exists in .kicad_dru."""
        constraints = DesignConstraints(
            electrical=[
                ElectricalConstraints(net_name="VCC", current_ma=500.0),
            ],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            dru_path = Path(tmpdir) / "board.kicad_dru"
            propagator = self._propagator()

            # First propagation: creates VCC
            propagator.propagate(constraints, dru_path)

            # Second propagation: should skip VCC
            warnings = propagator.propagate(constraints, dru_path)

            dru = parse_design_rules(dru_path)
            assert len(dru.net_classes) == 1  # still only one

    def test_propagate_preserves_existing_classes(self) -> None:
        """Propagator does not remove existing net classes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dru_path = Path(tmpdir) / "board.kicad_dru"

            # Write an initial .kicad_dru with "Default" class
            from kicad_agent.project.design_rules import (
                DesignRulesFile,
                NetClassDef,
            )
            initial_dru = DesignRulesFile()
            initial_dru.add_net_class(
                NetClassDef(name="Default", clearance=0.2, track_width=0.25)
            )
            initial_dru.to_file(dru_path)

            # Propagate additional constraints
            constraints = DesignConstraints(
                electrical=[
                    ElectricalConstraints(net_name="VCC", current_ma=500.0),
                ],
            )
            propagator = self._propagator()
            propagator.propagate(constraints, dru_path)

            dru = parse_design_rules(dru_path)
            names = {nc.name for nc in dru.net_classes}
            assert "Default" in names
            assert "VCC" in names

    def test_propagate_returns_achievable_warnings(self) -> None:
        """Propagator returns warnings from validate_achievable."""
        constraints = DesignConstraints(
            electrical=[
                ElectricalConstraints(
                    net_name="USB_DP",
                    diff_pair=DiffPairSpec(pair_name="USB", gap_mm=0.05),
                ),
            ],
            fab=FabProfileConstraints.jlcpcb(),
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            dru_path = Path(tmpdir) / "board.kicad_dru"
            propagator = self._propagator()
            warnings = propagator.propagate(constraints, dru_path)
            assert any("gap" in w.lower() for w in warnings)

    def test_propagate_with_impedance_sets_diff_pair_width(self) -> None:
        """Impedance target propagates to diff_pair_width in net class."""
        constraints = DesignConstraints(
            electrical=[
                ElectricalConstraints(
                    net_name="USB_DP",
                    diff_pair=DiffPairSpec(pair_name="USB", gap_mm=0.15),
                    impedance_ohm=90.0,
                ),
            ],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            dru_path = Path(tmpdir) / "board.kicad_dru"
            propagator = self._propagator()
            propagator.propagate(constraints, dru_path)

            dru = parse_design_rules(dru_path)
            nc = dru.net_classes[0]
            assert nc.diff_pair_gap > 0
            assert nc.diff_pair_width > 0

    def test_propagate_high_current_sets_wider_trace(self) -> None:
        """High current propagates to wider track_width in net class."""
        constraints = DesignConstraints(
            electrical=[
                ElectricalConstraints(net_name="MOTOR", current_ma=2000.0),
            ],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            dru_path = Path(tmpdir) / "board.kicad_dru"
            propagator = self._propagator()
            propagator.propagate(constraints, dru_path)

            dru = parse_design_rules(dru_path)
            nc = dru.net_classes[0]
            assert nc.track_width >= 1.0  # 2000mA / 1000 = 2mm minimum

    def test_propagate_no_electrical_constraints(self) -> None:
        """Propagator with no electrical constraints produces empty file."""
        constraints = DesignConstraints(electrical=[])
        with tempfile.TemporaryDirectory() as tmpdir:
            dru_path = Path(tmpdir) / "board.kicad_dru"
            propagator = self._propagator()
            propagator.propagate(constraints, dru_path)

            dru = parse_design_rules(dru_path)
            assert len(dru.net_classes) == 0


# ---------------------------------------------------------------------------
# ConstraintCompletenessGate
# ---------------------------------------------------------------------------

class TestConstraintCompletenessGate:
    """Test that the gate blocks placement when constraints are missing."""

    def _gate(self) -> ConstraintCompletenessGate:
        return ConstraintCompletenessGate()

    def test_passes_when_all_nontrivial_nets_have_constraints(self) -> None:
        """Gate passes when POWER, CLOCK, DIFFERENTIAL_PAIR, HIGH_CURRENT nets
        all have electrical constraints."""
        gate = self._gate()
        context = {
            "design_constraints": DesignConstraints(
                electrical=[
                    ElectricalConstraints(net_name="VCC", current_ma=500.0),
                    ElectricalConstraints(net_name="CLK", frequency_hz=100e6),
                    ElectricalConstraints(
                        net_name="USB_DP",
                        diff_pair=DiffPairSpec(pair_name="USB", gap_mm=0.15),
                    ),
                    ElectricalConstraints(net_name="MOTOR", current_ma=2000.0),
                ],
            ),
            "net_intent": {
                "VCC": NetClassification.POWER,
                "GND": NetClassification.GROUND,  # not nontrivial
                "CLK": NetClassification.CLOCK,
                "USB_DP": NetClassification.DIFFERENTIAL_PAIR,
                "MOTOR": NetClassification.HIGH_CURRENT,
                "SIG1": NetClassification.SIGNAL,  # not nontrivial
            },
        }
        result = gate.run(context)
        assert result.pass_bool is True
        assert len(result.blockers) == 0

    def test_blocks_when_power_net_missing_constraints(self) -> None:
        """Gate fails when a POWER net has no electrical constraints."""
        gate = self._gate()
        context = {
            "design_constraints": DesignConstraints(electrical=[]),
            "net_intent": {
                "VCC": NetClassification.POWER,
            },
        }
        result = gate.run(context)
        assert result.pass_bool is False
        assert any("VCC" in b for b in result.blockers)

    def test_blocks_when_high_current_net_missing_constraints(self) -> None:
        """Gate fails when a HIGH_CURRENT net has no constraints."""
        gate = self._gate()
        context = {
            "design_constraints": DesignConstraints(electrical=[]),
            "net_intent": {
                "MOTOR": NetClassification.HIGH_CURRENT,
            },
        }
        result = gate.run(context)
        assert result.pass_bool is False
        assert any("MOTOR" in b for b in result.blockers)

    def test_blocks_when_diff_pair_missing_constraints(self) -> None:
        """Gate fails when a DIFFERENTIAL_PAIR net has no constraints."""
        gate = self._gate()
        context = {
            "design_constraints": DesignConstraints(electrical=[]),
            "net_intent": {
                "USB_DP": NetClassification.DIFFERENTIAL_PAIR,
            },
        }
        result = gate.run(context)
        assert result.pass_bool is False
        assert any("USB_DP" in b for b in result.blockers)

    def test_blocks_when_clock_net_missing_constraints(self) -> None:
        """Gate fails when a CLOCK net has no constraints."""
        gate = self._gate()
        context = {
            "design_constraints": DesignConstraints(electrical=[]),
            "net_intent": {
                "CLK": NetClassification.CLOCK,
            },
        }
        result = gate.run(context)
        assert result.pass_bool is False
        assert any("CLK" in b for b in result.blockers)

    def test_passes_when_only_signal_nets(self) -> None:
        """Gate passes when only SIGNAL nets exist (no nontrivial nets)."""
        gate = self._gate()
        context = {
            "design_constraints": DesignConstraints(
                electrical=[ElectricalConstraints(net_name="SIG1")]
            ),
            "net_intent": {
                "SIG1": NetClassification.SIGNAL,
                "SIG2": NetClassification.SIGNAL,
            },
        }
        result = gate.run(context)
        assert result.pass_bool is True

    def test_passes_when_ground_net_missing_constraints(self) -> None:
        """GROUND is not nontrivial -- gate passes without constraints for it."""
        gate = self._gate()
        context = {
            "design_constraints": DesignConstraints(electrical=[]),
            "net_intent": {
                "GND": NetClassification.GROUND,
            },
        }
        result = gate.run(context)
        assert result.pass_bool is True

    def test_fails_when_no_design_constraints_in_context(self) -> None:
        """Gate fails when design_constraints key is missing from context."""
        gate = self._gate()
        context: dict = {"net_intent": {"VCC": NetClassification.POWER}}
        result = gate.run(context)
        assert result.pass_bool is False
        assert any("No design_constraints" in b for b in result.blockers)

    def test_fails_when_design_constraints_wrong_type(self) -> None:
        """Gate fails when design_constraints is not a DesignConstraints instance."""
        gate = self._gate()
        context = {
            "design_constraints": "not a DesignConstraints",
            "net_intent": {},
        }
        result = gate.run(context)
        assert result.pass_bool is False
        assert any("wrong type" in b for b in result.blockers)

    def test_warns_on_default_fab_profile(self) -> None:
        """Gate warns when fab profile uses all defaults."""
        gate = self._gate()
        context = {
            "design_constraints": DesignConstraints(
                electrical=[ElectricalConstraints(net_name="SIG1")],
            ),
            "net_intent": {"SIG1": NetClassification.SIGNAL},
        }
        result = gate.run(context)
        assert result.pass_bool is True
        assert any("default" in w.lower() for w in result.warnings)

    def test_no_warning_with_named_preset(self) -> None:
        """Gate does not warn about defaults when named preset is used."""
        gate = self._gate()
        context = {
            "design_constraints": DesignConstraints(
                electrical=[ElectricalConstraints(net_name="VCC", current_ma=500.0)],
                fab=FabProfileConstraints.jlcpcb(),
            ),
            "net_intent": {"VCC": NetClassification.POWER},
        }
        result = gate.run(context)
        assert result.pass_bool is True
        assert not any("default" in w.lower() for w in result.warnings)

    def test_artifacts_count_electrical_constraints(self) -> None:
        """Gate artifacts report number of electrical constraints."""
        gate = self._gate()
        context = {
            "design_constraints": DesignConstraints(
                electrical=[
                    ElectricalConstraints(net_name="VCC", current_ma=500.0),
                    ElectricalConstraints(net_name="GND"),
                ],
            ),
            "net_intent": {},
        }
        result = gate.run(context)
        assert any("2 electrical constraints" in a for a in result.artifacts)

    def test_artifacts_report_fab_profile(self) -> None:
        """Gate artifacts report fab profile details."""
        gate = self._gate()
        context = {
            "design_constraints": DesignConstraints(
                fab=FabProfileConstraints.jlcpcb_4layer(),
            ),
            "net_intent": {},
        }
        result = gate.run(context)
        assert any("4-layer" in a for a in result.artifacts)

    def test_gate_stage_is_pcb_setup(self) -> None:
        """Gate result stage is always PCB_SETUP."""
        gate = self._gate()
        from kicad_agent.validation.gate_types import DesignStage
        context = {
            "design_constraints": DesignConstraints(),
            "net_intent": {},
        }
        result = gate.run(context)
        assert result.stage == DesignStage.PCB_SETUP

    def test_gate_name_is_constraint_completeness(self) -> None:
        """Gate result name is 'constraint_completeness'."""
        gate = self._gate()
        context = {
            "design_constraints": DesignConstraints(),
            "net_intent": {},
        }
        result = gate.run(context)
        assert result.gate_name == "constraint_completeness"


# ---------------------------------------------------------------------------
# Gate Registration
# ---------------------------------------------------------------------------

class TestGateRegistration:
    """Test that constraint_completeness gate is registered at module scope."""

    def test_gate_registered(self) -> None:
        """constraint_completeness gate exists in the default runner."""
        runner = get_gate_runner()
        gate = runner.get_gate("constraint_completeness")
        assert gate is not None
        assert gate.name == "constraint_completeness"

    def test_gate_transitions_pcb_setup_to_placement(self) -> None:
        """Gate is registered for PCB_SETUP -> PLACEMENT."""
        runner = get_gate_runner()
        gate = runner.get_gate("constraint_completeness")
        from kicad_agent.validation.gate_types import DesignStage
        assert gate.from_stage == DesignStage.PCB_SETUP
        assert gate.to_stage == DesignStage.PLACEMENT

    def test_gate_has_check_function(self) -> None:
        """Gate has a registered check function."""
        runner = get_gate_runner()
        assert runner.has_check_fn("constraint_completeness")

    def test_gate_runs_via_runner(self) -> None:
        """Gate can be executed via GateRunner.run_gate()."""
        runner = get_gate_runner()
        context = {
            "design_constraints": DesignConstraints(),
            "net_intent": {},
        }
        result = runner.run_gate("constraint_completeness", context)
        assert result.pass_bool is True

    def test_gate_in_required_gates_for_transition(self) -> None:
        """Gate appears in required gates for PCB_SETUP -> PLACEMENT."""
        runner = get_gate_runner()
        from kicad_agent.validation.gate_types import DesignStage
        gates = runner.get_required_gates(
            DesignStage.PCB_SETUP, DesignStage.PLACEMENT
        )
        assert "constraint_completeness" in gates
