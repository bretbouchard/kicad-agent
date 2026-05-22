"""Operation executor -- dispatches validated Operation intents to handlers.

Establishes the pattern (executor dispatch, handler function, Transaction
wrapping, IR mutation, serialization) that all subsequent operations follow.

Security (threat model):
- T-04-06: Dispatch uses exact op_type matching; unknown raises ValueError
- T-04-01: UUID generated server-side in handlers

Usage:
    from kicad_agent.ops.executor import OperationExecutor
    from kicad_agent.ops.schema import Operation

    executor = OperationExecutor(base_dir=Path("/project"))
    result = executor.execute(op)
"""

import logging
from pathlib import Path
from typing import Any

from kicad_agent.ir.schematic_ir import SchematicIR
from kicad_agent.ir.transaction import Transaction
from kicad_agent.ops.schema import Operation
from kicad_agent.parser import parse_schematic
from kicad_agent.serializer import normalize_kicad_output, serialize_schematic

logger = logging.getLogger(__name__)


class OperationExecutor:
    """Dispatches validated Operation intents to mutation handlers.

    Each handler call is wrapped in a Transaction for rollback on failure.
    The executor parses the file, creates SchematicIR, calls the handler,
    serializes, normalizes, and commits.

    Args:
        base_dir: Base directory for resolving relative target_file paths.
    """

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir

    def execute(self, op: Operation) -> dict[str, Any]:
        """Execute a validated operation with Transaction wrapping.

        Parses the target file, creates IR, dispatches to handler,
        serializes result, normalizes output, and commits transaction.

        Args:
            op: Validated Operation from the schema.

        Returns:
            Dict with: success, operation, target_file, details.

        Raises:
            ValueError: For unknown op_type (T-04-06).
            FileNotFoundError: If target_file does not exist.
        """
        root = op.root
        file_path = self._base_dir / root.target_file

        if not file_path.exists():
            raise FileNotFoundError(f"Target file not found: {file_path}")

        # Clear IR registry to avoid stale registrations across operations
        from kicad_agent.ir.base import _clear_registry
        _clear_registry()

        # Parse the schematic file
        parse_result = parse_schematic(file_path)
        ir = SchematicIR(_parse_result=parse_result)

        # Wrap in Transaction for rollback on failure
        with Transaction(file_path) as txn:
            # Dispatch to appropriate handler
            details = self._dispatch(
                root.op_type,
                root,
                ir,
                file_path,
            )

            # Serialize mutated IR back to file
            serialize_schematic(parse_result, file_path)

            # Normalize the serialized output
            content = file_path.read_text(encoding="utf-8")
            normalized = normalize_kicad_output(content)
            file_path.write_text(normalized, encoding="utf-8")

            # Commit the transaction
            txn.commit()

        return {
            "success": True,
            "operation": root.op_type,
            "target_file": root.target_file,
            "details": details,
        }

    def _dispatch(
        self,
        op_type: str,
        op: Any,
        ir: SchematicIR,
        file_path: Path,
    ) -> dict[str, Any]:
        """Dispatch to the appropriate handler based on op_type.

        T-04-06: Exact string matching. Unknown op_type raises ValueError.

        Args:
            op_type: The operation type string.
            op: The operation's root model (e.g. AddComponentOp).
            ir: SchematicIR for the target file.
            file_path: Resolved path to the target file.

        Returns:
            Handler result dict.

        Raises:
            ValueError: For unknown op_type.
        """
        # Phase 4 ops with dedicated handler files
        if op_type == "add_component":
            from kicad_agent.ops.add_component import add_component
            return add_component(op, ir, file_path)

        if op_type == "remove_component":
            from kicad_agent.ops.remove_component import remove_component
            return remove_component(op, ir)

        if op_type == "duplicate_component":
            from kicad_agent.ops.duplicate_component import duplicate_component
            return duplicate_component(op, ir)

        if op_type == "array_replicate":
            from kicad_agent.ops.array_replicate import array_replicate
            return array_replicate(op, ir)

        if op_type == "move_component":
            from kicad_agent.ops.move_component import move_component
            file_type = ir.file_type
            return move_component(op, ir, file_type=file_type)

        if op_type == "modify_property":
            from kicad_agent.ops.modify_property import modify_property
            return modify_property(op, ir)

        # Phase 5 ops: net/bus/ref/footprint operations via IR methods
        if op_type == "add_net":
            net = ir.add_net(net_name=op.net_name, net_number=op.net_number)
            return {"net_name": net.name, "net_number": net.number}

        if op_type == "remove_net":
            ir.remove_net(net_name=op.net_name)
            return {"removed_net": op.net_name}

        if op_type == "rename_net":
            ir.rename_net(old_name=op.old_name, new_name=op.new_name)
            return {"old_name": op.old_name, "new_name": op.new_name}

        if op_type == "renumber_refs":
            changes = ir.renumber_references(
                prefix=op.prefix, start_index=op.start_index, step=op.step
            )
            return {"changes": [{"old": o, "new": n} for o, n in changes]}

        if op_type == "validate_refs":
            duplicates = ir.validate_reference_uniqueness()
            return {"duplicates": duplicates, "valid": len(duplicates) == 0}

        if op_type == "annotate":
            changes = ir.annotate_components(prefix_filter=op.prefix_filter)
            return {"annotated": [{"old": o, "new": n} for o, n in changes]}

        if op_type == "cross_ref_check":
            unresolved = ir.cross_reference_check()
            return {"unresolved": [{"ref": r, "lib_id": l} for r, l in unresolved]}

        if op_type == "assign_footprint":
            ir.assign_footprint(reference=op.reference, footprint_lib_id=op.footprint_lib_id)
            return {"reference": op.reference, "footprint": op.footprint_lib_id}

        if op_type == "swap_footprint":
            result = ir.swap_footprint(reference=op.reference, new_footprint_lib_id=op.new_footprint_lib_id)
            return result

        if op_type == "validate_footprint":
            # Schema-level validation only (no IR mutation)
            return {"footprint_lib_id": op.footprint_lib_id, "valid": True}

        if op_type == "verify_pin_map":
            result = ir.verify_pin_map(reference=op.reference, footprint_lib_id=op.footprint_lib_id)
            return result

        # Phase 6 ops: wire, label, power, no-connect, junction
        if op_type == "add_wire":
            result = ir.add_wire(
                start_x=op.start_x, start_y=op.start_y,
                end_x=op.end_x, end_y=op.end_y,
            )
            return result

        if op_type == "add_label":
            result = ir.add_label(
                name=op.name,
                label_type=op.label_type,
                x=op.position.x, y=op.position.y,
                angle=op.position.angle,
                shape=op.shape,
            )
            return result

        if op_type == "add_power":
            result = ir.add_power_symbol(
                name=op.name,
                x=op.position.x, y=op.position.y,
                angle=op.position.angle,
            )
            return result

        if op_type == "add_no_connect":
            result = ir.add_no_connect(
                x=op.position.x, y=op.position.y,
            )
            return result

        if op_type == "add_junction":
            result = ir.add_junction(
                x=op.position.x, y=op.position.y,
            )
            return result

        # Bus ops: schema-only for now (IR methods not yet implemented)
        if op_type == "add_bus":
            return {"bus_name": op.bus_name, "member_count": len(op.member_nets)}

        if op_type == "remove_bus":
            return {"removed_bus": op.bus_name}

        raise ValueError(f"Unknown op_type: {op_type!r}")
