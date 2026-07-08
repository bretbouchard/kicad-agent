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
                # kiutils Symbol class exposes libId (property) and entryName
                # (field). It does NOT have a `name` attribute -- using
                # sym.name raises AttributeError.
                # libId matches qualified IDs ("Device:R"); entryName matches
                # unqualified ("R"). [P0-001 fix] See
                # BUGS/P0-001-update-symbols-from-library-crash.md
                if sym.libId == lib_id or sym.entryName == symbol_name:
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

            # P0-002 fix: ALWAYS check dedup, regardless of whether pos came
            # from _find_position_for_unit or the fallback. The previous code
            # only deduped fallback positions, causing collisions when
            # _find_position_for_unit returned the same position for multiple
            # parent instances (e.g., U30/U31/U32/U33 all getting unit C at
            # the same spot because a shared wire endpoint was within
            # max_distance of each parent). See BUGS/P0-002-place-missing-
            # units-collides-positions.md.
            pos_key = _round_pos(pos[0], pos[1])
            while pos_key in _occupied_positions:
                # Nudge by offset until clear. Use offset_x/offset_y which
                # are the configured unit spacing (default 25.4mm / 0.0mm).
                pos = (
                    pos[0] + offset_x,
                    pos[1] + offset_y,
                )
                pos_key = _round_pos(pos[0], pos[1])

            new_x, new_y = pos

            # P0-002 fix (dry_run): record the occupied position here so the
            # dedup set stays accurate even when dry_run skips the placement
            # branch below. Previously, dry_run mode returned colliding
            # positions because _occupied_positions was only populated at the
            # end of the non-dry-run branch.
            _occupied_positions.add(_round_pos(new_x, new_y))

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


# ---------------------------------------------------------------------------
# Pin-name -> power-rail mapping (ae-47)
# ---------------------------------------------------------------------------

# Positive-supply pin names -> default analog/digital rails.
_POS_PIN_PATTERNS: list[tuple[str, str]] = [
    # (substring, default-rail) — checked in order, normalized lowercase
    ("v+", "+9V"),
    ("vcc", "+9V"),
    ("vdd", "+9V"),
    ("v_{dd}", "+9V"),
    ("v_{cc}", "+9V"),
]
# Negative-supply pin names -> rail.
_NEG_PIN_PATTERNS: list[tuple[str, str]] = [
    ("v-", "-9V"),
    ("vee", "-9V"),
    ("v_{ee}", "-9V"),
]
# Ground pin names -> rail.
_GND_PIN_PATTERNS: list[tuple[str, str]] = [
    ("gnd", "GND"),
    ("vss", "GND"),
    ("v_{ss}", "GND"),
    ("vssb", "GND"),
]

# Digital-domain rails (when the parent IC classifies as digital).
_DIGITAL_POS_RAIL = "+3V3"


def _classify_domain(value: str) -> str:
    """Classify a component value as 'analog' or 'digital'.

    Reuses the ground_topology pattern lists (NE5532/CD4066 are analog;
    MCU/74xx/40xx logic is digital). Conservative: unknown -> analog.
    """
    from kicad_agent.ops.ground_topology import (
        _ANALOG_REF_PATTERNS,
        _DIGITAL_REF_PATTERNS,
    )
    ref_str = value or ""
    if any(p.search(ref_str) for p in _DIGITAL_REF_PATTERNS):
        return "digital"
    return "analog"  # analog or unknown -> analog (conservative for power rails)


def _match_rail(
    pin_name: str,
    domain: str,
    overrides: dict[str, str] | None,
) -> str | None:
    """Resolve a power pin name to its target rail name, or None if not a power pin."""
    norm = (pin_name or "").lower().replace(" ", "")
    # 1. Explicit overrides take precedence (substring match on normalized name).
    if overrides:
        for pat, rail in overrides.items():
            if pat.lower().replace(" ", "") in norm:
                return rail
    # 2. Ground pins (checked before neg so "vss" doesn't catch "vssa" wrongly).
    for pat, rail in _GND_PIN_PATTERNS:
        if pat in norm and "a" not in norm.replace(pat, "", 1):  # avoid VSSA->AGND mismatch
            return rail
    # 3. Negative-supply pins.
    for pat, rail in _NEG_PIN_PATTERNS:
        if pat in norm:
            return rail
    # 4. Positive-supply pins — domain selects the rail.
    for pat, _rail in _POS_PIN_PATTERNS:
        if pat in norm:
            return _DIGITAL_POS_RAIL if domain == "digital" else "+9V"
    return None


