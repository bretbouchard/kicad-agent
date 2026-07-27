"""EasyEdaSource — ComponentSource adapter for EasyEdaClient.

Wraps the existing EasyEdaClient to conform to the ComponentSource ABC.
This is the bridge between the legacy hardcoded client and the new
pluggable architecture.
"""

from __future__ import annotations

import logging
from typing import Any

from volta.crawler.component_source import (
    Component,
    ComponentPrice,
    ComponentSource,
    ComponentStock,
    SourceAttribution,
)
from volta.crawler.easyeda_api import EasyEdaClient, JlcpcbComponent

logger = logging.getLogger(__name__)


class EasyEdaSource(ComponentSource):
    """ComponentSource backed by EasyEdaClient (JLCPCB search + EasyEDA CAD data).

    Translates JlcpcbComponent → vendor-neutral Component at the boundary.
    """

    def __init__(self, client: EasyEdaClient | None = None) -> None:
        self._client = client or EasyEdaClient()

    @property
    def name(self) -> str:
        return "easyeda"

    @property
    def display_name(self) -> str:
        return "EasyEDA / JLCPCB"

    def search(self, keyword: str, limit: int = 10) -> tuple[list[Component], int]:
        """Search JLCPCB components and map to vendor-neutral Components."""
        page_size = min(limit, 25)
        components, total = self._client.search_jlcpcb(
            keyword=keyword, page=1, page_size=page_size
        )

        # Fetch additional pages if needed
        if limit > 25 and len(components) < limit:
            page = 2
            while len(components) < limit and len(components) < total:
                extra, _ = self._client.search_jlcpcb(
                    keyword=keyword, page=page, page_size=min(limit - len(components), 25)
                )
                if not extra:
                    break
                components.extend(extra)
                page += 1

        return [self._map_component(c) for c in components[:limit]], total

    def get_details(self, part_number: str) -> Component | None:
        """Get component details by LCSC part number."""
        comp_data = self._client.get_component_cad_data(part_number)
        if comp_data is None:
            return None

        # Search to get the basic component info, then attach CAD data
        components, _ = self._client.search_jlcpcb(keyword=part_number, page_size=1)
        if not components:
            return None

        comp = self._map_component(components[0])
        return comp

    def get_cad_data(self, part_number: str) -> dict[str, Any] | None:
        """Get CAD data (pins, pads) for a component by LCSC ID."""
        data = self._client.get_component_cad_data(part_number)
        if data is None:
            return None
        return {
            "lcsc": data.lcsc,
            "title": data.title,
            "package": data.package,
            "pins": [
                {
                    "number": p.pin_number,
                    "name": p.pin_name,
                    "x": p.pos_x,
                    "y": p.pos_y,
                    "rotation": p.rotation,
                    "type": p.pin_type,
                }
                for p in data.pins
            ],
            "pads": [
                {
                    "number": p.pad_number,
                    "x": p.pos_x,
                    "y": p.pos_y,
                    "width": p.width,
                    "height": p.height,
                    "layer": p.layer,
                    "shape": p.shape,
                }
                for p in data.pads
            ],
        }

    def _map_component(self, jlcpcb: JlcpcbComponent) -> Component:
        """Map JlcpcbComponent → vendor-neutral Component."""
        specs: dict[str, str] = {}
        for attr in jlcpcb.attributes:
            name = attr.get("name", "")
            value = attr.get("value", "")
            if name and value:
                specs[name] = value

        pricing: tuple[ComponentPrice, ...] = ()
        if jlcpcb.price is not None:
            pricing = (
                ComponentPrice(
                    distributor="JLCPCB",
                    unit_price=jlcpcb.price,
                    min_order_qty=1,
                    currency="USD",
                ),
            )

        stock: tuple[ComponentStock, ...] = (
            ComponentStock(distributor="JLCPCB", quantity=jlcpcb.stock),
        )

        return Component(
            part_number=jlcpcb.name,
            manufacturer=jlcpcb.brand,
            description=jlcpcb.package,
            sources=(
                SourceAttribution(
                    provider="easyeda",
                    provider_part_id=jlcpcb.lcsc,
                    confidence=0.75,
                ),
            ),
            pricing=pricing,
            stock=stock,
            specs=specs,
            datasheet_url=jlcpcb.datasheet,
            lcsc_part_number=jlcpcb.lcsc,
            category=jlcpcb.category,
        )
