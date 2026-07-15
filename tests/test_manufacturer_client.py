"""Tests for the ManufacturerClient ABC + supporting dataclasses (INTEG-05).

Phase 209 Task 1. Mirrors the import-smoke + interface-shape style of
``test_crossfile_submodules.py``.
"""

from __future__ import annotations

import dataclasses
import sys

import pytest

from volta.manufacturing.manufacturer_client import (
    ManufacturerClient,
    OrderResult,
    OrderStatus,
    Quote,
)


class TestManufacturerClientImport:
    """Import-smoke and dependency-purity checks (TM-4)."""

    def test_module_imports_without_network_deps(self) -> None:
        """Importing the module does not pull httpx/requests/urllib into sys.modules.

        Measures the sys.modules delta caused by importing the module, so the
        assertion holds even when other tests in the suite loaded network libs.
        """
        import importlib
        network_mods = ("httpx", "requests", "urllib3", "aiohttp")
        before = set(sys.modules)
        importlib.import_module("volta.manufacturing.manufacturer_client")
        added = set(sys.modules) - before
        leaked = {m for m in network_mods if m in added}
        assert not leaked, f"network modules loaded by manufacturer_client: {leaked}"

    def test_all_four_names_importable(self) -> None:
        """ManufacturerClient + 3 dataclasses are importable."""
        assert ManufacturerClient is not None
        assert Quote is not None
        assert OrderResult is not None
        assert OrderStatus is not None


class TestDataclasses:
    """The 3 value objects are frozen dataclasses with the right shape (CR-01)."""

    def test_all_three_dataclasses_are_frozen(self) -> None:
        for cls in (Quote, OrderResult, OrderStatus):
            assert dataclasses.is_dataclass(cls)
            assert cls.__dataclass_params__.frozen, f"{cls.__name__} must be frozen"

    def test_quote_constructs_with_defaults(self) -> None:
        q = Quote(vendor="jlcpcb", unit_price_usd=2.50, quantity=100, lead_time_days=5)
        assert q.currency == "USD"
        assert q.notes == ""

    def test_order_result_constructs_with_default(self) -> None:
        r = OrderResult(order_id="ord-1", status="placed", vendor="jlcpcb")
        assert r.estimated_ship_date == ""

    def test_order_status_constructs_with_defaults(self) -> None:
        s = OrderStatus(order_id="ord-1", status="shipped", vendor="jlcpcb")
        assert s.tracking_number == ""
        assert s.last_updated == ""

    def test_frozen_dataclass_is_immutable(self) -> None:
        """A frozen dataclass raises on attribute assignment."""
        q = Quote(vendor="jlcpcb", unit_price_usd=1.0, quantity=1, lead_time_days=1)
        with pytest.raises(dataclasses.FrozenInstanceError):
            q.vendor = "pcbway"  # type: ignore[misc]


class TestAbstractInterface:
    """ManufacturerClient is abstract and cannot be instantiated directly."""

    def test_direct_instantiation_raises_typeerror(self) -> None:
        with pytest.raises(TypeError):
            ManufacturerClient()  # type: ignore[abstract]

    def test_stub_subclass_implementing_all_methods_instantiates(self) -> None:
        """A minimal concrete subclass can be instantiated and used."""

        class StubClient(ManufacturerClient):
            def quote(self, board_spec, quantity=1, **kwargs):  # type: ignore[no-untyped-def]
                return Quote(
                    vendor="stub", unit_price_usd=1.0,
                    quantity=quantity, lead_time_days=1,
                )

            def place_order(self, quote, **kwargs):  # type: ignore[no-untyped-def]
                return OrderResult(order_id="stub-1", status="placed", vendor="stub")

            def get_status(self, order_id):  # type: ignore[no-untyped-def]
                return OrderStatus(order_id=order_id, status="shipped", vendor="stub")

        client = StubClient()
        q = client.quote(board_spec=None, quantity=10)
        assert isinstance(q, Quote)
        assert q.quantity == 10
        assert isinstance(client.place_order(q), OrderResult)
        assert isinstance(client.get_status("stub-1"), OrderStatus)
