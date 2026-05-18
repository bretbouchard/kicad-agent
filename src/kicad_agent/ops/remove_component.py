"""Remove component operation handler.

Removes a SchematicSymbol from a schematic by reference designator.
Cleans up symbol_instances entries and records mutation for audit trail.

Security (threat model):
- T-04-03: Reference must match existing component exactly -- no wildcard
  or pattern deletion.

Usage:
    from kicad_agent.ops.remove_component import remove_component, RemoveComponentError

    op = RemoveComponentOp(
        target_file="schematic.kicad_sch",
        reference="R1",
    )
    result = remove_component(op, ir)
"""

from typing import Any

from kicad_agent.ops.schema import RemoveComponentOp


class RemoveComponentError(Exception):
    """Error raised when remove_component operation fails."""


def remove_component(
    op: RemoveComponentOp,
    ir: Any,
) -> dict[str, Any]:
    """Remove a component from a schematic by reference designator.

    Finds the component by reference, removes it from schematicSymbols,
    cleans up symbol_instances entries, and records the mutation.

    Args:
        op: RemoveComponentOp with target reference.
        ir: SchematicIR wrapping the parsed schematic.

    Returns:
        Dict with removed reference and uuid.

    Raises:
        RemoveComponentError: If component with given reference is not found.
    """
    # T-04-03: Exact reference match, no wildcard/pattern
    component = ir.get_component_by_ref(op.reference)
    if component is None:
        raise RemoveComponentError(
            f"Component not found: {op.reference!r}"
        )

    removed_uuid = component.uuid

    # Remove from schematicSymbols using identity check
    schematic = ir._parse_result.kiutils_obj
    schematic.schematicSymbols = [
        s for s in schematic.schematicSymbols if s is not component
    ]

    # Clean up symbol_instances entries matching this reference
    if schematic.symbolInstances:
        schematic.symbolInstances = [
            inst
            for inst in schematic.symbolInstances
            if not _instance_matches_reference(inst, op.reference)
        ]

    # Record mutation for audit trail
    ir._record_mutation(
        "remove_component",
        {"reference": op.reference, "uuid": removed_uuid},
    )

    return {
        "reference": op.reference,
        "uuid": removed_uuid,
    }


def _instance_matches_reference(instance: Any, reference: str) -> bool:
    """Check if a symbol instance matches the given reference.

    Handles both ProjectInstance (older kiutils) and SymbolProjectInstance
    (newer kiutils) formats.

    Args:
        instance: A kiutils symbol instance object.
        reference: The reference designator to match.

    Returns:
        True if the instance references the given reference designator.
    """
    # ProjectInstance format (name field contains reference)
    if hasattr(instance, "name") and instance.name == reference:
        return True

    # SymbolProjectInstance format (paths list with reference)
    if hasattr(instance, "paths"):
        for path in instance.paths:
            if hasattr(path, "reference") and path.reference == reference:
                return True

    return False
