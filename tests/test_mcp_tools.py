"""Regression guard: all v7.0 operations are auto-exposed as MCP tools.

Phase 209 (INTEG-01) is a verification-only requirement: ``_generate_operation_tools``
reads from the ``Operation`` discriminated union, so every op variant becomes an
MCP tool with zero manual wiring. This test locks that contract so future
schema/registry drift cannot silently drop an op from the MCP tool surface.
"""

from __future__ import annotations

from volta.mcp.edit_server import _generate_operation_tools


# The 9 ops added across Phases 205-208 that must appear as MCP tools.
_V70_OP_TYPES = {
    # Phase 205: board metadata
    "read_board_metadata",
    "set_board_metadata",
    "set_board_revision",
    # Phase 206: vendor DRC
    "drc_vendor",
    "list_vendor_drc_profiles",
    # Phase 207: versioned builds
    "build_create",
    "build_list",
    "build_show",
    # Phase 208: manufacturer handoff
    "build_handoff_export",
}


class TestMcpAutoExposure:
    """Verify the Operation union auto-generates MCP tools for v7.0 ops."""

    def test_all_v70_ops_are_mcp_tools(self) -> None:
        """Every Phase 205-208 op_type appears in the generated tool list."""
        tool_names = {t.name for t in _generate_operation_tools()}
        missing = _V70_OP_TYPES - tool_names
        assert not missing, f"v7.0 ops missing from MCP tools: {sorted(missing)}"

    def test_tool_count_matches_union_variants(self) -> None:
        """The generated tool count is non-trivial and stable (>= 163)."""
        tools = _generate_operation_tools()
        # 160 registered ops + 3 schema-only ops = 163 union variants.
        assert len(tools) >= 163
