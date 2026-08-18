"""MouserSource — ComponentSource adapter for the Mouser Search API.

Python-side adapter for Mouser's public Search API (Phase 251 Wave 3).
Used by MCP tools when the Swift app isn't running (CLI-only workflows,
MCP server mode).

Requires an API key stored in the environment:
    MOUSER_API_KEY
"""

from __future__ import annotations

import logging
import os
import re
import urllib.error
import urllib.request
from typing import Any

from volta.crawler.component_source import (
    Component,
    ComponentPrice,
    ComponentSource,
    ComponentStock,
    SourceAttribution,
)

logger = logging.getLogger(__name__)

MOUSER_SEARCH_URL = "https://api.mouser.com/api/v1/search/keyword"

# "1523 In Stock" / "5000 In Stock" → 1523 / 5000
_STOCK_RE = re.compile(r"(\d[\d,]*)")


class MouserSource(ComponentSource):
    """ComponentSource backed by the Mouser Search API.

    API-key auth via the X-Mouser-ApiKey header. Rate limits (429) and
    auth failures (401) degrade to empty results rather than raising —
    callers treat Mouser as one source among several.
    """

    def __init__(self) -> None:
        self._api_key = os.environ.get("MOUSER_API_KEY", "")

    @property
    def api_key(self) -> str:
        return self._api_key

    @property
    def name(self) -> str:
        return "mouser"

    @property
    def display_name(self) -> str:
        return "Mouser"

    @property
    def is_available(self) -> bool:
        return bool(self._api_key)

    def search(self, keyword: str, limit: int = 10) -> tuple[list[Component], int]:
        """Search Mouser by keyword. Returns (components, total_matches).

        HTTP and parse failures return ([], 0) — never raise.
        """
        if not self.is_available:
            logger.warning("MouserSource: MOUSER_API_KEY not configured")
            return [], 0

        body = {
            "SearchByKeywordRequest": {
                "keyword": keyword,
                "records": limit,
                "startingRecord": 0,
            }
        }
        payload = _json_dumps(body)
        request = urllib.request.Request(
            MOUSER_SEARCH_URL,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "X-Mouser-ApiKey": self._api_key,
            },
        )

        try:
            with urllib.request.urlopen(request) as response:  # noqa: S310
                data = _json_loads(response.read())
        except urllib.error.HTTPError as exc:
            logger.warning("MouserSource: HTTP %s on search %r", exc.code, keyword)
            return [], 0
        except (urllib.error.URLError, OSError) as exc:
            logger.warning("MouserSource: network error on search %r: %s", keyword, exc)
            return [], 0
        except ValueError as exc:
            logger.warning("MouserSource: invalid JSON response: %s", exc)
            return [], 0

        results = data.get("SearchResults") or []
        total = data.get("TotalResults", 0) or 0
        components = [_map_part(part) for part in results if part.get("PartNumber")]
        return components, int(total)


def _map_part(part: dict[str, Any]) -> Component:
    """Map a Mouser SearchResults entry to the vendor-neutral Component."""
    part_number = part.get("PartNumber", "")
    manufacturer = part.get("Manufacturer", "")

    pricing: tuple[ComponentPrice, ...] = ()
    breaks = part.get("PriceBreaks") or []
    if breaks:
        first_price = _parse_price(breaks[0].get("Price"))
        pricing = (
            ComponentPrice(
                distributor="Mouser",
                unit_price=first_price,
                tiered_pricing=tuple(breaks),
            ),
        )

    stock: tuple[ComponentStock, ...] = ()
    quantity = _parse_stock(part.get("Availability", ""))
    if quantity is not None:
        stock = (ComponentStock(distributor="Mouser", quantity=quantity),)

    return Component(
        part_number=part_number,
        manufacturer=manufacturer,
        description=part.get("Description", ""),
        sources=(
            SourceAttribution(
                provider="mouser",
                provider_part_id=part_number,
            ),
        ),
        pricing=pricing,
        stock=stock,
        datasheet_url=part.get("DataSheetUrl", "") or "",
        category=part.get("ProductCategory", "") or "",
    )


def _parse_price(raw: Any) -> float | None:
    """Mouser prices arrive as floats or currency strings ("$5.50")."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    match = re.search(r"[\d.]+", str(raw))
    return float(match.group(0)) if match else None


def _parse_stock(availability: str) -> int | None:
    """"1523 In Stock" → 1523; anything unparseable → None."""
    match = _STOCK_RE.search(availability or "")
    if not match:
        return None
    return int(match.group(1).replace(",", ""))


def _json_dumps(obj: Any) -> bytes:
    import json

    return json.dumps(obj).encode("utf-8")


def _json_loads(raw: bytes) -> dict[str, Any]:
    import json

    return json.loads(raw)
