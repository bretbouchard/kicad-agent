"""Integration tests for extended IC profiles and custom JSON loading.

Plan 71-02: Validates that all extended IC profiles (RP2350B, NE5532, CD4066,
CD4060, LM358) are present and correct, that the channel-strip profile uses
different power domains, and that custom JSON overrides work.
"""

import json
from pathlib import Path

import pytest

from kicad_agent.ops.net_label_placer import (
    _load_pin_map,
    _BUILTIN_PROFILES,
)


class TestBackplaneProfileCompleteness:

    def test_all_extended_ics_present(self):
        """Backplane profile contains all 10 ICs."""
        profile = _BUILTIN_PROFILES["backplane"]
        expected = [
            "AK4619VN", "MT8816", "W5500", "MCP4728", "P82B96DP",
            "RP2350B", "NE5532", "CD4066", "CD4060", "LM358",
        ]
        for ic in expected:
            assert ic in profile, f"Missing '{ic}' in backplane profile"

    def test_rp2350b_has_qspi_usb_swd_pins(self):
        """RP2350B profile has QSPI, USB, and SWD debug pins."""
        rp = _BUILTIN_PROFILES["backplane"]["RP2350B"]
        assert rp["VDD"] == "VCC_3V3"
        assert rp["USB_VBUS"] == "VBUS"
        assert rp["QSPI_SCLK"] == "QSPI_SCLK"
        assert rp["USB_DP"] == "USB_DP"
        assert rp["SWCLK"] == "SWCLK"
        # GPIO pins should be signal-dependent (None)
        assert rp["GPIO0"] is None

    def test_ne5532_has_dual_opamp_pins(self):
        """NE5532 profile has correct power rails and signal pins."""
        ne = _BUILTIN_PROFILES["backplane"]["NE5532"]
        assert ne["VCC"] == "VCC_12V"
        assert ne["VEE"] == "VCC_-12V"
        assert "1OUT" in ne
        assert "2IN+" in ne

    def test_cd4066_has_quad_switch_pins(self):
        """CD4066 profile has all four switch sections."""
        cd = _BUILTIN_PROFILES["backplane"]["CD4066"]
        assert cd["VDD"] == "VCC_5V"
        assert cd["VSS"] == "GND"
        for section in ("1", "2", "3", "4"):
            assert f"{section}A" in cd
            assert f"{section}B" in cd
            assert f"{section}C" in cd

    def test_cd4060_has_counter_output_pins(self):
        """CD4060 profile has oscillator and counter output pins."""
        cd = _BUILTIN_PROFILES["backplane"]["CD4060"]
        assert cd["VDD"] == "VCC_5V"
        assert cd["RESET"] is None
        for q in range(3, 15):
            assert f"Q{q}" in cd

    def test_lm358_has_dual_opamp_pins(self):
        """LM358 profile has correct power and dual op-amp pins."""
        lm = _BUILTIN_PROFILES["backplane"]["LM358"]
        assert lm["VCC"] == "VCC_5V"
        assert lm["GND"] == "GND"
        assert "1OUT" in lm
        assert "2IN+" in lm


class TestChannelStripProfile:

    def test_channel_strip_profile_exists(self):
        """'channel-strip' is a valid built-in profile."""
        assert "channel-strip" in _BUILTIN_PROFILES

    def test_ne5532_uses_15v_in_channel_strip(self):
        """NE5532 in channel-strip uses +/-15V, not +/-12V."""
        cs = _BUILTIN_PROFILES["channel-strip"]["NE5532"]
        assert cs["VCC"] == "VCC_15V"
        assert cs["VEE"] == "VCC_-15V"

    def test_channel_strip_has_that4301(self):
        """channel-strip profile includes THAT4301 VCA."""
        assert "THAT4301" in _BUILTIN_PROFILES["channel-strip"]

    def test_channel_strip_has_that2180(self):
        """channel-strip profile includes THAT2180 VCA core."""
        assert "THAT2180" in _BUILTIN_PROFILES["channel-strip"]

    def test_lm358_uses_agnd_in_channel_strip(self):
        """LM358 in channel-strip uses AGND instead of GND."""
        cs = _BUILTIN_PROFILES["channel-strip"]["LM358"]
        assert cs["GND"] == "AGND"
        assert cs["VCC"] == "VCC_15V"