def _existing_power_rails(ir: SchematicIR) -> set[str]:
    """Return the set of power-rail names already present on the sheet.

    A rail is present if a power symbol (lib_id starts with "power:") with
    that Value exists. We avoid adding duplicate rail symbols.
    """
    rails: set[str] = set()
    sch = ir._parse_result.kiutils_obj
    for sym in sch.schematicSymbols:
        lib_id = getattr(sym, "libId", "") or ""
        if not lib_id.startswith("power:"):
            continue
        # The rail name is the Value property (== the part after "power:").
        for prop in sym.properties:
            if prop.key == "Value" and prop.value:
                rails.add(prop.value)
                break
    return rails


def _pin_already_wired_to_rail(
    ir: SchematicIR, pin_x: float, pin_y: float, rail: str, grid: float = 1.27
) -> bool:
    """Check if a pin-tip position is already wired to the target power rail.

    Returns True if there's a power symbol of the target rail whose pin
    connects (directly or via a wire chain) to (pin_x, pin_y). Used to avoid
    re-wiring pins that a prior session already connected.

    Conservative: only checks for a wire from (pin_x, pin_y) to a power-symbol
    position within a short distance. Does not do full BFS — sufficient for the
    common case where the rail symbol sits directly above/below the pin.
    """
    import re
    raw = ir._parse_result.raw_content
    # Collect power-symbol positions for the target rail.
    rail_positions: list[tuple[float, float]] = []
    for m in re.finditer(r'\(symbol\s+\(lib_id\s+"power:' + re.escape(rail) + r'"', raw):
        s = m.start()
        # find the (at X Y) within the next ~200 chars
        at_m = re.search(r'\(at\s+([-\d.]+)\s+([-\d.]+)', raw[s:s+400])
        if at_m:
            rail_positions.append((round(float(at_m.group(1))/grid)*grid,
                                   round(float(at_m.group(2))/grid)*grid))
    if not rail_positions:
        return False
    # Collect wire endpoints.
    wires = re.findall(
        r'\(wire \(pts \(xy ([-\d.]+) ([-\d.]+)\) \(xy ([-\d.]+) ([-\d.]+)\)', raw
    )
    pin_pt = (round(pin_x/grid)*grid, round(pin_y/grid)*grid)
    # Check: is there a wire with one endpoint at the pin tip and the other at
    # (or chained to) a rail-symbol position?
    for x1, y1, x2, y2 in wires:
        p1 = (round(float(x1)/grid)*grid, round(float(y1)/grid)*grid)
        p2 = (round(float(x2)/grid)*grid, round(float(y2)/grid)*grid)
        if pin_pt not in (p1, p2):
            continue
        other = p2 if p1 == pin_pt else p1
        if other in rail_positions:
            return True
    return False


