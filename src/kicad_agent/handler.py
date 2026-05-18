"""Skill handler: validates JSON operation requests and routes them.

The handler is the bridge between the GSD Skill interface and the
kicad-agent Python backend.  It receives a JSON string from Claude,
validates it against the Pydantic operation schema, and returns a
structured result.

**This module does NOT execute mutations.**  It validates and prepares
operations; actual IR mutations will be wired in Phase 4+ when
operation executors exist.

Public API::

    from kicad_agent.handler import validate_operation, handle_operation, format_result
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Union

from pydantic import ValidationError

from kicad_agent.ops.schema import Operation
from kicad_agent.result import OperationError, OperationResult


def validate_operation(
    json_str: str,
) -> tuple[Operation | None, OperationError | None]:
    """Parse and validate a JSON operation string.

    Args:
        json_str: Raw JSON string from the skill interface.

    Returns:
        ``(Operation, None)`` on success, ``(None, OperationError)``
        on failure.  Error messages include actionable suggestions.
    """
    # -- Step 1: Parse JSON --
    try:
        parsed = json.loads(json_str)
    except json.JSONDecodeError as exc:
        return None, OperationError(
            success=False,
            operation_type="unknown",
            error=f"Invalid JSON syntax: {exc}",
            suggestion="Check that your JSON is well-formed. Ensure all strings are quoted, brackets are closed, and there are no trailing commas.",
        )

    # -- Step 2: Validate against Pydantic schema --
    try:
        op = Operation.model_validate({"root": parsed})
    except ValidationError as exc:
        # Extract a readable error message from the first error
        first_err = exc.errors()[0] if exc.errors() else {}
        field = first_err.get("loc", ("unknown",))
        field_name = field[-1] if field else "unknown"
        msg = first_err.get("msg", str(exc))
        error_type = first_err.get("type", "value_error")

        # Determine the op_type if available for better error context
        op_type = parsed.get("op_type", "unknown")

        # Provide targeted suggestions based on error type
        if "path" in str(msg).lower() or "traversal" in str(msg).lower() or "'.'" in str(msg):
            suggestion = "Use a relative path without '..' components. Only .kicad_sch, .kicad_pcb, .kicad_sym, and .kicad_mod files are allowed."
        elif error_type == "missing":
            suggestion = f"Add the required field '{field_name}' to your operation. Check the operation schema for required fields."
        elif "literal" in error_type.lower() or "op_type" in str(field):
            suggestion = f"'{parsed.get('op_type', '?')}' is not a valid op_type. Use one of the supported operation types (e.g., add_component, remove_component, move_component)."
        else:
            suggestion = f"Check the operation fields against the schema. Error in '{field_name}': {msg}"

        return None, OperationError(
            success=False,
            operation_type=op_type,
            error=f"Validation error: {msg}",
            suggestion=suggestion,
        )
    except Exception as exc:
        return None, OperationError(
            success=False,
            operation_type=parsed.get("op_type", "unknown"),
            error=f"Unexpected error: {exc}",
            suggestion="Check your operation JSON structure and try again.",
        )

    return op, None


def handle_operation(
    json_str: str,
    project_dir: Path | None = None,
) -> Union[OperationResult, OperationError]:
    """Validate an operation and return a structured result.

    Currently validates the operation and returns a success result
    indicating the operation was validated and queued.  Actual
    mutation dispatch will be wired in Phase 4+ when operation
    executors exist.

    Args:
        json_str: Raw JSON string from the skill interface.
        project_dir: Optional project directory for file resolution.

    Returns:
        ``OperationResult`` on success, ``OperationError`` on failure.
    """
    op, err = validate_operation(json_str)
    if err is not None:
        return err

    # Extract the concrete operation from the discriminated union
    concrete = op.root

    # Build details from the operation fields
    details: dict[str, Any] = {}
    for field_name in type(concrete).model_fields:
        if field_name in ("op_type", "target_file"):
            continue
        value = getattr(concrete, field_name)
        if value is not None:
            details[field_name] = value

    return OperationResult(
        success=True,
        operation_type=concrete.op_type,
        target_file=concrete.target_file,
        message="Operation validated and queued for execution",
        details=details,
    )


def format_result(result: Union[OperationResult, OperationError]) -> str:
    """Format a result into a human-readable string.

    Args:
        result: An ``OperationResult`` or ``OperationError``.

    Returns:
        Formatted text suitable for display.
    """
    return result.to_text()
