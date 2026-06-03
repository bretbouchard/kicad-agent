"""Integration tests for extended IC profiles.

Issue #8: Verify new IC profiles (RP2350B, NE5532, CD4066, CD4060, LM358),
channel-strip profile, and profile power-pin invariant.
"""

import json
from pathlib import Path

import pytest

from kicad_agent.ops.net_label_placer import (
    _load_pin_map,
    _BUILTIN_PROFILES,
    place_net_labels,
)
from tests.test_net_label_placer import _make_schematic_ir


class TestExtendedProfiles:
    """Verify new IC profiles in backplane."""

    def test_backplane_has_all_ics(self):
        """Backplane profile has all 10 ICs."""
        profile = _BUILTIN_PROFILES["backplane"]
        expected = {
            "AK4619VN", "MT8816", "W5500", "MCP4728", "P82B96DP",
            "RP2350B", "NE5532", "CD4066", "CD4060", "LM358",
        }
        assert expected.issubset(set(profile.keys()))

    def test_rp2350b_power_pins(self):
        """RP2350B has correct power mappings."""
        pins = _BUILTIN_PROFILES["backplane"]["RP2350B"]
        assert pins["VDD"] == "VCC_3V3"
        assert pins["GND"] == "GND"
        assert pins["QSPI_SCLK"] == "QSPI_SCLK"
        assert pins["USB_DP"] == "USB_DP"
        assert pins["ADC0"] is None  # Signal-dependent

    def test_ne5532_backplane_power(self):
        """NE5532 in backplane uses ±12V."""
        pins = _BUILTIN_PROFILES["backplane"]["NE5532"]
        assert pins["VCC"] == "VCC_12V"
        assert pins["VEE"] == "VCC_-12V"

    def test_cd4066_power(self):
        """CD4066 has 5V power."""
        pins = _BUILTIN_PROFILES["backplane"]["CD4066"]
        assert pins["VDD"] == "VCC_5V"
        assert pins["VSS"] == "GND"

    def test_cd4060_power(self):
        """CD4060 has 5V power."""
        pins = _BUILTIN_PROFILES["backplane"]["CD4060"]
        assert pins["VDD"] == "VCC_5V"
        assert pins["VSS"] == "GND"

    def test_lm358_power(self):
        """LM358 has 5V power in backplane."""
        pins = _BUILTIN_PROFILES["backplane"]["LM358"]
        assert pins["VCC"] == "VCC_5V"
        assert pins["GND"] == "GND"


class TestChannelStripProfile:
    """Verify channel-strip profile uses ±15V audio rails."""

    def test_channel_strip_exists(self):
        """'channel-strip' is a valid profile."""
        assert "channel-strip" in _BUILTIN_PROFILES

    def test_ne5532_channel_strip_15v(self):
        """NE5532 in channel-strip uses ±15V."""
        pins = _BUILTIN_PROFILES["channel-strip"]["NE5532"]
        assert pins["VCC"] == "VCC_15V"
        assert pins["VEE"] == "VCC_-15V"

    def test_different_power_domains(self):
        """Same IC maps to different nets per profile."""
        bp_ne = _BUILTIN_PROFILES["backplane"]["NE5532"]
        cs_ne = _BUILTIN_PROFILES["channel-strip"]["NE5532"]
        assert bp_ne["VCC"] != cs_ne["VCC"]

    def test_that4301_profile(self):
        """THAT4301 in channel-strip profile."""
        pins = _BUILTIN_PROFILES["channel-strip"]["THAT4301"]
        assert pins["VCC"] == "VCC_15V"
        assert pins["VEE"] == "VCC_-15V"

    def test_that2180_profile(self):
        """THAT2180 in channel-strip profile."""
        pins = _BUILTIN_PROFILES["channel-strip"]["THAT2180"]
        assert pins["VCC"] == "VCC_15V"


class TestAutoMerge:
    """Verify auto mode merges all profiles."""

    def test_auto_merges_all(self):
        """Auto mode has ICs from both profiles."""
        mapping = _load_pin_map("auto", Path("."))
        # From backplane
        assert "RP2350B" in mapping
        # From channel-strip
        assert "THAT4301" in mapping

    def test_auto_last_profile_wins_on_conflict(self):
        """When IC exists in both profiles, last merged profile wins."""
        # "auto" merges in dict iteration order — channel-strip merges after backplane
        # so channel-strip's NE5532 (±15V) overwrites backplane's (±12V)
        mapping = _load_pin_map("auto", Path("."))
        assert mapping["NE5532"]["VCC"] == "VCC_15V"  # channel-strip wins


class TestPowerPinInvariant:
    """Every power pin across all profiles must be non-None."""

    _POWER_PIN_NAMES = frozenset({
        "VDD", "VCC", "VEE", "GND", "VSS", "AGND", "DGND",
        "TVDD", "AVDD", "DVDD", "DVDDH", "AVDRV",
    })

    def test_all_power_pins_non_none(self):
        """Power pins are never mapped to None."""
        violations = []
        for profile_name, profile in _BUILTIN_PROFILES.items():
            for ic_name, pins in profile.items():
                for pin_name, net in pins.items():
                    if pin_name in self._POWER_PIN_NAMES and net is None:
                        violations.append(f"{profile_name}/{ic_name}.{pin_name}")
        assert not violations, f"Power pins mapped to None: {violations}"


class TestJsonOverride:

    def test_json_override_builtin(self, tmp_path):
        """Custom JSON overrides built-in mapping for same IC."""
        custom = {"AK4619VN": {"TVDD": "CUSTOM_3V3"}}
        json_path = tmp_path / "custom.json"
        json_path.write_text(json.dumps(custom))

        mapping = _load_pin_map(str(json_path), Path("."))
        assert mapping["AK4619VN"]["TVDD"] == "CUSTOM_3V3"
        # Only the custom pins, not the full built-in set
        assert "VSS1" not in mapping["AK4619VN"]

    def test_new_ic_via_json(self, tmp_path):
        """Custom JSON adds ICs not in any built-in profile."""
        custom = {"MCU_CUSTOM": {"VDD": "VCC_3V3", "GPIO0": None}}
        json_path = tmp_path / "custom.json"
        json_path.write_text(json.dumps(custom))

        mapping = _load_pin_map(str(json_path), Path("."))
        assert "MCU_CUSTOM" in mapping
        assert mapping["MCU_CUSTOM"]["VDD"] == "VCC_3V3"


class TestProfileIntegration:

    def test_rp2350b_label_placement(self):
        """RP2350B QSPI pins get labels when wires exist."""
        ir, path = _make_schematic_ir(
            wires=[(50.0, 50.0, 60.0, 50.0)],
            symbols=[("MCU", "RP2350B", "U1", 0, 0)],
        )
        ir.get_pin_positions = lambda: [
            {"reference": "U1", "pin_name": "QSPI_SCLK", "x": 50.0, "y": 50.0},
        ]

        result = place_net_labels(ir, path, pin_map="backplane")
        assert result["labels_placed"] == 1
        assert any(d["net_name"] == "QSPI_SCLK" for d in result["details"])
