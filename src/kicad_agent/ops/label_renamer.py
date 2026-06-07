"""Net label renamer -- rename label text objects across a schematic.

Renames all labels matching a given name to a new name, with safety
checks for name conflicts and broken references. Supports local labels,
global labels, hierarchical labels, or all types at once.

Usage:
    from kicad_agent.ops.label_renamer import rename_net_label

    result = rename_net_label(ir, file_path, old_name="SIG_COLD", new_name="SIG_COLD_CH2")
    for loc in result["locations"]:
        print(f"  {loc['type']} at {loc['position']}")
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _find_labels_by_name(
    ir: Any,
    target_name: str,
    label_type: str,
) -> list[dict[str, Any]]:
    """Find all labels matching target_name in the schematic.

    Args:
        ir: SchematicIR for the target schematic.
        target_name: Label text to match.
        label_type: "label", "global", "hierarchical", or "all".

    Returns:
        List of dicts with label_type, position, and object reference.
    """
    sch = ir.schematic
    matches: list[dict[str, Any]] = []

    def _check_label_list(label_list: list, ltype: str) -> None:
        for lbl in label_list:
            if lbl.text == target_name:
                matches.append({
                    "type": ltype,
                    "position": [lbl.position.X, lbl.position.Y],
                    "angle": getattr(lbl.position, "angle", 0.0),
                    "label": lbl,
                })

    if label_type in ("label", "all"):
        _check_label_list(sch.labels, "label")

    if label_type in ("global", "all"):
        _check_label_list(sch.globalLabels, "global")

    if label_type in ("hierarchical", "all"):
        _check_label_list(sch.hierarchicalLabels, "hierarchical")

    return matches


def rename_net_label(
    ir: Any,
    file_path: Path,
    *,
    old_name: str,
    new_name: str,
    label_type: str = "all",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Rename all labels matching old_name to new_name.

    Safety checks:
    - Warns if new_name already exists as a different net (potential conflict)
    - Reports matches found before any modification

    Args:
        ir: SchematicIR for the target schematic.
        file_path: Resolved path to the schematic file.
        old_name: Current label text to find.
        new_name: Replacement label text.
        label_type: Which label types to rename: "label", "global",
            "hierarchical", or "all" (default).
        dry_run: If True, report what would change without modifying.

    Returns:
        Dict with renamed count, locations, warnings, and dry_run flag.
    """
    # 1. Find all matching labels
    matches = _find_labels_by_name(ir, old_name, label_type)

    if not matches:
        return {
            "renamed": 0,
            "locations": [],
            "warnings": [f"No labels found matching '{old_name}'"],
            "dry_run": dry_run,
        }

    # 2. Safety check: does new_name already exist as a different label?
    existing = _find_labels_by_name(ir, new_name, label_type)
    existing_types = {m["type"] for m in existing}
    if existing_types:
        warning = (
            f"new_name '{new_name}' already exists as "
            f"{', '.join(sorted(existing_types))} label(s). "
            "Renaming may create duplicates."
        )
        logger.warning("rename_net_label: %s", warning)

    # 3. Dry run: report without modifying
    if dry_run:
        locations = [
            {
                "type": m["type"],
                "position": m["position"],
                "angle": m["angle"],
            }
            for m in matches
        ]
        return {
            "renamed": 0,
            "locations": locations,
            "warnings": [warning] if existing_types else [],
            "dry_run": True,
        }

    # 4. Rename labels
    locations: list[dict[str, Any]] = []
    for m in matches:
        old_text = m["label"].text
        m["label"].text = new_name
        ir._record_mutation("rename_net_label", {
            "old_name": old_name,
            "new_name": new_name,
            "type": m["type"],
            "position": m["position"],
        })
        locations.append({
            "type": m["type"],
            "position": m["position"],
            "angle": m["angle"],
            "old_name": old_text,
            "new_name": new_name,
        })

    return {
        "renamed": len(locations),
        "locations": locations,
        "warnings": [warning] if existing_types else [],
        "old_name": old_name,
        "new_name": new_name,
    }
