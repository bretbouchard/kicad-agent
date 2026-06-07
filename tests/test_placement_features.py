"""Tests for placement feature extraction (features.py).

Covers:
  - Component feature extraction for IC, passive, connector, fixed, unfixed
  - Net feature extraction for power nets, signal nets, high-speed nets
  - Edge cases: zero board dimensions, single-pin nets
  - Constant verification: feature vector dimensions
"""

from __future__ import annotations

import numpy as np
import pytest

from kicad_agent.generation.intent import ComponentSpec, NetSpec, PositionSpec
from kicad_agent.placement.features import (
    COMP_FEATURE_DIM,
    NET_FEATURE_DIM,
    _estimate_size,
    extract_component_features,
    extract_net_features,
)


class TestConstants:
    """Verify exported dimension constants."""

    def test_comp_feature_dim_is_32(self) -> None:
        assert COMP_FEATURE_DIM == 32

    def test_net_feature_dim_is_16(self) -> None:
        assert NET_FEATURE_DIM == 16


class TestEstimateSize:
    """Tests for internal _estimate_size heuristic."""

    def test_ic_returns_10(self) -> None:
        comp = ComponentSpec(library_id="MCU:IC1", reference="U1", value="IC")
        assert _estimate_size(comp) == 10.0

    def test_resistor_returns_2(self) -> None:
        comp = ComponentSpec(library_id="Device:R", reference="R1", value="10k")
        assert _estimate_size(comp) == 2.0

    def test_capacitor_returns_2(self) -> None:
        comp = ComponentSpec(library_id="Device:C", reference="C1", value="100nF")
        assert _estimate_size(comp) == 2.0

    def test_connector_returns_3(self) -> None:
        comp = ComponentSpec(library_id="Conn:J1", reference="J1", value="HDR")
        assert _estimate_size(comp) == 3.0

    def test_transistor_returns_8(self) -> None:
        comp = ComponentSpec(library_id="Device:Q", reference="Q1", value="2N2222")
        assert _estimate_size(comp) == 8.0

    def test_inductor_returns_5(self) -> None:
        comp = ComponentSpec(library_id="Device:L", reference="L1", value="4.7uH")
        assert _estimate_size(comp) == 5.0

    def test_diode_returns_5(self) -> None:
        comp = ComponentSpec(library_id="Device:D", reference="D1", value="1N4148")
        assert _estimate_size(comp) == 5.0


class TestExtractComponentFeatures:
    """Tests for extract_component_features output structure and values."""

    def test_returns_correct_shape(self) -> None:
        comp = ComponentSpec(library_id="Device:R", reference="R1", value="10k")
        features = extract_component_features(comp, 100.0, 80.0)
        assert features.shape == (COMP_FEATURE_DIM,)
        assert features.dtype == np.float32

    def test_ic_flags(self) -> None:
        comp = ComponentSpec(library_id="MCU:IC1", reference="U1", value="STM32")
        features = extract_component_features(comp, 100.0, 80.0)
        assert features[0] == 10.0   # estimated_size
        assert features[1] == 1.0      # is_ic
        assert features[2] == 0.0      # is_passive
        assert features[3] == 0.0      # is_connector

    def test_resistor_flags(self) -> None:
        comp = ComponentSpec(library_id="Device:R", reference="R1", value="10k")
        features = extract_component_features(comp, 100.0, 80.0)
        assert features[0] == 2.0       # estimated_size
        assert features[1] == 0.0        # is_ic
        assert features[2] == 1.0        # is_passive

    def test_connector_flag(self) -> None:
        comp = ComponentSpec(library_id="Conn:J1", reference="J1", value="HDR")
        features = extract_component_features(comp, 100.0, 80.0)
        assert features[3] == 1.0        # is_connector

    def test_fixed_position_normalization(self) -> None:
        comp = ComponentSpec(
            library_id="Device:R", reference="R1", value="10k",
            position=PositionSpec(x=50.0, y=40.0),
        )
        features = extract_component_features(comp, 100.0, 80.0)
        assert features[4] == 1.0       # is_fixed
        assert features[5] == pytest.approx(0.5)  # normalized x
        assert features[6] == pytest.approx(0.5)  # normalized y

    def test_unfixed_position_zeros(self) -> None:
        comp = ComponentSpec(library_id="Device:R", reference="R1", value="10k")
        features = extract_component_features(comp, 100.0, 80.0)
        assert features[4] == 0.0       # is_fixed
        assert features[5] == 0.0       # normalized x
        assert features[6] == 0.0       # normalized y

    def test_zero_board_dims_no_crash(self) -> None:
        comp = ComponentSpec(
            library_id="Device:R", reference="R1", value="10k",
            position=PositionSpec(x=50.0, y=40.0),
        )
        features = extract_component_features(comp, 0.0, 0.0)
        assert features[4] == 1.0       # is_fixed
        assert features[5] == 0.0       # division by zero guarded

    def test_reserved_positions_zero(self) -> None:
        comp = ComponentSpec(library_id="Device:R", reference="R1", value="10k")
        features = extract_component_features(comp, 100.0, 80.0)
        assert np.all(features[23:31] == 0.0)

    def test_library_id_hash_populated(self) -> None:
        comp = ComponentSpec(library_id="Device:R_Small", reference="R1", value="10k")
        features = extract_component_features(comp, 100.0, 80.0)
        assert features[7] > 0.0   # 'D' from "Device:"
        assert np.any(features[7:15] > 0.0)

    def test_short_library_id(self) -> None:
        """Library ID shorter than 8 chars only populates available slots."""
        comp = ComponentSpec(library_id="X", reference="R1", value="10k")
        features = extract_component_features(comp, 100.0, 80.0)
        assert features[7] > 0.0   # 'X' char
        assert features[8] == 0.0    # beyond string length