class TestProfilePowerDomainDifferences:

    def test_ne5532_different_power_per_profile(self):
        """Same IC (NE5532) maps to different power nets per profile."""
        bp = _BUILTIN_PROFILES["backplane"]["NE5532"]
        cs = _BUILTIN_PROFILES["channel-strip"]["NE5532"]

        # Backplane: +/-12V, Channel-strip: +/-15V
        assert bp["VCC"] != cs["VCC"]
        assert bp["VCC"] == "VCC_12V"
        assert cs["VCC"] == "VCC_15V"

    def test_cd4066_different_ground_per_profile(self):
        """CD4066 uses different ground nets per profile."""
        bp = _BUILTIN_PROFILES["backplane"]["CD4066"]
        cs = _BUILTIN_PROFILES["channel-strip"]["CD4066"]

        assert bp["VSS"] == "GND"
        assert cs["VSS"] == "AGND"

    def test_lm358_different_power_per_profile(self):
        """LM358 uses different power nets per profile."""
        bp = _BUILTIN_PROFILES["backplane"]["LM358"]
        cs = _BUILTIN_PROFILES["channel-strip"]["LM358"]

        assert bp["VCC"] == "VCC_5V"
        assert cs["VCC"] == "VCC_15V"


class TestAutoMergesAllProfiles:

    def test_auto_has_rp2350b(self):
        """Auto mode includes RP2350B from backplane."""
        mapping = _load_pin_map("auto", Path("."))
        assert "RP2350B" in mapping

    def test_auto_has_that4301(self):
        """Auto mode includes THAT4301 from channel-strip."""
        mapping = _load_pin_map("auto", Path("."))
        assert "THAT4301" in mapping

    def test_auto_has_all_ics(self):
        """Auto mode merges all ICs from all profiles."""
        mapping = _load_pin_map("auto", Path("."))
        all_ics = set()
        for profile in _BUILTIN_PROFILES.values():
            all_ics.update(profile.keys())
        for ic in all_ics:
            assert ic in mapping, f"Auto merge missing '{ic}'"


class TestJsonOverrideBuiltin:

    def test_json_override_same_ic(self, tmp_path):
        """Custom JSON overrides built-in mapping for same IC name."""
        custom = {"NE5532": {"VCC": "VCC_9V", "VEE": "GND"}}
        json_path = tmp_path / "override.json"
        json_path.write_text(json.dumps(custom))

        mapping = _load_pin_map(str(json_path), Path("."))

        # Should use JSON values, not built-in
        assert mapping["NE5532"]["VCC"] == "VCC_9V"
        assert mapping["NE5532"]["VEE"] == "GND"
        # Should NOT have the full built-in pin list
        assert "1OUT" not in mapping["NE5532"]


class TestPowerPinNeverNone:

    def test_power_pins_never_none_in_all_profiles(self):
        """Every IC profile has non-None values for power-related pins."""
        power_patterns = ("VDD", "VCC", "VEE", "GND", "VSS",
                          "TVDD", "AVDD", "DVDD", "DVDDH", "AVDRV")

        for profile_name, profile in _BUILTIN_PROFILES.items():
            for ic_name, pins in profile.items():
                for pin_name, net in pins.items():
                    if pin_name in power_patterns:
                        assert net is not None, (
                            f"{profile_name}/{ic_name}.{pin_name} "
                            f"mapped to None"
                        )

    def test_ground_pins_always_have_ground_net(self):
        """GND and VSS pins always map to a ground net."""
        for profile_name, profile in _BUILTIN_PROFILES.items():
            for ic_name, pins in profile.items():
                for pin_name in ("GND", "VSS"):
                    if pin_name in pins:
                        net = pins[pin_name]
                        assert net is not None, (
                            f"{profile_name}/{ic_name}.{pin_name} is None"
                        )
                        assert "GND" in net.upper() or "AGND" in net.upper(), (
                            f"{profile_name}/{ic_name}.{pin_name} = "
                            f"'{net}' doesn't look like ground"
                        )
