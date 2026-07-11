"""ManufacturerClient -- abstract interface for manufacturer API adapters.

Phase 209: INTEG-05. Interface-only ABC that seeds the v7.1 vendor adapter
contract (quote / place_order / get_status). Implementations are deliberately
out of scope here -- Phase 210 (DEFERRED to v7.1) builds the concrete adapters
(PCBWay, MacroFab, JLCPCB).

This module is import-pure: it pulls in only ``abc``, ``dataclasses``, and
``typing`` -- no ``httpx``/``requests``/``urllib``/``aiohttp``. Importing it
must not trigger any I/O or pull a network library into ``sys.modules``
(threat-model TM-4).

Scope guard (Pitfall 8): If activated, scope to QUOTE ONLY first -- quoting is
read-only and safe; ordering has financial consequences.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Quote:
    """Vendor-neutral manufacturing quote (CR-01 frozen dataclass).

    Carries enough info to compare vendors without being vendor-specific.

    Attributes:
        vendor: Vendor key (e.g. ``"jlcpcb"``).
        unit_price_usd: Per-unit price.
        quantity: Number of boards the quote covers.
        lead_time_days: Estimated fabrication lead time.
        currency: ISO 4217 currency code (default ``"USD"``).
        notes: Freeform vendor notes.
    """

    vendor: str
    unit_price_usd: float
    quantity: int
    lead_time_days: int
    currency: str = "USD"
    notes: str = ""


@dataclass(frozen=True)
class OrderResult:
    """Result of placing an order (CR-01 frozen dataclass).

    Attributes:
        order_id: Vendor-issued order identifier.
        status: Vendor status string at order time.
        vendor: Vendor key.
        estimated_ship_date: Optional ship-date estimate.
    """

    order_id: str
    status: str
    vendor: str
    estimated_ship_date: str = ""


@dataclass(frozen=True)
class OrderStatus:
    """Status snapshot for a previously placed order (CR-01 frozen dataclass).

    Attributes:
        order_id: Vendor-issued order identifier.
        status: Current vendor status string.
        vendor: Vendor key.
        tracking_number: Shipment tracking number (when available).
        last_updated: Vendor-reported timestamp of this status.
    """

    order_id: str
    status: str
    vendor: str
    tracking_number: str = ""
    last_updated: str = ""


class ManufacturerClient(ABC):
    """Abstract interface for manufacturer API adapters.

    Implementations (Phase 210, DEFERRED to v7.1) connect to specific vendor
    APIs (PCBWay, MacroFab, JLCPCB) for quote/order/status.

    Scope guard (Pitfall 8): If activated, scope to QUOTE ONLY first --
    quoting is read-only and safe; ordering has financial consequences. Any
    concrete adapter must treat ``place_order`` as a high-stakes, opt-in path
    requiring explicit confirmation.
    """

    @abstractmethod
    def quote(self, board_spec: Any, quantity: int = 1, **kwargs: Any) -> Quote:
        """Request a manufacturing quote for a board specification."""

    @abstractmethod
    def place_order(self, quote: Quote, **kwargs: Any) -> OrderResult:
        """Place an order based on a previously obtained quote."""

    @abstractmethod
    def get_status(self, order_id: str) -> OrderStatus:
        """Check the status of a previously placed order."""
