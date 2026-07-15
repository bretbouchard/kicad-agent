"""Tests for bundled vendor DRC profile files and the drc_profiles package (DRC-02, DRC-03, DRC-06, DRC-07, DRC-08)."""
import pytest

from volta.manufacturing.drc_profiles import (
    VendorDrcProfileInfo,
    get_drc_profile_path,
    list_drc_profiles,
)

_PROFILES_DIR = "src/volta/manufacturing/drc_profiles"

# The 9 expected vendor files.
_EXPECTED_VENDORS = {
    "pcbway",
    "jlcpcb",
    "aisler_2layer",
    "aisler_4layer",
    "aisler_6layer",
    "aisler_8layer",
    "oshpark",
    "advanced_circuits",
    "generic",
}

# Required attribution header lines (DRC-06).
_REQUIRED_HEADERS = ("# Source:", "# License:", "# Last verified:", "# Vendor:", "# Capabilities:")


def _read_dru(vendor: str) -> str:
    return get_drc_profile_path(vendor).read_text(encoding="utf-8")


class TestDruFileAttribution:
    """DRC-06: every .kicad_dru file has the required attribution headers."""

    def test_all_dru_files_have_attribution(self) -> None:
        for vendor in _EXPECTED_VENDORS:
            content = _read_dru(vendor)
            for header in _REQUIRED_HEADERS:
                assert header in content, (
                    f"{vendor}.kicad_dru missing header {header!r}"
                )

    def test_all_dru_files_have_version_1(self) -> None:
        for vendor in _EXPECTED_VENDORS:
            content = _read_dru(vendor)
            assert "(version 1)" in content, f"{vendor}.kicad_dru missing (version 1)"


class TestAnnularRingValues:
    """DRC-07 + AISLER hard limit: verify the load-bearing numeric values."""

    def test_pcbway_annular_ring_015(self) -> None:
        # DRC-07: PCBWay annular is 0.15mm, not the stale 0.25mm/0.1mm.
        content = _read_dru("pcbway")
        assert "annular_width (min 0.15mm)" in content

    def test_jlcpcb_annular_ring_015(self) -> None:
        # DRC-07: JLCPCB annular is 0.15mm.
        content = _read_dru("jlcpcb")
        assert "annular_width (min 0.15mm)" in content

    def test_aisler_annular_ring_02(self) -> None:
        # AISLER hard limit is 0.2mm (larger than JLC/PCBWay).
        content = _read_dru("aisler_2layer")
        assert "annular_width (min 0.2mm)" in content


class TestProfileRegistry:
    """DRC-08: list_drc_profiles + get_drc_profile_path."""

    def test_list_drc_profiles_returns_9(self) -> None:
        profiles = list_drc_profiles()
        assert len(profiles) == 9
        vendors = {p.vendor for p in profiles}
        assert vendors == _EXPECTED_VENDORS

    def test_all_profile_entries_have_required_fields(self) -> None:
        required = {
            "vendor", "display_name", "drc_rules_path",
            "min_trace_width_mm", "min_clearance_mm", "min_drill_mm",
            "min_annular_ring_mm", "min_via_diameter_mm",
            "supports_blind_vias", "supports_castellated",
            "source", "last_verified",
        }
        for p in list_drc_profiles():
            fields = set(p.__dataclass_fields__.keys())
            assert required.issubset(fields), (
                f"{p.vendor} missing fields: {required - fields}"
            )

    def test_vendor_drc_profile_info_is_frozen(self) -> None:
        p = list_drc_profiles()[0]
        with pytest.raises((AttributeError, Exception)):
            p.vendor = "mutated"  # type: ignore[misc]

    def test_get_drc_profile_path_returns_existing_file(self) -> None:
        for vendor in _EXPECTED_VENDORS:
            path = get_drc_profile_path(vendor)
            assert path.is_file(), f"{vendor} path does not exist: {path}"
            assert path.name == f"{vendor}.kicad_dru"

    def test_profile_numeric_values_match_files(self) -> None:
        # Spot-check that the registry metadata matches the DRU file values
        # (single source of truth). PCBWay: track 0.127, annular 0.15.
        by_vendor = {p.vendor: p for p in list_drc_profiles()}
        pcbway = by_vendor["pcbway"]
        assert pcbway.min_trace_width_mm == pytest.approx(0.127)
        assert pcbway.min_annular_ring_mm == pytest.approx(0.15)
        assert pcbway.min_drill_mm == pytest.approx(0.2)

        aisler = by_vendor["aisler_2layer"]
        assert aisler.min_annular_ring_mm == pytest.approx(0.2)

        generic = by_vendor["generic"]
        assert generic.min_drill_mm == pytest.approx(0.4)
        assert generic.min_clearance_mm == pytest.approx(0.2)


class TestPathTraversalDefense:
    """Threat model scenario 1: vendor name validation blocks path traversal."""

    def test_get_drc_profile_path_rejects_traversal(self) -> None:
        with pytest.raises(ValueError, match="must match"):
            get_drc_profile_path("../../etc/passwd")

    def test_get_drc_profile_path_rejects_slashes(self) -> None:
        with pytest.raises(ValueError, match="must match"):
            get_drc_profile_path("foo/bar")

    def test_get_drc_profile_path_rejects_dots(self) -> None:
        with pytest.raises(ValueError, match="must match"):
            get_drc_profile_path("foo.bar")

    def test_get_drc_profile_path_rejects_uppercase(self) -> None:
        with pytest.raises(ValueError, match="must match"):
            get_drc_profile_path("PCBWay")

    def test_get_drc_profile_path_unknown_vendor_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown vendor"):
            get_drc_profile_path("nonexistent")
