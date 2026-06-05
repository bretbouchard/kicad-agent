"""Component repair operations -- symbol updates, pin type fixes, unit placement.

Provides component-level repair functions for schematic ERC auto-fix:
- Library symbol re-embedding for mismatched symbols
- Pin electrical type mismatch fixing
- Multi-unit symbol missing unit placement with connectivity-aware scoring
"""

import logging
import math
from collections import Counter
from pathlib import Path
from typing import Any

from kicad_agent.ir.schematic_ir import SchematicIR
from kicad_agent.schematic_routing.net_extractor import NetPositionIndex

logger = logging.getLogger(__name__)


def update_symbols_from_library(
    ir: SchematicIR, file_path: Path, *,
    references: list[str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Re-embed mismatched symbols from their libraries.

    Equivalent to KiCad GUI's "Update Symbol from Library" for all symbols
    whose embedded lib_symbols definition diverges from the library version.

    Args:
        ir: SchematicIR for the target schematic.
        file_path: Resolved path to the schematic file.
        references: Specific references to update, or None for all.
        dry_run: If True, report mismatches without modifying.

    Returns:
        Dict with updated (list), skipped (list), and total_mismatches.
    """
    import copy

    from kiutils.symbol import SymbolLib

    from kicad_agent.ir.schematic_ir import _match_lib_symbol
    from kicad_agent.validation.symbol_mismatch import (
        _get_embedded_pin_signature,
        _get_library_pin_signature,
    )

    sch = ir._parse_result.kiutils_obj

    # Get all unique lib_ids used by placed symbols
    try:
        all_refs = ir.get_all_references()
    except Exception as exc:
        return {"updated": [], "skipped": [], "total_mismatches": 0, "error": str(exc)}

    # Deduplicate lib_ids while tracking references
    seen_lib_ids: dict[str, list[str]] = {}
    for reference, lib_id in all_refs:
        if lib_id and ":" in lib_id:
            seen_lib_ids.setdefault(lib_id, []).append(reference)

    # Filter by requested references
    if references is not None:
        ref_set = set(references)
        filtered: dict[str, list[str]] = {}
        for lib_id, refs in seen_lib_ids.items():
            matching = [r for r in refs if r in ref_set]
            if matching:
                filtered[lib_id] = matching
        seen_lib_ids = filtered

    updated: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for lib_id, refs in seen_lib_ids.items():
        embedded_pins = _get_embedded_pin_signature(ir, lib_id)
        library_pins = _get_library_pin_signature(lib_id, file_path)

        if library_pins is None:
            skipped.append({
                "lib_id": lib_id,
                "references": refs,
                "reason": "library_not_found",
            })
            continue

        if embedded_pins == library_pins:
            continue  # No mismatch

        if dry_run:
            updated.append({
                "lib_id": lib_id,
                "references": refs,
                "action": "would_update",
            })
            continue

        # Re-embed: find the library, load symbol, replace embedded version
        library_name, _, symbol_name = lib_id.partition(":")
        try:
            from kicad_agent.project.lib_table import parse_lib_table

            schematic_dir = file_path.resolve().parent
            library_uri: str | None = None

            for table_path in [
                schematic_dir / "sym-lib-table",
                Path.home() / "Library" / "Preferences" / "kicad" / "10.0" / "sym-lib-table",
                Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/template/sym-lib-table"),
            ]:
                if not table_path.exists():
                    continue
                try:
                    table = parse_lib_table(table_path)
                    entry = table.get(library_name)
                    library_uri = entry.uri.replace(
                        "${KIPRJMOD}", str(schematic_dir.resolve())
                    )
                    break
                except (KeyError, ValueError, FileNotFoundError, OSError):
                    continue

            if library_uri is None:
                skipped.append({
                    "lib_id": lib_id,
                    "references": refs,
                    "reason": "library_path_not_resolved",
                })
                continue

            lib_path = Path(library_uri)
            if not lib_path.exists():
                skipped.append({
                    "lib_id": lib_id,
                    "references": refs,
                    "reason": "library_file_not_found",
                })
                continue

            lib = SymbolLib.from_file(str(lib_path))

            source_symbol = None
            for sym in lib.symbols:
                if sym.libId == lib_id or sym.name == symbol_name:
                    source_symbol = sym
                    break

            if source_symbol is None:
                skipped.append({
                    "lib_id": lib_id,
                    "references": refs,
                    "reason": "symbol_not_in_library",
                })
                continue

            # Replace embedded symbol
            new_symbol = copy.deepcopy(source_symbol)
            new_symbol.libraryNickname = library_name

            for i, existing in enumerate(sch.libSymbols):
                if _match_lib_symbol(existing, lib_id):
                    sch.libSymbols[i] = new_symbol
                    break

            ir._record_mutation("update_symbols_from_library", {
                "lib_id": lib_id,
                "references": refs,
            })

            updated.append({
                "lib_id": lib_id,
                "references": refs,
                "action": "updated",
            })

        except Exception as exc:
            skipped.append({
                "lib_id": lib_id,
                "references": refs,
                "reason": f"error: {exc}",
            })

    return {
        "updated": updated,
        "skipped": skipped,
        "total_mismatches": len(updated) + len(skipped),
    }


def fix_pin_type_mismatches(
    ir: SchematicIR, file_path: Path, *,
    pin_type_map: dict[str, str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Fix pin electrical type mismatches in embedded lib_symbols.

    Updates pin electrical types to resolve pin_to_pin ERC violations.
    Default: change "unspecified" to "passive".

    Args:
        ir: SchematicIR for the target schematic.
        file_path: Resolved path to the schematic file.
        pin_type_map: Override map, defaults to {"unspecified": "passive"}.
        dry_run: If True, report without modifying.

    Returns:
        Dict with pins_changed, details, and lib_ids_affected.
    """
    if pin_type_map is None:
        pin_type_map = {"unspecified": "passive"}

    sch = ir._parse_result.kiutils_obj
    pins_changed: list[dict[str, Any]] = []
    lib_ids_affected: set[str] = set()

    for lib_sym in sch.libSymbols:
        lib_id = getattr(lib_sym, "libId", "")
        for unit in lib_sym.units:
            for pin in unit.pins:
                old_type = pin.electricalType
                new_type = pin_type_map.get(old_type)
                if new_type is not None:
                    if dry_run:
                        pins_changed.append({
                            "lib_id": lib_id,
                            "pin_number": pin.number,
                            "pin_name": pin.name,
                            "old_type": old_type,
                            "new_type": new_type,
                            "dry_run": True,
                        })
                    else:
                        pin.electricalType = new_type
                        pins_changed.append({
                            "lib_id": lib_id,
                            "pin_number": pin.number,
                            "pin_name": pin.name,
                            "old_type": old_type,
                            "new_type": new_type,
                        })
                    lib_ids_affected.add(lib_id)

    if pins_changed and not dry_run:
        ir._record_mutation("fix_pin_type_mismatches", {
            "pins_changed": len(pins_changed),
            "lib_ids": sorted(lib_ids_affected),
        })

    return {
        "pins_changed": pins_changed,
        "total": len(pins_changed),
        "lib_ids_affected": sorted(lib_ids_affected),
    }


def _get_unit_pin_map(lib_sym) -> dict[int, set[str]]:
    """Extract unit_number -> pin_numbers mapping from sub-symbol names.

    KiCad multi-unit symbols define sub-symbols named ``ParentName_X_Y``
    where X is the unit number and Y is the body style.  This helper
    parses those names and returns a mapping from unit number to the set
    of pin numbers defined in that unit.

    Units with zero pins (graphic-only wrappers) are excluded.
    """
    unit_map: dict[int, set[str]] = {}
    for sub_sym in lib_sym.units:
        name = getattr(sub_sym, "libId", "") or ""
        parts = name.rsplit("_", 2)
        if len(parts) < 3:
            continue
        try:
            unit_num = int(parts[-2])
        except ValueError:
            continue

        pin_numbers: set[str] = set()
        for pin in sub_sym.pins:
            if pin.number:
                pin_numbers.add(pin.number)

        if pin_numbers:
            unit_map[unit_num] = pin_numbers

    return unit_map


def _get_unit_pin_offsets(
    lib_sym, unit_num: int
) -> dict[str, tuple[float, float]]:
    """Get pin positions for a specific unit from the lib symbol.

    Returns dict of pin_number -> (px, py) where px, py are relative to
    the component origin (the pin's connection-point position in the lib
    symbol definition).
    """
    for sub_sym in lib_sym.units:
        name = getattr(sub_sym, "libId", "") or ""
        parts = name.rsplit("_", 2)
        if len(parts) < 3:
            continue
        try:
            u = int(parts[-2])
        except ValueError:
            continue
        if u == unit_num:
            return {
                pin.number: (pin.position.X, pin.position.Y)
                for pin in sub_sym.pins
                if pin.number
            }
    return {}


def _find_position_for_unit(
    ir: SchematicIR,
    lib_sym,
    unit_num: int,
    rotation: float,
    wire_endpoints: list[dict[str, Any]],
    label_positions: list[dict[str, Any]],
    center: tuple[float, float] | None = None,
    max_distance: float = 100.0,
    net_index: NetPositionIndex | None = None,
    placed_unit_roots: set[tuple[float, float]] | None = None,
) -> tuple[float, float] | None:
    """Find the component position that aligns a unit's pins with existing nets.

    Phase 66: Uses connectivity-aware scoring when a NetPositionIndex is
    provided.  For each candidate position, calculates where each pin would
    land and scores by how many pins connect to unique nets (not shared with
    already-placed units).  Falls back to spatial wire-endpoint voting when
    no net index is available.

    Uses the Y-inversion pattern from ``get_pin_positions()``:
        absolute = (sx + rot_px, sy - rot_py)
    Reverse: (sx, sy) = (abs_x - rot_px, abs_y + rot_py)

    Args:
        net_index: Optional NetPositionIndex for connectivity-aware scoring.
        placed_unit_roots: Set of union-find component roots for pins of
            already-placed units.  Candidate positions whose pins land on
            these roots are penalized.
    """
    pin_offsets = _get_unit_pin_offsets(lib_sym, unit_num)
    if not pin_offsets:
        return None

    angle_rad = math.radians(rotation)
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)

    # Build anchor points from wire endpoints and label positions
    anchor_points: list[tuple[float, float]] = []
    for wire in wire_endpoints:
        anchor_points.append((wire["start_x"], wire["start_y"]))
        anchor_points.append((wire["end_x"], wire["end_y"]))
    for label in label_positions:
        anchor_points.append((label["x"], label["y"]))

    if not anchor_points:
        return None

    # Filter by proximity to center if provided
    if center is not None:
        cx, cy = center
        max_dist_sq = max_distance * max_distance
        anchor_points = [
            (ax, ay)
            for ax, ay in anchor_points
            if (ax - cx) ** 2 + (ay - cy) ** 2 <= max_dist_sq
        ]
        if not anchor_points:
            return None

    # Collect candidate component positions from all pins x all anchors
    candidate_positions: list[tuple[float, float]] = []
    for _pin_num, (px, py) in pin_offsets.items():
        rot_px = px * cos_a - py * sin_a
        rot_py = px * sin_a + py * cos_a

        for anchor_x, anchor_y in anchor_points:
            cand_x = round((anchor_x - rot_px) * 10) / 10
            cand_y = round((anchor_y + rot_py) * 10) / 10
            candidate_positions.append((cand_x, cand_y))

    if not candidate_positions:
        return None

    # --- Net-aware scoring (Phase 66) ---
    if net_index is not None and placed_unit_roots is not None:
        best_pos: tuple[float, float] | None = None
        best_score = 0

        # Deduplicated candidate positions
        unique_candidates = set(candidate_positions)

        for cand_x, cand_y in unique_candidates:
            score = 0
            for _pin_num, (px, py) in pin_offsets.items():
                rot_px = px * cos_a - py * sin_a
                rot_py = px * sin_a + py * cos_a

                # Y-inversion: absolute = (sx + rot_px, sy - rot_py)
                pin_abs_x = cand_x + rot_px
                pin_abs_y = cand_y - rot_py

                root = net_index.get_component_root((pin_abs_x, pin_abs_y))
                if root is not None and root not in placed_unit_roots:
                    score += 1

            if score > best_score:
                best_score = score
                best_pos = (cand_x, cand_y)

        if best_score >= 2 and best_pos is not None:
            return best_pos

        # Net-aware didn't find a good position -- fall through to spatial
        logger.debug(
            "Net-aware scoring best=%d (need >=2), falling back to spatial",
            best_score,
        )

    # --- Spatial fallback: wire-endpoint voting ---
    pos_counter = Counter(candidate_positions)
    if not pos_counter:
        return None

    best_pos_spatial, count = pos_counter.most_common(1)[0]
    if count >= 2:
        return best_pos_spatial

    return None


def place_missing_units(
    ir: SchematicIR, file_path: Path, *,
    references: list[str] | None = None,
    offset_x: float = 25.4,
    offset_y: float = 0.0,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Place all unplaced units of multi-unit symbols.

    For multi-unit symbols, finds units reported as missing by ERC and places
    them adjacent to the existing unit with configurable spacing.

    Args:
        ir: SchematicIR for the target schematic.
        file_path: Resolved path to the schematic file.
        references: Specific references to fix, or None for all.
        offset_x: Horizontal spacing between units in mm.
        offset_y: Vertical spacing between units in mm.
        dry_run: If True, report without modifying.

    Returns:
        Dict with units_placed and details.
    """
    import copy
    import uuid

    from kicad_agent.ir.schematic_ir import _match_lib_symbol
    from kicad_agent.ops.repair_wires import _round_pos

    sch = ir._parse_result.kiutils_obj

    # Find all components, grouped by reference prefix (multi-unit symbols
    # share the same base reference like U4 with units A, B, C, D)
    components_by_ref: dict[str, list[Any]] = {}
    for comp in sch.schematicSymbols:
        ref_prop = None
        for prop in comp.properties:
            if prop.key == "Reference":
                ref_prop = prop.value
                break
        if ref_prop is None:
            continue

        # Multi-unit references: U4A, U4B etc. Base is U4
        base_ref = ref_prop.rstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
        components_by_ref.setdefault(base_ref, []).append(comp)

    # Filter by requested references
    if references is not None:
        ref_set = set(references)
        components_by_ref = {
            k: v for k, v in components_by_ref.items() if k in ref_set
        }

    units_placed: list[dict[str, Any]] = []

    # Issue #3: track occupied positions across all base_ref iterations
    # to prevent overlapping placements for different ICs.
    _occupied_positions: set[tuple[float, float]] = set()

    # Build net position index for connectivity-aware placement (Phase 66).
    # Try to build from the schematic file; if that fails (e.g. in-memory
    # only), fall back to None which disables net-aware scoring.
    net_index: NetPositionIndex | None = None
    try:
        net_index = NetPositionIndex.from_file(file_path)
    except Exception:
        logger.debug("Could not build NetPositionIndex, using spatial fallback")

    for base_ref, components in components_by_ref.items():
        if len(components) == 0:
            continue

        # Skip KiCad internal/hidden symbols (power flags, off-page connectors, etc.)
        # These have references starting with '#' (e.g. #PWR, #FLG) and are not
        # real multi-unit ICs that need placement.
        if base_ref.startswith("#"):
            continue

        # Get the lib_id from the first component
        lib_id = components[0].libId

        # Find the embedded symbol definition
        # Issue #6: Use _match_lib_symbol for nickname-less lib_symbols
        lib_sym = None
        for ls in sch.libSymbols:
            if _match_lib_symbol(ls, lib_id):
                lib_sym = ls
                break

        if lib_sym is None:
            continue

        # Count available units
        available_units = list(lib_sym.units)

        # KiCad standard library symbols (R, C, L, power, test points) use a
        # 2-unit structure: unit 0 = graphic-only (no pins), unit 1 = component.
        # True multi-unit symbols (NE5532, CD4066BE) have 3+ units or pins on
        # unit 0 (shared power pins).  Skip the fake 2-unit symbols.
        if len(available_units) <= 2 and len(available_units[0].pins) == 0:
            continue  # Single-unit symbol with graphic wrapper

        # Get unit_number -> pin_numbers mapping from sub-symbol names
        unit_pin_map = _get_unit_pin_map(lib_sym)
        if not unit_pin_map:
            continue

        # Determine which unit numbers are placed vs missing.
        # KiCad unit numbers are NOT sequential array indices --
        # NE5532 has units {1, 2, 3} but a component may have
        # only units {1, 3} placed (op-amp A + power).  We must
        # use comp.unit to get the actual KiCad unit number.
        placed_unit_nums = {comp.unit for comp in components}
        missing_unit_nums = sorted(unit_pin_map.keys() - placed_unit_nums)

        if not missing_unit_nums:
            continue  # All units already placed

        # Issue #3: single-unit usage guard.  When only 1 unit is placed but
        # the symbol has multiple units, this is likely intentional single-unit
        # usage (e.g. using one gate of a quad op-amp).  Only place the power
        # unit if it has power pins; skip all other missing units.
        if len(components) == 1 and len(missing_unit_nums) > 1:
            power_unit = max(unit_pin_map.keys())
            if power_unit not in placed_unit_nums:
                # Check if the power unit has power pins
                power_offsets = _get_unit_pin_offsets(lib_sym, power_unit)
                has_power_pins = False
                if power_offsets:
                    # Look for power pins in the library symbol's sub-symbols
                    for sub_sym in lib_sym.units:
                        sub_name = getattr(sub_sym, "libId", "") or ""
                        # Sub-symbol naming: <lib_id>_N_M where N=unit, M=body
                        parts = sub_name.rsplit("_", 2)
                        if len(parts) >= 3:
                            try:
                                u = int(parts[-2])
                            except ValueError:
                                continue
                            if u == power_unit:
                                for pin in sub_sym.pins:
                                    if pin.electricalType in ("power_in", "power_out"):
                                        has_power_pins = True
                                        break
                if has_power_pins:
                    # Only place the power unit, skip other missing units
                    missing_unit_nums = [power_unit]
                else:
                    continue  # Skip: single-unit usage, no power unit needed

        if not missing_unit_nums:
            continue  # All units already placed

        # Get wire endpoints and label positions for position calculation
        wire_endpoints = ir.get_wire_endpoints()
        label_positions = ir.get_label_positions()

        # Get position and rotation of first placed component
        first_comp = components[0]
        rotation = first_comp.position.angle or 0.0

        # Collect union-find component roots for already-placed units' pins.
        # Phase 66: Net-aware scoring uses this to avoid placing a missing
        # unit at a position where its pins would land on the same nets.
        placed_unit_roots: set[tuple[float, float]] = set()
        if net_index is not None:
            angle_rad = math.radians(rotation)
            cos_a = math.cos(angle_rad)
            sin_a = math.sin(angle_rad)
            for comp in components:
                comp_offsets = _get_unit_pin_offsets(lib_sym, comp.unit)
                for _pn, (px, py) in comp_offsets.items():
                    rot_px = px * cos_a - py * sin_a
                    rot_py = px * sin_a + py * cos_a
                    pin_x = comp.position.X + rot_px
                    pin_y = comp.position.Y - rot_py
                    root = net_index.get_component_root((pin_x, pin_y))
                    if root is not None:
                        placed_unit_roots.add(root)

        # Place missing units
        for i, missing_num in enumerate(missing_unit_nums):
            # Phase 66: Net-aware position matching.  Find a position where
            # the missing unit's pins land on nets DIFFERENT from the
            # already-placed units.  Only search near the first placed unit.
            center = (first_comp.position.X, first_comp.position.Y)
            pos = _find_position_for_unit(
                ir, lib_sym, missing_num, rotation,
                wire_endpoints, label_positions,
                center=center, max_distance=100.0,
                net_index=net_index,
                placed_unit_roots=placed_unit_roots,
            )
            if pos is None:
                # Fallback: offset from first unit.  Stacking at the
                # same position is unsafe for dual op-amps (NE5532
                # units 1 and 2 have identical pin offset patterns),
                # so we use a sequential offset instead.
                offset_idx = len(components) + i
                pos = (
                    first_comp.position.X + offset_idx * offset_x,
                    first_comp.position.Y + offset_idx * offset_y,
                )
                # Issue #3: avoid position collisions with previously
                # placed units from other base references.
                pos_key = _round_pos(pos[0], pos[1])
                while pos_key in _occupied_positions:
                    offset_idx += 1
                    pos = (
                        first_comp.position.X + offset_idx * offset_x,
                        first_comp.position.Y + offset_idx * offset_y,
                    )
                    pos_key = _round_pos(pos[0], pos[1])

            new_x, new_y = pos

            if dry_run:
                unit_letter = chr(ord("A") + missing_num - 1)
                units_placed.append({
                    "base_reference": base_ref,
                    "unit_number": missing_num,
                    "unit_letter": unit_letter,
                    "position": [new_x, new_y],
                    "dry_run": True,
                })
                continue

            # Clone the first component and override unit-specific fields
            new_comp = copy.deepcopy(first_comp)
            new_uuid = str(uuid.uuid4())
            new_comp.position.X = new_x
            new_comp.position.Y = new_y
            new_comp.position.angle = rotation

            # Bug B fix: set the correct KiCad unit number.
            # Previously all clones inherited comp.unit=1 from the
            # first component, causing the wrong sub-symbol graphics.
            new_comp.unit = missing_num

            # Update UUID
            if hasattr(new_comp, "uuid"):
                new_comp.uuid = new_uuid

            # Derive reference letter from unit number (1=A, 2=B, 3=C, ...)
            unit_letter = chr(ord("A") + missing_num - 1)
            for prop in new_comp.properties:
                if prop.key == "Reference":
                    prop.value = f"{base_ref}{unit_letter}"
                    break

            sch.schematicSymbols.append(new_comp)

            # Issue #3: record occupied position for deduplication
            _occupied_positions.add(_round_pos(new_x, new_y))

            ir._record_mutation("place_missing_unit", {
                "base_reference": base_ref,
                "unit_number": missing_num,
                "unit_letter": unit_letter,
                "position": [new_x, new_y],
                "uuid": new_uuid,
            })

            units_placed.append({
                "base_reference": base_ref,
                "unit_number": missing_num,
                "unit_letter": unit_letter,
                "position": [new_x, new_y],
                "uuid": new_uuid,
            })

    return {
        "units_placed": units_placed,
        "total": len(units_placed),
    }
