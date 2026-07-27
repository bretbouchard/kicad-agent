"""Abstract component source interface — vendor-neutral provider protocol.

This is the Python-side equivalent of Swift's ComponentDataProvider protocol.
Every component data source (EasyEDA, Digi-Key, Octopart, jlcparts) implements
ComponentSource. The MCP tool layer dispatches to registered sources rather
than hardcoding EasyEdaClient.

Usage:
    from volta.crawler.component_source import ComponentSource, ComponentRegistry

    registry = ComponentRegistry()
    registry.register(EasyEdaSource())
    registry.register(DigiKeySource(...))

    results = registry.search("STM32F411", limit=10)
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Vendor-neutral data models (mirror Swift UnifiedComponent)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ComponentPrice:
    """Per-distributor pricing entry."""
    distributor: str
    unit_price: float | None
    min_order_qty: int = 1
    currency: str = "USD"
    tiered_pricing: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class ComponentStock:
    """Per-distributor stock entry."""
    distributor: str
    quantity: int
    lead_time: str | None = None


@dataclass(frozen=True)
class SourceAttribution:
    """Which provider contributed data for a component."""
    provider: str
    provider_part_id: str
    confidence: float = 0.8


@dataclass(frozen=True)
class Component:
    """Vendor-neutral component — Python mirror of Swift UnifiedComponent.

    Every provider's native response is translated into this shape at the
    provider boundary. Nothing vendor-specific escapes the source module.
    """
    part_number: str
    manufacturer: str
    description: str
    sources: tuple[SourceAttribution, ...] = ()
    pricing: tuple[ComponentPrice, ...] = ()
    stock: tuple[ComponentStock, ...] = ()
    specs: dict[str, str] = field(default_factory=dict)
    datasheet_url: str = ""
    lcsc_part_number: str = ""
    category: str = ""

    @property
    def normalized_mpn(self) -> str:
        """Uppercase, stripped of spaces and dashes — canonical merge key."""
        return self.part_number.upper().replace(" ", "").replace("-", "")


# ---------------------------------------------------------------------------
# HTTPSession protocol (network abstraction)
# ---------------------------------------------------------------------------


@runtime_checkable
class HTTPSession(Protocol):
    """Network transport abstraction — replaces raw urllib.request.

    Allows mocking network calls in tests without monkeypatching urllib.
    """

    def get(self, url: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
        """GET request returning parsed JSON."""
        ...

    def post(
        self,
        url: str,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """POST request returning parsed JSON."""
        ...


# ---------------------------------------------------------------------------
# ComponentSource ABC
# ---------------------------------------------------------------------------


class ComponentSource(ABC):
    """Abstract base class for all component data sources.

    Implementations must provide search() and optionally get_details().
    Each source maps its native response format into the vendor-neutral
    Component dataclass.

    This is the Python equivalent of Swift's ComponentDataProvider protocol.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Machine identifier (e.g., 'easyeda', 'digikey', 'octopart')."""
        ...

    @property
    def display_name(self) -> str:
        """Human-readable name for UI display."""
        return self.name.capitalize()

    @property
    def is_available(self) -> bool:
        """Whether this source can currently serve requests."""
        return True

    @abstractmethod
    def search(self, keyword: str, limit: int = 10) -> tuple[list[Component], int]:
        """Search for components by keyword.

        Args:
            keyword: Search query (MPN, description, etc.).
            limit: Maximum results to return.

        Returns:
            Tuple of (component_list, total_results).
        """
        ...

    def get_details(self, part_number: str) -> Component | None:
        """Get detailed data for a specific part.

        Override for sources that support detailed lookups.
        Returns None by default (source doesn't support detail queries).
        """
        return None

    def get_cad_data(self, part_number: str) -> dict[str, Any] | None:
        """Get CAD data (pins, pads, footprint) for a part.

        Override for sources that provide CAD data.
        Returns None by default.
        """
        return None


# ---------------------------------------------------------------------------
# Component Registry
# ---------------------------------------------------------------------------


class ComponentRegistry:
    """Registry of component sources — Python mirror of Swift's registry.

    MCP tools query the registry instead of a specific source. Sources are
    registered at startup; the registry dispatches queries to all available
    sources and returns merged results.
    """

    def __init__(self) -> None:
        self._sources: dict[str, ComponentSource] = {}

    def register(self, source: ComponentSource) -> None:
        """Register a component source."""
        if source.name in self._sources:
            logger.warning("ComponentRegistry: replacing existing source '%s'", source.name)
        self._sources[source.name] = source
        logger.info("ComponentRegistry: registered '%s'", source.name)

    def unregister(self, name: str) -> None:
        """Remove a registered source."""
        self._sources.pop(name, None)

    def get(self, name: str) -> ComponentSource | None:
        """Get a source by name."""
        return self._sources.get(name)

    @property
    def sources(self) -> list[ComponentSource]:
        """All registered sources."""
        return list(self._sources.values())

    @property
    def available_sources(self) -> list[ComponentSource]:
        """Sources that are currently available."""
        return [s for s in self._sources.values() if s.is_available]

    def search_all(
        self, keyword: str, limit: int = 10
    ) -> dict[str, tuple[list[Component], int]]:
        """Search across all available sources.

        Returns:
            Dict mapping source name to (results, total).
            Failed sources are logged and excluded from results.
        """
        results: dict[str, tuple[list[Component], int]] = {}
        for source in self.available_sources:
            try:
                comps, total = source.search(keyword, limit=limit)
                results[source.name] = (comps, total)
            except Exception:
                logger.exception("Source '%s' failed for query '%s'", source.name, keyword)
        return results
