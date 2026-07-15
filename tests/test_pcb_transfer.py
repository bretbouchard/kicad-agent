"""Tests for PCB transfer handler -- D-12 force flag removal.

Verifies that production handlers have no force bypass parameter.
All validation gates always run; there is no CLI-only escape hatch.
"""

import ast
import inspect
from pathlib import Path
from typing import Any

import pytest

from volta.ops.handlers.pcb_transfer import (
    UpdateFromSchematicOp,
    handle_update_from_schematic,
)


# ---------------------------------------------------------------------------
# D-12: Force flag removal tests
# ---------------------------------------------------------------------------


class TestForceFlagRemoval:
    """D-12: Force flag removed from production handlers."""

    def test_handle_update_from_schematic_no_force_param(self):
        """D-12: handle_update_from_schematic has no 'force' parameter."""
        sig = inspect.signature(handle_update_from_schematic)
        params = list(sig.parameters.keys())
        assert "force" not in params, f"force parameter found in {params}"

    def test_handle_update_from_schematic_always_validates(self):
        """D-12: Validation always runs, no force bypass branch exists."""
        source = inspect.getsource(handle_update_from_schematic)
        # No force bypass conditional
        assert "if force" not in source, "Force bypass conditional found"
        assert "force=True" not in source
        assert "force_bypassed" not in source

    def test_no_force_references_in_module(self):
        """D-12: Zero 'force' parameter references in entire module."""
        import volta.ops.handlers.pcb_transfer as mod
        source = inspect.getsource(mod)
        # No function-level force parameter (not in schema, not in handler)
        assert "force: bool" not in source
        assert "force=True" not in source
        assert "force=False" not in source
        # Docstrings mentioning "no force" or "no bypass" are OK
        # But actual force parameter usage is not
        assert "if force:" not in source

    def test_schema_has_no_force_field(self):
        """D-12: UpdateFromSchematicOp schema has no force/bypass field."""
        fields = UpdateFromSchematicOp.model_fields
        assert "force" not in fields
        assert "bypass" not in fields
        assert "skip_validation" not in fields