def place_and_wire_power_units(
    ir: SchematicIR, file_path: Path, *,
    references: list[str] | None = None,
    offset_x: float = 25.4,
    offset_y: float = 0.0,
    rail_overrides: dict[str, str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Place missing power units of multi-unit ICs AND wire their pins to rails.

    Closes bead ae-47: ``place_missing_units`` places unit C/E but leaves the
    power pins unwired (which previously caused 51 ERC errors). This op places
    the unit, then for each power pin (V+, V-, VDD, VSS, ...) adds a power
    symbol (if the rail isn't already on the sheet) and wires the pin to it.

    See ``PlaceAndWirePowerUnitsOp`` schema docstring for the pin-to-rail map.

    Args:
        ir: SchematicIR for the target schematic.
        file_path: Resolved path to the schematic file.
        references: Specific references to fix, or None for all.
        offset_x/offset_y: Unit spacing passed to place_missing_units.
        rail_overrides: Optional {pin_substring: rail_name} overrides.
        dry_run: If True, report the plan without modifying.

    Returns:
        Dict with units_placed (count), pins_wired (count), rails_added
        (list), and a per-reference detail list.
    """
    # Phase 1: PRE-SCAN to find which ICs need power-unit PLACEMENT.
    # We cannot call place_missing_units on all refs then filter — it WRITES
    # all units (including unwanted signal units like U10A/U10B) to disk before
    # our filter runs. Instead, scan first, then restrict place_missing_units
    # to ONLY the ICs missing their power unit, via the references parameter.
    from kicad_agent.ir.schematic_ir import _match_lib_symbol
    sch = ir._parse_result.kiutils_obj

    def _unit_has_power_pins(lib_sym: Any, unit_num: int) -> bool:
        if lib_sym is None:
            return False
        for sub_sym in lib_sym.units:
            sub_name = getattr(sub_sym, "libId", "") or ""
            parts = sub_name.rsplit("_", 2)
            if len(parts) >= 3:
                try:
                    u = int(parts[-2])
                except ValueError:
                    continue
                if u == unit_num:
                    for p in sub_sym.pins:
                        if getattr(p, "electricalType", "") in ("power_in", "power_out"):
                            return True
        return False

    def _lib_sym_for_ref(ref_val: str):
        """Return the (lib_id, lib_symbol) for a component by reference."""
        for comp in sch.schematicSymbols:
            rv = ""
            for prop in comp.properties:
                if prop.key == "Reference":
                    rv = prop.value
                    break
            if rv == ref_val:
                for ls in sch.libSymbols:
                    if _match_lib_symbol(ls, comp.libId):
                        return comp.libId, ls
                return comp.libId, None
        return None, None

    # Group components by base reference + collect placed units per IC.
    from collections import defaultdict
    comps_by_ref: dict[str, list[Any]] = defaultdict(list)
    for comp in sch.schematicSymbols:
        rv = ""
        for prop in comp.properties:
            if prop.key == "Reference":
                rv = prop.value
                break
        if rv and not rv.startswith("#"):
            base = re.sub(r"[A-Z]$", "", rv) if rv[-1:].isalpha() and len(rv) > 1 else rv
            comps_by_ref[base].append(comp)

    # For each multi-unit IC, determine: does it have a power unit defined,
    # and is that power unit placed? If not placed → needs placement.
    refs_needing_power_placement: list[str] = []
    refs_with_power_placed: list[str] = []  # power unit exists, may need wiring
    for base_ref, comps in comps_by_ref.items():
        if len(comps) < 1:
            continue
        lib_id, lib_sym = _lib_sym_for_ref(base_ref)
        if lib_sym is None:
            continue
        unit_pin_map = _get_unit_pin_map(lib_sym)
        if not unit_pin_map:
            continue
        # Which units have power pins?
        power_units = [u for u in unit_pin_map if _unit_has_power_pins(lib_sym, u)]
        if not power_units:
            continue  # no power unit in this symbol
        placed_units = {c.unit for c in comps}
        has_power_placed = any(u in placed_units for u in power_units)
        # Apply caller's references filter if given.
        if references is not None and base_ref not in references:
            continue
        if has_power_placed:
            refs_with_power_placed.append(base_ref)
        else:
            refs_needing_power_placement.append(base_ref)

    # Phase 1b: place ONLY the power units for ICs missing them.
    placed: list[dict[str, Any]] = []
    if refs_needing_power_placement:
        placement = place_missing_units(
            ir, file_path,
            references=refs_needing_power_placement,
            offset_x=offset_x,
            offset_y=offset_y,
            dry_run=dry_run,
        )
        placed = placement.get("units_placed", [])

    # Phase 2: wire power pins. Process newly-placed units + pre-existing
    # power units (which may be unwired). Skip pins already wired to a rail.
    pins_wired: list[dict[str, Any]] = []
    rails_added: list[str] = []
    existing_rails = _existing_power_rails(ir)
    rails_added_set: set[str] = set()

    # Build the set of power units to wire: newly-placed + pre-existing.
    units_to_wire: list[dict[str, Any]] = list(placed)
    queued = {(u["base_reference"], u["unit_number"]) for u in placed}
    for base_ref in refs_with_power_placed:
        for comp in comps_by_ref.get(base_ref, []):
            _, lib_sym = _lib_sym_for_ref(base_ref)
            if lib_sym and _unit_has_power_pins(lib_sym, comp.unit):
                key = (base_ref, comp.unit)
                if key not in queued:
                    units_to_wire.append({
                        "base_reference": base_ref,
                        "unit_number": comp.unit,
                        "unit_letter": chr(ord("A") + comp.unit - 1),
                        "position": [comp.position.X, comp.position.Y],
                    })
                    queued.add(key)

    if not units_to_wire:
        return {
            "units_placed": len(placed),
            "pins_wired": 0,
            "rails_added": [],
            "details": [],
            "message": "No power units needing placement or wiring.",
        }

    for unit_info in units_to_wire:
        base_ref = unit_info["base_reference"]
        unit_num = unit_info["unit_number"]
        unit_letter = unit_info["unit_letter"]
        ux, uy = unit_info["position"]

        # Find the lib_symbol for this IC to read pin offsets + the parent value.
        lib_id = None
        parent_value = ""
        for comp in sch.schematicSymbols:
            ref_val = ""
            for prop in comp.properties:
                if prop.key == "Reference":
                    ref_val = prop.value
                    break
            if ref_val == base_ref:
                lib_id = comp.libId
            if ref_val == base_ref:
                for prop in comp.properties:
                    if prop.key == "Value":
                        parent_value = prop.value
                        break
        if not lib_id:
            continue

        lib_sym = None
        for ls in sch.libSymbols:
            if _match_lib_symbol(ls, lib_id):
                lib_sym = ls
                break
        if lib_sym is None:
            continue

        domain = _classify_domain(parent_value)
        pin_offsets = _get_unit_pin_offsets(lib_sym, unit_num)
        if not pin_offsets:
            continue

        for pin_num, (px, py) in pin_offsets.items():
            # Read pin name + electrical type from the lib_symbol sub-symbol.
            pin_name = ""
            pin_etype = ""
            for sub_sym in lib_sym.units:
                sub_name = getattr(sub_sym, "libId", "") or ""
                parts = sub_name.rsplit("_", 2)
                if len(parts) >= 3:
                    try:
                        u = int(parts[-2])
                    except ValueError:
                        continue
                    if u == unit_num:
                        for p in sub_sym.pins:
                            if p.number == pin_num:
                                pin_name = p.name
                                pin_etype = getattr(p, "electricalType", "")
                                break
            if pin_etype not in ("power_in", "power_out"):
                continue

            rail = _match_rail(pin_name, domain, rail_overrides)
            if rail is None:
                continue

            # Skip if this pin is ALREADY wired to a power rail. Pre-existing
            # power units (e.g. U10/U11) may already have correct wiring from
            # a prior session; adding a second wire to the same pin creates a
            # different_unit_net conflict (two wires, same pin, same net, but
            # ERC flags the duplicate path). We check whether any existing wire
            # touches the pin tip AND leads to a power symbol of the target rail.
            grid = 1.27
            pre_tip_x = round((ux + px) / grid) * grid
            pre_tip_y = round((uy - py) / grid) * grid
            if _pin_already_wired_to_rail(ir, pre_tip_x, pre_tip_y, rail, grid):
                continue

            # Absolute pin-tip position (Y-inversion, no rotation assumed for
            # power units which are placed at angle 0).
            # CRITICAL: snap to the 1.27mm grid (KiCad default 50mil). Off-grid
            # wires don't connect to pins → pin_not_connected/wire_dangling
            # errors. The place_missing_units offset (25.4mm) is grid-aligned,
            # but _find_position_for_unit can return off-grid wire-endpoint
            # positions. We snap the UNIT position to grid first (and move the
            # placed component to match), so all derived coords are aligned.
            grid = 1.27
            snapped_ux = round(ux / grid) * grid
            snapped_uy = round(uy / grid) * grid
            if not dry_run:
                # Only NEWLY-PLACED units need correction (pre-existing power
                # units like U10/U11 already have correct ref/position/instances).
                # Newly-placed units are identifiable by their suffixed Reference
                # ("{base_ref}{unit_letter}", e.g. "U5C") — place_missing_units
                # adds the suffix; this schematic's convention is base-only.
                placed_ref = f"{base_ref}{unit_letter}"
                for comp in sch.schematicSymbols:
                    ref_val = ""
                    for prop in comp.properties:
                        if prop.key == "Reference":
                            ref_val = prop.value
                            break
                    if ref_val == placed_ref:
                        # Fix: grid-snap position, strip suffix, fix instances unit.
                        comp.position.X = snapped_ux
                        comp.position.Y = snapped_uy
                        for prop in comp.properties:
                            if prop.key == "Reference":
                                prop.value = base_ref
                                break
                        try:
                            for proj in (comp.instances or []):
                                for path_inst in (proj.paths or []):
                                    path_inst.unit = unit_num
                                    path_inst.reference = base_ref
                        except (AttributeError, TypeError):
                            pass
                        break
            ux, uy = snapped_ux, snapped_uy  # use snapped for pin-tip math

            pin_tip_x = round((ux + px) / grid) * grid
            pin_tip_y = round((uy - py) / grid) * grid

            # Place the rail symbol a short offset from the pin tip so the wire
            # is short and unambiguous. The power symbol's pin is at its origin.
            # Offset is grid-aligned (5.08mm = 4 grid units).
            sym_x = pin_tip_x + (offset_x if rail.startswith("+") else -offset_x)
            if rail == "GND":
                sym_x = pin_tip_x
            sym_y = pin_tip_y - 5.08  # 200mil above the pin tip
            sym_x = round(sym_x / grid) * grid
            sym_y = round(sym_y / grid) * grid

            # Track whether this rail is being introduced to the sheet for the
            # first time (for reporting). But ALWAYS place a power-symbol
            # instance at (sym_x, sym_y) — every connection needs its own
            # symbol instance, mirroring how the working schematic has a
            # separate +9V/-9V instance per op-amp. Wiring to an existing
            # symbol elsewhere on the sheet would require long wires; a local
            # symbol instance is how KiCad schematics actually work.
            rails_added_for_pin = False
            if rail not in existing_rails and rail not in rails_added_set:
                rails_added_for_pin = True
                if not dry_run:
                    existing_rails.add(rail)
                rails_added_set.add(rail)
                rails_added.append(rail)

            if not dry_run:
                # Always place the power symbol at the wire start point.
                ir.add_power_symbol(name=rail, x=sym_x, y=sym_y, angle=0.0)
                try:
                    ir.add_wire(sym_x, sym_y, pin_tip_x, pin_tip_y, force=True)
                except Exception as exc:  # net-conflict or duplicate — record, continue
                    logger.warning(
                        "place_and_wire_power_units: wire failed for %s pin %s -> %s: %s",
                        base_ref, pin_num, rail, exc,
                    )

            pins_wired.append({
                "reference": f"{base_ref}{unit_letter}",
                "pin_number": pin_num,
                "pin_name": pin_name,
                "rail": rail,
                "rail_added": rails_added_for_pin,
                "wire": [sym_x, sym_y, pin_tip_x, pin_tip_y],
            })

    return {
        "units_placed": len(placed),
        "pins_wired": len(pins_wired),
        "rails_added": rails_added,
        "details": pins_wired,
        "placement_detail": placed,
        "dry_run": dry_run,
    }

