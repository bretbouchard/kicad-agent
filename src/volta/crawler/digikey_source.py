"""DigiKeySource — ComponentSource adapter for Digi-Key V4 API.

Python-side adapter for Digi-Key's V4 API. Used by MCP tools when
the Swift app isn't running (e.g., CLI-only workflows, MCP server mode).

Requires OAuth2 client credentials stored in environment variables:
    DIGIKEY_CLIENT_ID, DIGIKEY_CLIENT_SECRET
"""

from __future__ import annotations

import logging
import os
import time
import urllib.parse
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

# Digi-Key V4 API endpoints (US sandbox/production)
DIGIKEY_TOKEN_URL = "https://api.digikey.com/v1/oauth2/token"
DIGIKEY_SEARCH_URL = "https://api.digikey.com/products/v4/search/keyword"


class DigiKeySource(ComponentSource):
    """ComponentSource backed by Digi-Key V4 API.

    Uses OAuth2 client credentials flow. Token is cached in-memory with
    60-second pre-expiry renewal. Falls back gracefully when credentials
    are not configured.
    """

    def __init__(self) -> None:
        self._client_id = os.environ.get("DIGIKEY_CLIENT_ID", "")
        self._client_secret = os.environ.get("DIGIKEY_CLIENT_SECRET", "")
        self._token: str = ""
        self._token_expires: float = 0.0

    @property
    def name(self) -> str:
        return "digikey"

    @property
    def display_name(self) -> str:
        return "Digi-Key"

    @property
    def is_available(self) -> bool:
        return bool(self._client_id and self._client_secret)

    def _ensure_token(self) -> str | None:
        """Get a valid OAuth2 token, refreshing if needed."""
        if self._token and time.time() < self._token_expires - 60:
            return self._token

        if not self.is_available:
            logger.warning("DigiKeySource: credentials not configured")
            return None

        data = urllib.parse.urlencode({
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "grant_type": "client_credentials",
        }).encode("utf-8")

        try:
            req = urllib.request.Request(
                DIGIKEY_TOKEN_URL,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                token_data = __import__("json").loads(resp.read())
                self._token = token_data["access_token"]
                self._token_expires = time.time() + token_data.get("expires_in", 1800)
                return self._token
        except Exception:
            logger.exception("DigiKeySource: failed to get OAuth2 token")
            return None

    def search(self, keyword: str, limit: int = 10) -> tuple[list[Component], int]:
        """Search Digi-Key components via V4 keyword search."""
        token = self._ensure_token()
        if not token:
            return [], 0

        payload = {
            "Keywords": keyword,
            "RecordCount": min(limit, 50),
            "RecordStartPosition": 0,
        }

        body = __import__("json").dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            DIGIKEY_SEARCH_URL,
            data=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "X-DIGIKEY-Locale-Site": "US",
                "X-DIGIKEY-Locale-Language": "en",
                "X-DIGIKEY-Locale-Currency": "USD",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = __import__("json").loads(resp.read())
        except Exception:
            logger.exception("DigiKeySource: search failed for '%s'", keyword)
            return [], 0

        products = (raw.get("Products") or [])[:limit]
        total = raw.get("ProductCount", len(products))

        components = [self._map_product(p) for p in products]
        return components, total

    def _map_product(self, product: dict[str, Any]) -> Component:
        """Map a Digi-Key V4 product to vendor-neutral Component."""
        # Pricing
        pricing: tuple[ComponentPrice, ...] = ()
        std_pricing = product.get("StandardPricing") or []
        tiers = tuple(
            {"min_qty": t.get("BreakQuantity", 0), "unit_price": t.get("UnitPrice", 0.0)}
            for t in std_pricing
        )
        if std_pricing:
            unit_price = std_pricing[0].get("UnitPrice")
            min_qty = std_pricing[0].get("BreakQuantity", 1)
            pricing = (
                ComponentPrice(
                    distributor="Digi-Key",
                    unit_price=unit_price,
                    min_order_qty=min_qty,
                    currency="USD",
                    tiered_pricing=tiers,
                ),
            )

        # Stock
        stock_qty = product.get("QuantityAvailable", 0)
        stock = (
            ComponentStock(
                distributor="Digi-Key",
                quantity=stock_qty,
                lead_time=product.get("LeadTime"),
            ),
        )

        # Specs
        specs: dict[str, str] = {}
        for param in product.get("Parameters") or []:
            name = param.get("ParameterName", "")
            value = param.get("Value", "")
            if name and value:
                specs[name] = value

        # Datasheet
        datasheet = product.get("PrimaryDatasheet", "") or ""

        # Part number and manufacturer
        mpn = product.get("ManufacturerPartNumber", "") or product.get("DigiKeyPartNumber", "")
        mfr = (product.get("Manufacturer") or {}).get("Value", "") or ""
        desc = product.get("DetailedDescription", "") or product.get("ProductDescription", "")
        category = (product.get("ProductCategory") or {}).get("Value", "") or ""

        dk_part_id = product.get("DigiKeyPartNumber", "")

        return Component(
            part_number=mpn,
            manufacturer=mfr,
            description=desc,
            sources=(
                SourceAttribution(
                    provider="digikey",
                    provider_part_id=dk_part_id,
                    confidence=0.95,
                ),
            ),
            pricing=pricing,
            stock=stock,
            specs=specs,
            datasheet_url=datasheet,
            category=category,
        )
