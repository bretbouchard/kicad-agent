"""Tests for ComponentTypeClassifier (Phase 89, Task 0)."""

import pytest

from kicad_agent.analysis.types import NetClassification
from kicad_agent.validation.gates.component_classifier import (
    ComponentRole,
    ComponentTypeClassifier,
)


@pytest.fixture
def classifier() -> ComponentTypeClassifier:
    return ComponentTypeClassifier()


class TestCapacitorClassification:
    """Capacitor classification based on package size and net intent."""

    def test_decoupling_cap_small_package_on_power_net(self, classifier: ComponentTypeClassifier) -> None:
        assert classifier.classify(
            lib_id="Device:C_Small",
            package_size="0402",
            connected_net_names=["VCC3V3"],
            net_classifications={"VCC3V3": NetClassification.POWER},
        ) == ComponentRole.DECOUPLING_CAP

    def test_decoupling_cap_0603_on_ground_net(self, classifier: ComponentTypeClassifier) -> None:
        assert classifier.classify(
            lib_id="Device:C",
            package_size="0603",
            connected_net_names=["GND"],
            net_classifications={"GND": NetClassification.GROUND},
        ) == ComponentRole.DECOUPLING_CAP

    def test_bulk_cap_large_package_on_power_net(self, classifier: ComponentTypeClassifier) -> None:
        assert classifier.classify(
            lib_id="Device:C_Polarized",
            package_size="1206",
            connected_net_names=["VCC5V"],
            net_classifications={"VCC5V": NetClassification.POWER},
        ) == ComponentRole.BULK_CAP

    def test_bulk_cap_electrolytic_on_power_net(self, classifier: ComponentTypeClassifier) -> None:
        assert classifier.classify(
            lib_id="Device:CP",
            package_size="C-electrolytic",
            connected_net_names=["VCC"],
            net_classifications={"VCC": NetClassification.POWER},
        ) == ComponentRole.BULK_CAP

    def test_generic_cap_on_signal_net(self, classifier: ComponentTypeClassifier) -> None:
        assert classifier.classify(
            lib_id="Device:C",
            package_size="0805",
            connected_net_names=["AUDIO_IN"],
            net_classifications={"AUDIO_IN": NetClassification.SIGNAL},
        ) == ComponentRole.CAPACITOR

    def test_generic_cap_no_net_info(self, classifier: ComponentTypeClassifier) -> None:
        assert classifier.classify(
            lib_id="Device:C",
            package_size="0402",
            connected_net_names=[],
            net_classifications={},
        ) == ComponentRole.CAPACITOR


class TestRegulatorClassification:
    """IC classification with known regulator patterns."""

    def test_lm7805_power_regulator(self, classifier: ComponentTypeClassifier) -> None:
        assert classifier.classify(
            lib_id="Regulator_Linear:LM7805_TO220",
            package_size="TO-220",
            connected_net_names=["VIN", "VOUT"],
            net_classifications={"VIN": NetClassification.POWER, "VOUT": NetClassification.POWER},
        ) == ComponentRole.POWER_REGULATOR

    def test_ams1117_power_regulator(self, classifier: ComponentTypeClassifier) -> None:
        assert classifier.classify(
            lib_id="Regulator_Linear:AMS1117-3.3_SOT-223",
            package_size="SOT-223",
            connected_net_names=["VCC3V3"],
            net_classifications={"VCC3V3": NetClassification.POWER},
        ) == ComponentRole.POWER_REGULATOR

    def test_generic_ic_not_regulator(self, classifier: ComponentTypeClassifier) -> None:
        assert classifier.classify(
            lib_id="Amplifier_Operational:NE5532_SO-8",
            package_size="SO-8",
            connected_net_names=["AUDIO_IN"],
            net_classifications={"AUDIO_IN": NetClassification.ANALOG},
        ) == ComponentRole.IC


class TestOtherComponentTypes:
    """Resistor, connector, inductor, diode, misc classification."""

    def test_resistor(self, classifier: ComponentTypeClassifier) -> None:
        assert classifier.classify(
            lib_id="Device:R",
            package_size="0402",
            connected_net_names=["SIG"],
            net_classifications={"SIG": NetClassification.SIGNAL},
        ) == ComponentRole.RESISTOR

    def test_connector(self, classifier: ComponentTypeClassifier) -> None:
        assert classifier.classify(
            lib_id="Connector:USB_C_Receptacle_USB2.0",
            package_size="USB-C",
            connected_net_names=[],
            net_classifications={},
        ) == ComponentRole.CONNECTOR

    def test_inductor(self, classifier: ComponentTypeClassifier) -> None:
        assert classifier.classify(
            lib_id="Device:L",
            package_size="0805",
            connected_net_names=[],
            net_classifications={},
        ) == ComponentRole.INDUCTOR

    def test_diode(self, classifier: ComponentTypeClassifier) -> None:
        assert classifier.classify(
            lib_id="Device:D",
            package_size="SOD-123",
            connected_net_names=[],
            net_classifications={},
        ) == ComponentRole.DIODE

    def test_transistor(self, classifier: ComponentTypeClassifier) -> None:
        assert classifier.classify(
            lib_id="Device:Q_NPN_BEC",
            package_size="SOT-23",
            connected_net_names=[],
            net_classifications={},
        ) == ComponentRole.TRANSISTOR

    def test_misc_unknown(self, classifier: ComponentTypeClassifier) -> None:
        # A lib_id without colon and not matching any known pattern -> misc
        assert classifier.classify(
            lib_id="unknown_part",
            package_size=None,
            connected_net_names=[],
            net_classifications={},
        ) == ComponentRole.MISC


class TestIsThermal:
    """is_thermal static method checks."""

    def test_power_regulator_is_thermal(self) -> None:
        assert ComponentTypeClassifier.is_thermal(ComponentRole.POWER_REGULATOR) is True

    def test_thermal_ic_is_thermal(self) -> None:
        assert ComponentTypeClassifier.is_thermal(ComponentRole.THERMAL_IC) is True

    def test_resistor_not_thermal(self) -> None:
        assert ComponentTypeClassifier.is_thermal(ComponentRole.RESISTOR) is False

    def test_ic_not_thermal(self) -> None:
        assert ComponentTypeClassifier.is_thermal(ComponentRole.IC) is False
