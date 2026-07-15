"""Schematic ERC repair operations -- re-export shim.

Split into domain-specific modules:
- repair_wires.py: Wire snapping, grid, dangling, bridges, shorts
- repair_nets.py: Shorted net detection and resolution
- repair_components.py: Symbol/unit repair
- repair_erc.py: No-connects, power flags, labels, junctions

Usage:
    from volta.ops.repair import repair_wire_snapping
"""

# Re-export SNAP_TOLERANCE for backward compatibility
from volta.ops.repair_wires import SNAP_TOLERANCE  # noqa: F401

# Re-export NetPositionIndex for backward compatibility (tests patch via this path)
from volta.schematic_routing.net_extractor import NetPositionIndex  # noqa: F401

# Public API re-exports
from volta.ops.repair_wires import (  # noqa: F401
    break_wire_shorts,
    find_bridge_wires,
    remove_dangling_wires,
    repair_wire_snapping,
    snap_to_grid,
)
from volta.ops.repair_nets import (  # noqa: F401
    _check_orphan_count,
    _diff_net_snapshots,
    _is_power_net,
    _take_net_snapshot,
    _verify_clean_break,
    detect_shorted_nets,
    fix_shorted_nets,
    resolve_shorted_nets,
)
from volta.ops.repair_components import (  # noqa: F401
    fix_pin_type_mismatches,
    place_missing_units,
    update_symbols_from_library,
)
from volta.ops.repair_erc import (  # noqa: F401
    _checkpoint_ir,
    _restore_ir,
    add_junctions_at_labels,
    add_power_flags,
    place_no_connects,
    place_no_connects_from_erc,
    remove_orphaned_labels,
)

# Re-export private helpers used by tests
from volta.ops.repair_components import (  # noqa: F401
    _find_position_for_unit,
    _get_unit_pin_map,
    _get_unit_pin_offsets,
)
from volta.ops.repair_wires import (  # noqa: F401
    _point_on_wire_segment,
    _near_anchor,
)
