"""Tests for component search MCP tools.

Tests all 4 MCP tools with mocked EasyEdaClient (no network calls in CI).
Covers: normal flows, validation errors, empty results, not found, pagination.

Requirements covered:
  MCP-01: search_components tool with keyword, limit, part_type filtering.
  MCP-02: get_component_details tool with LCSC ID validation.
  MCP-03: search_and_detail combined tool.
  MCP-04: get_component_suggestions lightweight tool.
  MCP-05: Input validation (keyword, lcsc_id, limit bounds).
  MCP-06: Pin type mapping (EasyEDA int → KiCad electrical type string).
  MCP-07: Part type mapping (user "basic"/"extended" → API "base"/"expand").
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from kicad_agent.crawler.easyeda_api import (
    EasyEdaComponentData,
    EasyEdaFootprintPad,
    EasyEdaPin,
    EasyEdaClient,
    JlcpcbComponent,
)
from kicad_agent.mcp.tools import (
    ValidationError,
    get_component_details,
    get_component_suggestions,
    search_and_detail,
    search_components,
)


# ======================================================================
# Fixtures
# ======================================================================


def _make_component(**overrides: Any) -> JlcpcbComponent:
    """Create a JlcpcbComponent with sensible defaults."""
    defaults = dict(
        lcsc="C83700",
        name="STM32F103C8T6",
        brand="STMicroelectronics",
        package="LQFP-48",
        category="MCU",
        stock=50000,
        part_type="Basic",
        price=1.50,
        datasheet="https://datasheet.lcsc.com/C83700.pdf",
        attributes=({"name": "Flash", "value": "64KB"},),
    )
    defaults.update(overrides)
    return JlcpcbComponent(**defaults)


def _make_pin(**overrides: Any) -> EasyEdaPin:
    """Create an EasyEdaPin with sensible defaults."""
    defaults = dict(
        pin_number="1",
        pin_name="VCC",
        pos_x=0.0,
        pos_y=5.08,
        rotation=0,
        pin_type=4,  # power
    )
    defaults.update(overrides)
    return EasyEdaPin(**defaults)


def _make_pad(**overrides: Any) -> EasyEdaFootprintPad:
    """Create an EasyEdaFootprintPad with sensible defaults."""
    defaults = dict(
        pad_number="1",
        pos_x=0.0,
        pos_y=0.0,
        width=1.5,
        height=0.5,
        layer=1,
        shape="RECT",
    )
    defaults.update(overrides)
    return EasyEdaFootprintPad(**defaults)


def _make_component_data(**overrides: Any) -> EasyEdaComponentData:
    """Create an EasyEdaComponentData with sensible defaults."""
    pins = overrides.pop("pins", (_make_pin(),))
    pads = overrides.pop("pads", (_make_pad(),))
    defaults = dict(
        lcsc="C83700",
        title="STM32F103C8T6",
        package="LQFP-48",
        pins=pins,
        pads=pads,
        data_str="",
    )
    defaults.update(overrides)
    return EasyEdaComponentData(**defaults)


def _mock_client(
    search_result: tuple | None = None,
    cad_data: EasyEdaComponentData | None = None,
) -> MagicMock:
    """Create a mock EasyEdaClient."""
    client = MagicMock(spec=EasyEdaClient)
    client.search_jlcpcb.return_value = search_result or ([], 0)
    client.get_component_cad_data.return_value = cad_data
    return client


# ======================================================================
# search_components
# ======================================================================


class TestSearchComponents:
    def test_basic_search(self) -> None:
        comp = _make_component()
        client = _mock_client(search_result=([comp], 1))
        result = search_components(client, "STM32")
        assert result["total"] == 1
        assert len(result["results"]) == 1
        assert result["results"][0]["lcsc"] == "C83700"
        assert result["results"][0]["name"] == "STM32F103C8T6"
        assert result["results"][0]["package"] == "LQFP-48"
        assert result["results"][0]["stock"] == 50000
        assert result["results"][0]["price"] == 1.50
        client.search_jlcpcb.assert_called_once_with(
            keyword="STM32", page=1, page_size=10, part_type=None,
        )

    def test_part_type_mapping(self) -> None:
        """User-facing 'basic' maps to API 'base'."""
        client = _mock_client(search_result=([], 0))
        search_components(client, "cap", part_type="basic")
        client.search_jlcpcb.assert_called_once_with(
            keyword="cap", page=1, page_size=10, part_type="base",
        )

    def test_part_type_extended(self) -> None:
        """User-facing 'extended' maps to API 'expand'."""
        client = _mock_client(search_result=([], 0))
        search_components(client, "res", part_type="extended")
        client.search_jlcpcb.assert_called_once_with(
            keyword="res", page=1, page_size=10, part_type="expand",
        )

    def test_empty_results(self) -> None:
        client = _mock_client(search_result=([], 0))
        result = search_components(client, "xyznonexistent")
        assert result["total"] == 0
        assert result["results"] == []

    def test_limit_capped_to_page_size(self) -> None:
        """Limit <= 25 uses single page."""
        client = _mock_client(search_result=([_make_component()], 100))
        result = search_components(client, "STM32", limit=5)
        assert len(result["results"]) == 1
        client.search_jlcpcb.assert_called_once_with(
            keyword="STM32", page=1, page_size=5, part_type=None,
        )

    def test_pagination_for_large_limit(self) -> None:
        """Limit > 25 triggers additional page fetches."""
        page1 = [_make_component(lcsc=f"C{i}") for i in range(25)]
        page2 = [_make_component(lcsc=f"C{i+25}") for i in range(10)]
        client = _mock_client(search_result=(page1, 35))
        client.search_jlcpcb.side_effect = [(page1, 35), (page2, 35)]
        result = search_components(client, "cap", limit=35)
        assert len(result["results"]) == 35

    def test_attributes_included(self) -> None:
        comp = _make_component(attributes=({"name": "Flash", "value": "64KB"},))
        client = _mock_client(search_result=([comp], 1))
        result = search_components(client, "STM32")
        assert result["results"][0]["attributes"] == [{"name": "Flash", "value": "64KB"}]


# ======================================================================
# get_component_details
# ======================================================================


class TestGetComponentDetails:
    def test_basic_details(self) -> None:
        data = _make_component_data()
        client = _mock_client(cad_data=data)
        result = get_component_details(client, "C83700")
        assert result["lcsc"] == "C83700"
        assert result["title"] == "STM32F103C8T6"
        assert result["package"] == "LQFP-48"
        assert len(result["pins"]) == 1
        assert len(result["pads"]) == 1

    def test_pin_type_mapping(self) -> None:
        """EasyEDA pin_type int → KiCad electrical type string."""
        pin = _make_pin(pin_type=4)  # power → power_in
        data = _make_component_data(pins=(pin,))
        client = _mock_client(cad_data=data)
        result = get_component_details(client, "C83700")
        assert result["pins"][0]["type"] == "power_in"

    def test_all_pin_type_mappings(self) -> None:
        """Verify the complete pin type mapping table."""
        from kicad_agent.mcp.tools import _PIN_TYPE_MAP
        assert _PIN_TYPE_MAP == {
            0: "passive",
            1: "input",
            2: "output",
            3: "bidirectional",
            4: "power_in",
        }

    def test_unknown_pin_type_defaults_to_passive(self) -> None:
        pin = _make_pin(pin_type=99)  # Unknown type
        data = _make_component_data(pins=(pin,))
        client = _mock_client(cad_data=data)
        result = get_component_details(client, "C83700")
        assert result["pins"][0]["type"] == "passive"

    def test_multiple_pins_and_pads(self) -> None:
        pins = (
            _make_pin(pin_number="1", pin_name="VCC", pin_type=4),
            _make_pin(pin_number="2", pin_name="GND", pin_type=4),
            _make_pin(pin_number="3", pin_name="DOUT", pin_type=2),
            _make_pin(pin_number="4", pin_name="DIN", pin_type=1),
            _make_pin(pin_number="5", pin_name="CLK", pin_type=0),
        )
        pads = tuple(_make_pad(pad_number=str(i)) for i in range(1, 4))
        data = _make_component_data(pins=pins, pads=pads)
        client = _mock_client(cad_data=data)
        result = get_component_details(client, "C83700")
        assert len(result["pins"]) == 5
        assert result["pins"][0]["type"] == "power_in"
        assert result["pins"][2]["type"] == "output"
        assert result["pins"][3]["type"] == "input"
        assert result["pins"][4]["type"] == "passive"
        assert len(result["pads"]) == 3

    def test_not_found(self) -> None:
        client = _mock_client(cad_data=None)
        with pytest.raises(ValueError, match="not found"):
            get_component_details(client, "C99999")

    def test_pad_format(self) -> None:
        pad = _make_pad()
        data = _make_component_data(pads=(pad,))
        client = _mock_client(cad_data=data)
        result = get_component_details(client, "C83700")
        assert result["pads"][0] == {
            "number": "1",
            "x": 0.0,
            "y": 0.0,
            "width": 1.5,
            "height": 0.5,
            "layer": 1,
            "shape": "RECT",
        }


# ======================================================================
# search_and_detail
# ======================================================================


class TestSearchAndDetail:
    def test_combined_search(self) -> None:
        comp1 = _make_component(lcsc="C111")
        comp2 = _make_component(lcsc="C222", name="STM32F407")
        data1 = _make_component_data(lcsc="C111", pins=(_make_pin(pin_type=1),))
        data2 = _make_component_data(lcsc="C222", pins=(_make_pin(pin_type=2),))

        client = _mock_client(search_result=([comp1, comp2], 2))
        client.get_component_cad_data.side_effect = [data1, data2]

        result = search_and_detail(client, "STM32", detail_limit=2)
        assert result["total"] == 2
        assert len(result["results"]) == 2
        # First result has pins from CAD data
        assert "pins" in result["results"][0]
        assert result["results"][0]["pins"][0]["type"] == "input"
        assert result["results"][1]["pins"][0]["type"] == "output"

    def test_detail_limit_caps_at_search_limit(self) -> None:
        comp = _make_component()
        client = _mock_client(search_result=([comp], 1))
        # detail_limit > search_limit → clamped
        result = search_and_detail(client, "STM32", detail_limit=10, search_limit=1)
        assert len(result["results"]) == 1

    def test_cad_data_failure_graceful(self) -> None:
        """If CAD data fetch fails for one result, still returns basic info."""
        comp1 = _make_component(lcsc="C111")
        comp2 = _make_component(lcsc="C222")
        data1 = _make_component_data(lcsc="C111")

        client = _mock_client(search_result=([comp1, comp2], 2))
        client.get_component_cad_data.side_effect = [data1, None]

        result = search_and_detail(client, "STM32", detail_limit=2)
        assert len(result["results"]) == 2
        # First has pins, second doesn't
        assert "pins" in result["results"][0]
        assert "pins" not in result["results"][1]


# ======================================================================
# get_component_suggestions
# ======================================================================


class TestGetComponentSuggestions:
    def test_basic_suggestions(self) -> None:
        comp = _make_component()
        client = _mock_client(search_result=([comp], 1))
        result = get_component_suggestions(client, "STM32")
        assert result["total"] == 1
        assert len(result["suggestions"]) == 1
        s = result["suggestions"][0]
        assert s["lcsc"] == "C83700"
        assert s["name"] == "STM32F103C8T6"
        assert s["package"] == "LQFP-48"
        assert s["stock"] == 50000
        # Lightweight format — no price, no datasheet
        assert "price" not in s
        assert "datasheet" not in s

    def test_empty_suggestions(self) -> None:
        client = _mock_client(search_result=([], 0))
        result = get_component_suggestions(client, "xyznonexistent")
        assert result["suggestions"] == []
        assert result["total"] == 0

    def test_suggestions_respects_limit(self) -> None:
        comps = [_make_component(lcsc=f"C{i}") for i in range(10)]
        client = _mock_client(search_result=(comps, 100))
        result = get_component_suggestions(client, "cap", limit=3)
        assert len(result["suggestions"]) == 3


# ======================================================================
# Input validation
# ======================================================================


class TestInputValidation:
    def test_empty_keyword(self) -> None:
        client = _mock_client()
        with pytest.raises(ValidationError, match="empty"):
            search_components(client, "")

    def test_whitespace_only_keyword(self) -> None:
        client = _mock_client()
        with pytest.raises(ValidationError, match="empty"):
            search_components(client, "   ")

    def test_keyword_too_long(self) -> None:
        client = _mock_client()
        with pytest.raises(ValidationError, match="200"):
            search_components(client, "x" * 201)

    def test_keyword_trimmed(self) -> None:
        """Leading/trailing whitespace is stripped."""
        comp = _make_component()
        client = _mock_client(search_result=([comp], 1))
        search_components(client, "  STM32  ")
        client.search_jlcpcb.assert_called_once_with(
            keyword="STM32", page=1, page_size=10, part_type=None,
        )

    def test_invalid_lcsc_id_format(self) -> None:
        client = _mock_client()
        with pytest.raises(ValidationError, match="invalid LCSC"):
            get_component_details(client, "ABC123")

    def test_invalid_lcsc_id_with_special_chars(self) -> None:
        client = _mock_client()
        with pytest.raises(ValidationError, match="invalid LCSC"):
            get_component_details(client, "C83700; rm -rf /")

    def test_valid_lcsc_id(self) -> None:
        data = _make_component_data()
        client = _mock_client(cad_data=data)
        result = get_component_details(client, "C83700")
        assert result["lcsc"] == "C83700"

    def test_limit_below_minimum(self) -> None:
        client = _mock_client()
        with pytest.raises(ValidationError, match="between 1 and 50"):
            search_components(client, "STM32", limit=0)

    def test_limit_above_maximum(self) -> None:
        client = _mock_client()
        with pytest.raises(ValidationError, match="between 1 and 50"):
            search_components(client, "STM32", limit=51)

    def test_invalid_part_type(self) -> None:
        client = _mock_client()
        with pytest.raises(ValidationError, match="invalid part_type"):
            search_components(client, "STM32", part_type="invalid")

    def test_lcsc_id_trimmed(self) -> None:
        """LCSC ID whitespace is stripped before validation."""
        data = _make_component_data()
        client = _mock_client(cad_data=data)
        result = get_component_details(client, "  C83700  ")
        assert result["lcsc"] == "C83700"
