"""Tool definitions and response formatting for the component search MCP server.

Wraps EasyEdaClient with input validation, value mapping, and structured responses.
All EasyEdaClient calls are synchronous, so callers should use asyncio.to_thread().
"""

from __future__ import annotations

import re
from dataclasses import asdict
from typing import Any

from volta.crawler.easyeda_api import (
    EasyEdaClient,
    EasyEdaComponentData,
    EasyEdaFootprintPad,
    EasyEdaPin,
    JlcpcbComponent,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_KEYWORD_LEN = 200
_MAX_LIMIT = 50
_LCSC_RE = re.compile(r"^C\d+$")

# EasyEDA pin type int → KiCad electrical type string
# EasyEDA docs: 0=unspecified, 1=input, 2=output, 3=bidirectional, 4=power
# We map to the closest KiCad electrical_type equivalents.
_PIN_TYPE_MAP: dict[int, str] = {
    0: "passive",
    1: "input",
    2: "output",
    3: "bidirectional",
    4: "power_in",
}

# MCP tool input part_type values → EasyEdaClient API values
_PART_TYPE_MAP: dict[str, str] = {
    "basic": "base",
    "extended": "expand",
}

# Rate limiting: minimum seconds between API calls
_MIN_CALL_INTERVAL = 0.3


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class ValidationError(ValueError):
    """Raised when MCP tool input fails validation."""


def _validate_keyword(keyword: str) -> str:
    """Validate and normalize a search keyword."""
    keyword = keyword.strip()
    if not keyword:
        raise ValidationError("keyword must not be empty")
    if len(keyword) > _MAX_KEYWORD_LEN:
        raise ValidationError(f"keyword must be at most {_MAX_KEYWORD_LEN} characters")
    return keyword


def _validate_lcsc_id(lcsc_id: str) -> str:
    """Validate an LCSC part number (e.g., 'C83700')."""
    lcsc_id = lcsc_id.strip()
    if not _LCSC_RE.match(lcsc_id):
        raise ValidationError(f"invalid LCSC part number: {lcsc_id!r} (expected format: C followed by digits)")
    return lcsc_id


def _validate_limit(value: int, name: str = "limit") -> int:
    """Validate a limit parameter."""
    if value < 1 or value > _MAX_LIMIT:
        raise ValidationError(f"{name} must be between 1 and {_MAX_LIMIT}")
    return value


def _map_part_type(part_type: str | None) -> str | None:
    """Map user-facing part_type to API value."""
    if part_type is None:
        return None
    api_value = _PART_TYPE_MAP.get(part_type)
    if api_value is None:
        raise ValidationError(f"invalid part_type: {part_type!r} (expected 'basic' or 'extended')")
    return api_value


# ---------------------------------------------------------------------------
# Response formatting
# ---------------------------------------------------------------------------


def _format_pin(pin: EasyEdaPin) -> dict[str, Any]:
    """Format a pin with human-readable type."""
    return {
        "number": pin.pin_number,
        "name": pin.pin_name,
        "x": pin.pos_x,
        "y": pin.pos_y,
        "rotation": pin.rotation,
        "type": _PIN_TYPE_MAP.get(pin.pin_type, "passive"),
    }


def _format_pad(pad: EasyEdaFootprintPad) -> dict[str, Any]:
    """Format a pad."""
    return {
        "number": pad.pad_number,
        "x": pad.pos_x,
        "y": pad.pos_y,
        "width": pad.width,
        "height": pad.height,
        "layer": pad.layer,
        "shape": pad.shape,
    }


def _format_component(comp: JlcpcbComponent) -> dict[str, Any]:
    """Format a JLCPCB component for MCP response."""
    return {
        "lcsc": comp.lcsc,
        "name": comp.name,
        "brand": comp.brand,
        "package": comp.package,
        "category": comp.category,
        "stock": comp.stock,
        "part_type": comp.part_type,
        "price": comp.price,
        "datasheet": comp.datasheet,
        "attributes": list(comp.attributes),
    }


def _format_component_data(data: EasyEdaComponentData) -> dict[str, Any]:
    """Format full component CAD data for MCP response."""
    return {
        "lcsc": data.lcsc,
        "title": data.title,
        "package": data.package,
        "pins": [_format_pin(p) for p in data.pins],
        "pads": [_format_pad(p) for p in data.pads],
    }


def _format_suggestion(comp: JlcpcbComponent) -> dict[str, Any]:
    """Lightweight format for autocomplete suggestions."""
    return {
        "lcsc": comp.lcsc,
        "name": comp.name,
        "package": comp.package,
        "stock": comp.stock,
    }


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def search_components(
    client: EasyEdaClient,
    keyword: str,
    limit: int = 10,
    part_type: str | None = None,
) -> dict[str, Any]:
    """Search JLCPCB components by keyword.

    Args:
        client: EasyEdaClient instance.
        keyword: Search query (e.g., "STM32", "NE555", "100nF 0402").
        limit: Maximum results to return (1-50).
        part_type: "basic" for Basic parts, "extended" for Extended, None for both.

    Returns:
        Dict with "results" list and "total" count.

    Raises:
        ValidationError: If inputs fail validation.
    """
    keyword = _validate_keyword(keyword)
    limit = _validate_limit(limit)
    api_part_type = _map_part_type(part_type)

    components, total = client.search_jlcpcb(
        keyword=keyword,
        page=1,
        page_size=min(limit, 25),  # JLCPCB max page size is 25
        part_type=api_part_type,
    )

    # If limit > 25, fetch additional pages
    if limit > 25 and len(components) < limit:
        page = 2
        while len(components) < limit and len(components) < total:
            extra, _ = client.search_jlcpcb(
                keyword=keyword,
                page=page,
                page_size=min(limit - len(components), 25),
                part_type=api_part_type,
            )
            if not extra:
                break
            components.extend(extra)
            page += 1

    return {
        "results": [_format_component(c) for c in components[:limit]],
        "total": total,
    }


def get_component_details(
    client: EasyEdaClient,
    lcsc_id: str,
) -> dict[str, Any]:
    """Get full CAD data for a specific LCSC component.

    Args:
        client: EasyEdaClient instance.
        lcsc_id: LCSC part number (e.g., "C83700").

    Returns:
        Dict with lcsc, title, package, pins, and pads.

    Raises:
        ValidationError: If lcsc_id is malformed.
        ValueError: If component not found.
    """
    lcsc_id = _validate_lcsc_id(lcsc_id)

    data = client.get_component_cad_data(lcsc_id)
    if data is None:
        raise ValueError(f"Component not found: {lcsc_id}")

    return _format_component_data(data)


def search_and_detail(
    client: EasyEdaClient,
    keyword: str,
    detail_limit: int = 3,
    search_limit: int = 10,
) -> dict[str, Any]:
    """Search components and fetch full CAD data for top results.

    Args:
        client: EasyEdaClient instance.
        keyword: Search query.
        detail_limit: Number of top results to fetch CAD data for (1-10).
        search_limit: Total search results to return (1-50).

    Returns:
        Dict with "results" (top N with full pins/pads) and "total".

    Raises:
        ValidationError: If inputs fail validation.
    """
    keyword = _validate_keyword(keyword)
    search_limit = _validate_limit(search_limit)
    detail_limit = _validate_limit(detail_limit, name="detail_limit")
    if detail_limit > search_limit:
        detail_limit = search_limit

    components, total = client.search_jlcpcb(
        keyword=keyword,
        page=1,
        page_size=min(search_limit, 25),
    )

    if search_limit > 25 and len(components) < search_limit:
        page = 2
        while len(components) < search_limit and len(components) < total:
            extra, _ = client.search_jlcpcb(
                keyword=keyword,
                page=page,
                page_size=min(search_limit - len(components), 25),
            )
            if not extra:
                break
            components.extend(extra)
            page += 1

    results = [_format_component(c) for c in components[:search_limit]]

    # Fetch CAD data for top N
    for i in range(min(detail_limit, len(results))):
        lcsc = results[i]["lcsc"]
        data = client.get_component_cad_data(lcsc)
        if data is not None:
            results[i]["pins"] = [_format_pin(p) for p in data.pins]
            results[i]["pads"] = [_format_pad(p) for p in data.pads]

    return {
        "results": results,
        "total": total,
    }


def get_component_suggestions(
    client: EasyEdaClient,
    keyword: str,
    limit: int = 5,
) -> dict[str, Any]:
    """Quick suggestion list for autocomplete-style UX.

    Args:
        client: EasyEdaClient instance.
        keyword: Search query.
        limit: Maximum suggestions (1-50).

    Returns:
        Dict with "suggestions" list (lcsc, name, package, stock only).

    Raises:
        ValidationError: If inputs fail validation.
    """
    keyword = _validate_keyword(keyword)
    limit = _validate_limit(limit)

    components, total = client.search_jlcpcb(
        keyword=keyword,
        page=1,
        page_size=min(limit, 25),
    )

    return {
        "suggestions": [_format_suggestion(c) for c in components[:limit]],
        "total": total,
    }