class TestExtractNetFeatures:
    """Tests for extract_net_features output structure and values."""

    def _make_comp(self, ref: str = "U1") -> ComponentSpec:
        return ComponentSpec(library_id="Dev:IC", reference=ref, value="IC")

    def test_returns_correct_shape(self) -> None:
        net = NetSpec(name="SDA", pins=["U1.1", "R1.1"])
        features = extract_net_features(net, [self._make_comp()])
        assert features.shape == (NET_FEATURE_DIM,)
        assert features.dtype == np.float32

    def test_pin_count(self) -> None:
        net = NetSpec(name="SDA", pins=["U1.1", "R1.1", "R2.1"])
        features = extract_net_features(net, [self._make_comp()])
        assert features[0] == 3.0

    def test_component_count(self) -> None:
        net = NetSpec(name="SDA", pins=["U1.1", "U1.2", "R1.1"])
        features = extract_net_features(net, [self._make_comp()])
        assert features[1] == 2.0  # U1 and R1

    def test_power_net_flag(self) -> None:
        net = NetSpec(name="GND", pins=["U1.5", "C1.2"])
        features = extract_net_features(net, [self._make_comp()])
        assert features[2] == 1.0   # is_power

    def test_vcc_power_net_flag(self) -> None:
        net = NetSpec(name="VCC", pins=["U1.10"])
        features = extract_net_features(net, [self._make_comp()])
        assert features[2] == 1.0

    def test_signal_net_not_power(self) -> None:
        net = NetSpec(name="SDA", pins=["U1.1", "R1.1"])
        features = extract_net_features(net, [self._make_comp()])
        assert features[2] == 0.0

    def test_power_net_criticality_is_1(self) -> None:
        net = NetSpec(name="GND", pins=["U1.5"])
        features = extract_net_features(net, [self._make_comp()])
        assert features[3] == 1.0   # criticality for power

    def test_high_speed_net_criticality_is_3(self) -> None:
        net = NetSpec(name="SDA", pins=["U1.1", "R1.1"])
        features = extract_net_features(net, [self._make_comp()])
        assert features[3] == 3.0   # SDA contains "SDA" keyword

    def test_default_net_criticality_is_2(self) -> None:
        net = NetSpec(name="NET_AUDIO", pins=["U1.7", "R1.2"])
        features = extract_net_features(net, [self._make_comp()])
        assert features[3] == 2.0   # default criticality

    def test_fanout_ratio(self) -> None:
        net = NetSpec(name="SDA", pins=["U1.1", "R1.1"])
        features = extract_net_features(net, [self._make_comp()])
        assert features[4] == pytest.approx(2.0 / 2.0)  # 2 pins / 2 components

    def test_single_pin_fanout_ratio(self) -> None:
        net = NetSpec(name="NC", pins=["U1.1"])
        features = extract_net_features(net, [self._make_comp()])
        assert features[4] == pytest.approx(1.0)  # 1 pin / 1 component

    def test_reserved_positions_zero(self) -> None:
        net = NetSpec(name="SDA", pins=["U1.1"])
        features = extract_net_features(net, [self._make_comp()])
        assert np.all(features[5:16] == 0.0)
