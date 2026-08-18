"""Tool definitions and response formatting for the component search MCP server.

Uses the ComponentSource ABC to dispatch queries to any registered source.
The default registry includes EasyEdaSource and DigiKeySource (when configured).
Callers can register additional sources at runtime.

All ComponentSource calls are synchronous; callers should use asyncio.to_thread().
"""

from __future__ import annotations

import re
from typing import Any

from volta.crawler.component_source import ComponentRegistry, ComponentSource
from volta.crawler.digikey_source import DigiKeySource
from volta.crawler.easyeda_api import (
    EasyEdaClient,
    EasyEdaComponentData,
    EasyEdaFootprintPad,
    EasyEdaPin,
    JlcpcbComponent,
)
from volta.crawler.easyeda_source import EasyEdaSource
from volta.crawler.mouser_source import MouserSource

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_KEYWORD_LEN = 200
_MAX_LIMIT = 50
_LCSC_RE = re.compile(r"^C\d+$")

# EasyEDA pin type int → KiCad electrical type string
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


# ---------------------------------------------------------------------------
# Default registry factory
# ---------------------------------------------------------------------------


def create_default_registry(
    easyeda_client: EasyEdaClient | None = None,
) -> ComponentRegistry:
    """Create a ComponentRegistry with all available sources registered.

    Args:
        easyeda_client: Optional EasyEdaClient instance (for cache dir config).

    Returns:
        ComponentRegistry with EasyEdaSource always registered and
        DigiKeySource registered if credentials are available.
    """
    registry = ComponentRegistry()
    registry.register(EasyEdaSource(client=easyeda_client))
    registry.register(DigiKeySource())
    registry.register(MouserSource())
    return registry


# ---------------------------------------------------------------------------
# Input validation (unchanged)
# ---------------------------------------------------------------------------


class ValidationError(ValueError):
    """Raised when MCP tool input fails validation."""


def _validate_keyword(keyword: str) -> str:
    keyword = keyword.strip()
    if not keyword:
        raise ValidationError("keyword must not be empty")
    if len(keyword) > _MAX_KEYWORD_LEN:
        raise ValidationError(f"keyword must be at most {_MAX_KEYWORD_LEN} characters")
    return keyword


def _validate_lcsc_id(lcsc_id: str) -> str:
    lcsc_id = lcsc_id.strip()
    if not _LCSC_RE.match(lcsc_id):
        raise ValidationError(f"invalid LCSC part number: {lcsc_id!r} (expected format: C followed by digits)")
    return lcsc_id


def _validate_limit(value: int, name: str = "limit") -> int:
    if value < 1 or value > _MAX_LIMIT:
        raise ValidationError(f"{name} must be between 1 and {_MAX_LIMIT}")
    return value


def _map_part_type(part_type: str | None) -> str | None:
    if part_type is None:
        return None
    api_value = _PART_TYPE_MAP.get(part_type)
    if api_value is None:
        raise ValidationError(f"invalid part_type: {part_type!r} (expected 'basic' or 'extended')")
    return api_value


# ---------------------------------------------------------------------------
# Response formatting (vendor-neutral)
# ---------------------------------------------------------------------------


def _format_component_v2(comp: Any) -> dict[str, Any]:
    """Format a vendor-neutral Component for MCP response."""
    return {
        "part_number": comp.part_number,
        "manufacturer": comp.manufacturer,
        "description": comp.description,
        "category": comp.category,
        "pricing": [
            {
                "distributor": p.distributor,
                "unit_price": p.unit_price,
                "min_order_qty": p.min_order_qty,
                "currency": p.currency,
                "tiers": [dict(t) for t in p.tiered_pricing] if p.tiered_pricing else [],
            }
            for p in comp.pricing
        ],
        "stock": [
            {
                "distributor": s.distributor,
                "quantity": s.quantity,
                "lead_time": s.lead_time,
            }
            for s in comp.stock
        ],
        "specs": dict(comp.specs),
        "datasheet": comp.datasheet_url,
        "lcsc": comp.lcsc_part_number,
        "sources": [
            {
                "provider": s.provider,
                "provider_part_id": s.provider_part_id,
                "confidence": s.confidence,
            }
            for s in comp.sources
        ],
    }


# ---------------------------------------------------------------------------
# Legacy response formatting (backward compat with existing MCP clients)
# ---------------------------------------------------------------------------


def _format_pin(pin: EasyEdaPin) -> dict[str, Any]:
    return {
        "number": pin.pin_number,
        "name": pin.pin_name,
        "x": pin.pos_x,
        "y": pin.pos_y,
        "rotation": pin.rotation,
        "type": _PIN_TYPE_MAP.get(pin.pin_type, "passive"),
    }


def _format_pad(pad: EasyEdaFootprintPad) -> dict[str, Any]:
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
    return {
        "lcsc": data.lcsc,
        "title": data.title,
        "package": data.package,
        "pins": [_format_pin(p) for p in data.pins],
        "pads": [_format_pad(p) for p in data.pads],
    }


def _format_suggestion(comp: JlcpcbComponent) -> dict[str, Any]:
    return {
        "lcsc": comp.lcsc,
        "name": comp.name,
        "package": comp.package,
        "stock": comp.stock,
    }


# ---------------------------------------------------------------------------
# Tool implementations — multi-source (new API)
# ---------------------------------------------------------------------------


def search_all_sources(
    registry: ComponentRegistry,
    keyword: str,
    limit: int = 10,
) -> dict[str, Any]:
    """Search across all registered sources and return merged results.

    Args:
        registry: ComponentRegistry with registered sources.
        keyword: Search query (e.g., "STM32", "NE555", "100nF 0402").
        limit: Maximum results per source (1-50).

    Returns:
        Dict mapping source name to {results, total}.

    Raises:
        ValidationError: If inputs fail validation.
    """
    keyword = _validate_keyword(keyword)
    limit = _validate_limit(limit)

    raw = registry.search_all(keyword, limit=limit)

    return {
        source_name: {
            "results": [_format_component_v2(c) for c in comps],
            "total": total,
        }
        for source_name, (comps, total) in raw.items()
    }


# ---------------------------------------------------------------------------
# Tool implementations — legacy (backward compat)
# ---------------------------------------------------------------------------
# These retain the original EasyEdaClient-specific API for existing MCP clients.
# New code should use search_all_sources() with a ComponentRegistry.
# ---------------------------------------------------------------------------


def search_components(
    client: EasyEdaClient,
    keyword: str,
    limit: int = 10,
    part_type: str | None = None,
) -> dict[str, Any]:
    """Search JLCPCB components by keyword. (Legacy — uses EasyEdaClient directly.)

    New code should use search_all_sources() with a ComponentRegistry instead.
    """
    keyword = _validate_keyword(keyword)
    limit = _validate_limit(limit)
    api_part_type = _map_part_type(part_type)

    components, total = client.search_jlcpcb(
        keyword=keyword,
        page=1,
        page_size=min(limit, 25),
        part_type=api_part_type,
    )

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
    """Get full CAD data for a specific LCSC component. (Legacy)"""
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
    """Search components and fetch full CAD data for top results. (Legacy)"""
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
    """Quick suggestion list for autocomplete-style UX. (Legacy)"""
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
