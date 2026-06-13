"""Tests for NetIntentExtractor -- net intent classification and quality warnings.

Distribution per council LOW-1:
  - Net classification patterns: 3 tests (power/clock base delegation, high_current override, diff pair detection)
  - Hidden power pins: 2 tests (detected, none found)
  - Ambiguous connectors: 2 tests (detected, none found)
  - Stub symbols: 2 tests (detected, none found)
  - Integration: 2 tests (full gate result, net artifacts in GateResult)
  - Total: 11 tests
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _make_mock_component(
    reference: str = "U1",
    lib_id: str = "Device:R",
    footprint: str = "Resistor_SMD:R_0805",
    value: str = "10k",
    dnp: bool = False,
    pins: list | None = None,
    pin_types: list[str] | None = None,
) -> MagicMock:
    """Create a mock component with standard properties."""
    comp = MagicMock()
    comp.libId = lib_id
    comp.dnp = dnp
    comp.properties = [
        MagicMock(key="Reference", value=reference),
        MagicMock(key="Footprint", value=footprint),
        MagicMock(key="Value", value=value),
    ]

    # Build mock pins if provided
    if pins is not None:
        comp._mock_pins = pins
    else:
        comp._mock_pins = []
    if pin_types is not None:
        comp._mock_pin_types = pin_types
    else:
        comp._mock_pin_types = []

    return comp


def _make_mock_ir(
    components: list | None = None,
    wires: list | None = None,
    labels: list | None = None,
    net_labels: list | None = None,
    nets: dict | None = None,
    lib_symbols: list | None = None,
) -> MagicMock:
    """Create a mock SchematicIR."""
    ir = MagicMock()
    ir.components = components or []
    ir.wires = wires or []
    ir.labels = labels or []
    ir.net_labels = net_labels or []
    ir.nets = nets or {}
    ir.schematic.libSymbols = lib_symbols or []
    ir.get_component_property = MagicMock(
        side_effect=lambda comp, key: {
            (comp, "Reference"): getattr(comp, "_ref", "U1"),
            (comp, "Footprint"): getattr(comp, "_fp", ""),
            (comp, "Value"): getattr(comp, "_val", ""),
            (comp, "MPN"): getattr(comp, "_mpn", ""),
        }.get((comp, key))
    )
    return ir


# ---------------------------------------------------------------------------
# NetClassification enum extension tests
# ---------------------------------------------------------------------------


class TestNetClassificationExtension:
    """Verify NetClassification has the new gate-specific values."""

    def test_has_high_current(self):
        from kicad_agent.analysis.types import NetClassification

        assert hasattr(NetClassification, "HIGH_CURRENT")
        assert NetClassification.HIGH_CURRENT.value == "HIGH_CURRENT"

    def test_has_differential_pair(self):
        from kicad_agent.analysis.types import NetClassification

        assert hasattr(NetClassification, "DIFFERENTIAL_PAIR")
        assert NetClassification.DIFFERENTIAL_PAIR.value == "DIFFERENTIAL_PAIR"

    def test_has_analog_digital(self):
        from kicad_agent.analysis.types import NetClassification

        assert hasattr(NetClassification, "ANALOG")
        assert NetClassification.ANALOG.value == "ANALOG"
        assert hasattr(NetClassification, "DIGITAL")
        assert NetClassification.DIGITAL.value == "DIGITAL"


# ---------------------------------------------------------------------------
# Net classification pattern tests (3)
# ---------------------------------------------------------------------------


class TestNetClassificationPatterns:
    """Test net classification delegation and gate-specific overrides."""

    def test_power_and_clock_delegate_to_base_classifier(self):
        """POWER/GROUND/CLOCK from existing NetClassification are returned unchanged for known power/clock nets."""
        from kicad_agent.validation.gates.net_intent import NetIntentExtractor

        extractor = NetIntentExtractor()

        # Provide nets via mock labels
        label_vcc = MagicMock()
        label_vcc.text = "VCC"
        label_gnd = MagicMock()
        label_gnd.text = "GND"
        ir = _make_mock_ir(labels=[label_vcc, label_gnd])

        net_map = extractor.extract_nets(ir)
        # VCC/GND should be POWER/GROUND via base classifier
        assert net_map.get("VCC") == "POWER", f"Expected POWER for VCC, got {net_map.get('VCC')}"
        assert net_map.get("GND") == "GROUND", f"Expected GROUND for GND, got {net_map.get('GND')}"

    def test_high_current_override(self):
        """HIGH_CURRENT category assigned to nets matching motor/heater patterns."""
        from kicad_agent.validation.gates.net_intent import NetIntentExtractor

        extractor = NetIntentExtractor()

        # Provide nets via mock labels
        label_mot = MagicMock()
        label_mot.text = "MOT_DRV"
        label_heat = MagicMock()
        label_heat.text = "HEATER_OUT"
        ir = _make_mock_ir(labels=[label_mot, label_heat])

        net_map = extractor.extract_nets(ir)
        assert net_map.get("MOT_DRV") == "HIGH_CURRENT", f"Expected HIGH_CURRENT for MOT_DRV, got {net_map.get('MOT_DRV')}"
        assert net_map.get("HEATER_OUT") == "HIGH_CURRENT", f"Expected HIGH_CURRENT for HEATER_OUT, got {net_map.get('HEATER_OUT')}"

    def test_differential_pair_detection(self):
        """DIFFERENTIAL_PAIR category assigned to net name pairs ending in _P/_N or +/-."""
        from kicad_agent.validation.gates.net_intent import NetIntentExtractor

        extractor = NetIntentExtractor()

        # Provide nets via mock labels
        labels = []
        for name in ["SDI_P", "SDI_N", "SDA+", "SDA-"]:
            lbl = MagicMock()
            lbl.text = name
            labels.append(lbl)
        ir = _make_mock_ir(labels=labels)

        net_map = extractor.extract_nets(ir)
        # _P/_N suffix at end of name
        assert net_map.get("SDI_P") == "DIFFERENTIAL_PAIR", f"Expected DIFFERENTIAL_PAIR for SDI_P, got {net_map.get('SDI_P')}"
        assert net_map.get("SDI_N") == "DIFFERENTIAL_PAIR", f"Expected DIFFERENTIAL_PAIR for SDI_N, got {net_map.get('SDI_N')}"
        # +/- suffix at end of name
        assert net_map.get("SDA+") == "DIFFERENTIAL_PAIR", f"Expected DIFFERENTIAL_PAIR for SDA+, got {net_map.get('SDA+')}"
        assert net_map.get("SDA-") == "DIFFERENTIAL_PAIR", f"Expected DIFFERENTIAL_PAIR for SDA-, got {net_map.get('SDA-')}"


# ---------------------------------------------------------------------------
# Hidden power pin tests (2)
# ---------------------------------------------------------------------------


class TestHiddenPowerPins:
    """Test detection of unconnected power pins inside multi-unit symbols."""

    def test_hidden_power_pins_detected(self):
        """Hidden power pins return list of (reference, pin_name) strings."""
        from kicad_agent.validation.gates.net_intent import NetIntentExtractor

        extractor = NetIntentExtractor()

        # Create a multi-unit component with unconnected VCC/VSS power pins
        comp = MagicMock()
        comp.libId = "MyLib:LM358"
        comp.dnp = False
        comp.properties = [MagicMock(key="Reference", value="U1")]

        # Mock pins: some connected, some hidden power pins
        pin_vcc = MagicMock()
        pin_vcc.name = "VCC"
        pin_vcc.electricalType = "power_in"

        pin_gnd = MagicMock()
        pin_gnd.name = "GND"
        pin_gnd.electricalType = "power_in"

        pin_out = MagicMock()
        pin_out.name = "OUT"
        pin_out.electricalType = "output"

        # Unit with pins
        unit_a = MagicMock()
        unit_a.pins = [pin_out]  # No power pins in visible unit
        unit_b = MagicMock()
        unit_b.pins = [pin_vcc, pin_gnd]  # Hidden power pins in invisible unit

        lib_sym = MagicMock()
        lib_sym.libId = "MyLib:LM358"
        lib_sym.units = [unit_a, unit_b]

        ir = _make_mock_ir(components=[comp], lib_symbols=[lib_sym])

        hidden = extractor.detect_hidden_power_pins(ir)
        assert isinstance(hidden, list), f"Expected list, got {type(hidden)}"
        assert len(hidden) >= 1, f"Expected at least 1 hidden power pin, got {len(hidden)}"
        assert any("VCC" in h for h in hidden), f"Expected VCC in hidden pins, got: {hidden}"

    def test_no_hidden_power_pins(self):
        """Components with all power pins connected return empty list."""
        from kicad_agent.validation.gates.net_intent import NetIntentExtractor

        extractor = NetIntentExtractor()

        # Simple component with no hidden power pins
        comp = MagicMock()
        comp.libId = "Device:R"
        comp.dnp = False
        comp.properties = [MagicMock(key="Reference", value="R1")]

        lib_sym = MagicMock()
        lib_sym.libId = "Device:R"
        lib_sym.units = []

        ir = _make_mock_ir(components=[comp], lib_symbols=[lib_sym])

        hidden = extractor.detect_hidden_power_pins(ir)
        assert hidden == [], f"Expected no hidden power pins, got: {hidden}"


# ---------------------------------------------------------------------------
# Ambiguous connector tests (2)
# ---------------------------------------------------------------------------


class TestAmbiguousConnectors:
    """Test detection of connectors without pin-type assignments."""

    def test_ambiguous_connectors_detected(self):
        """Connectors without pin-type assignments return list of references."""
        from kicad_agent.validation.gates.net_intent import NetIntentExtractor

        extractor = NetIntentExtractor()

        # Create a connector component with passive-only pins (ambiguous)
        conn = MagicMock()
        conn.libId = "Connector:Conn_01x04"
        conn.dnp = False
        conn.properties = [MagicMock(key="Reference", value="J1")]

        lib_sym = MagicMock()
        lib_sym.libId = "Connector:Conn_01x04"

        pin1 = MagicMock()
        pin1.electricalType = "passive"  # Ambiguous -- no specific type
        pin2 = MagicMock()
        pin2.electricalType = "passive"

        unit = MagicMock()
        unit.pins = [pin1, pin2]
        lib_sym.units = [unit]

        ir = _make_mock_ir(components=[conn], lib_symbols=[lib_sym])

        ambiguous = extractor.detect_ambiguous_connectors(ir)
        assert isinstance(ambiguous, list), f"Expected list, got {type(ambiguous)}"
        assert len(ambiguous) >= 1, f"Expected at least 1 ambiguous connector, got {len(ambiguous)}"
        assert any("J1" in c for c in ambiguous), f"Expected J1 in connectors, got: {ambiguous}"

    def test_no_ambiguous_connectors(self):
        """Non-connector components return empty list."""
        from kicad_agent.validation.gates.net_intent import NetIntentExtractor

        extractor = NetIntentExtractor()

        # Regular IC component -- not a connector
        comp = MagicMock()
        comp.libId = "Device:R"
        comp.dnp = False
        comp.properties = [MagicMock(key="Reference", value="R1")]

        ir = _make_mock_ir(components=[comp])

        ambiguous = extractor.detect_ambiguous_connectors(ir)
        assert ambiguous == [], f"Expected no ambiguous connectors, got: {ambiguous}"


# ---------------------------------------------------------------------------
# Stub symbol tests (2)
# ---------------------------------------------------------------------------


class TestStubSymbols:
    """Test detection of symbols with zero pins."""

    def test_stub_symbols_detected(self):
        """Symbols with zero pins return list of references."""
        from kicad_agent.validation.gates.net_intent import NetIntentExtractor

        extractor = NetIntentExtractor()

        # Create a stub symbol with no pins
        stub = MagicMock()
        stub.libId = "Custom:Placeholder"
        stub.dnp = False
        stub.properties = [MagicMock(key="Reference", value="LOGO1")]

        lib_sym = MagicMock()
        lib_sym.libId = "Custom:Placeholder"
        lib_sym.units = []  # No units = no pins

        ir = _make_mock_ir(components=[stub], lib_symbols=[lib_sym])

        stubs = extractor.detect_stub_symbols(ir)
        assert isinstance(stubs, list), f"Expected list, got {type(stubs)}"
        assert len(stubs) >= 1, f"Expected at least 1 stub symbol, got {len(stubs)}"
        assert any("LOGO1" in s for s in stubs), f"Expected LOGO1 in stubs, got: {stubs}"

    def test_no_stub_symbols(self):
        """Components with pins return empty list."""
        from kicad_agent.validation.gates.net_intent import NetIntentExtractor

        extractor = NetIntentExtractor()

        # Normal component with pins
        comp = MagicMock()
        comp.libId = "Device:R"
        comp.dnp = False
        comp.properties = [MagicMock(key="Reference", value="R1")]

        lib_sym = MagicMock()
        lib_sym.libId = "Device:R"
        unit = MagicMock()
        pin1 = MagicMock()
        unit.pins = [pin1]
        lib_sym.units = [unit]

        ir = _make_mock_ir(components=[comp], lib_symbols=[lib_sym])

        stubs = extractor.detect_stub_symbols(ir)
        assert stubs == [], f"Expected no stub symbols, got: {stubs}"


# ---------------------------------------------------------------------------
# Pattern constants tests
# ---------------------------------------------------------------------------


class TestPatternConstants:
    """Verify module-level pattern constants exist and are used."""

    def test_pattern_constants_exist(self):
        """Module-level pattern constants _HIGH_CURRENT_PATTERNS, _DIFF_PAIR_PATTERN, etc. exist."""
        import kicad_agent.validation.gates.net_intent as module

        assert hasattr(module, "_HIGH_CURRENT_PATTERNS")
        assert hasattr(module, "_DIFF_PAIR_PATTERN")
        assert hasattr(module, "_ANALOG_PATTERNS")
        assert hasattr(module, "_DIGITAL_PATTERNS")
        assert hasattr(module, "_CONNECTOR_PREFIXES")
