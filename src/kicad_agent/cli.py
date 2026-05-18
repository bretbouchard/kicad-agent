"""CLI wrapper for kicad-agent -- run operations from the terminal.

Usage examples::

    # Print the operation JSON Schema
    kicad-agent --schema

    # Run an operation from inline JSON
    kicad-agent '{"op_type": "add_component", ...}'

    # Run an operation from a file
    kicad-agent operation.json

    # Validate without executing
    kicad-agent --dry-run operation.json

    # Specify project directory
    kicad-agent -p /path/to/project operation.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from kicad_agent.handler import format_result, handle_operation, validate_operation
from kicad_agent.ops.schema import get_operation_schema


def _build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser."""
    parser = argparse.ArgumentParser(
        prog="kicad-agent",
        description="Run kicad-agent operations from the terminal.",
    )

    parser.add_argument(
        "operation",
        nargs="?",
        default=None,
        help=(
            "JSON string or path to a JSON file containing the operation. "
            "If the argument starts with '{', it is treated as inline JSON; "
            "otherwise, it is treated as a file path."
        ),
    )

    parser.add_argument(
        "--project-dir",
        "-p",
        type=Path,
        default=None,
        help="Project directory (defaults to current working directory).",
    )

    parser.add_argument(
        "--schema",
        "-s",
        action="store_true",
        help="Print the operation JSON Schema and exit.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the operation without executing.",
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print detailed output including operation details dict.",
    )

    return parser


def _read_operation(raw: str) -> str:
    """Read operation JSON from inline string or file path.

    Args:
        raw: Either an inline JSON string (starts with ``{``) or a file path.

    Returns:
        The JSON string to validate.

    Raises:
        SystemExit: If the file cannot be read.
    """
    if raw.startswith("{"):
        return raw

    path = Path(raw)
    if not path.exists():
        print(f"Error: file not found: {raw}", file=sys.stderr)
        sys.exit(1)

    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"Error reading file: {exc}", file=sys.stderr)
        sys.exit(1)


def main(argv: list[str] | None = None) -> None:
    """Entry point for the kicad-agent CLI."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    # --schema: print schema and exit
    if args.schema:
        schema = get_operation_schema()
        print(json.dumps(schema, indent=2))
        sys.exit(0)

    # Require an operation argument if not --schema
    if args.operation is None:
        parser.error("the following arguments are required: operation")

    # Read the operation JSON
    json_str = _read_operation(args.operation)

    # Resolve project directory
    project_dir = args.project_dir

    # --dry-run: validate only
    if args.dry_run:
        _op, err = validate_operation(json_str)
        if err is not None:
            print(format_result(err), file=sys.stderr)
            sys.exit(1)
        print("Validation passed.")
        sys.exit(0)

    # Execute the operation
    result = handle_operation(json_str, project_dir=project_dir)

    if args.verbose and hasattr(result, "details"):
        output = format_result(result)
        if result.details:
            output += "\n  Details:"
            for key, value in result.details.items():
                output += f"\n    {key}: {value}"
        print(output)
    else:
        print(format_result(result))

    sys.exit(0 if result.success else 1)


if __name__ == "__main__":
    main()
