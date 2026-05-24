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

    # Collect training data from GitHub
    kicad-agent collect --max-repos 100
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from kicad_agent.handler import format_result, handle_operation, validate_operation
from kicad_agent.ops.schema import get_operation_schema

_SUBCOMMANDS = {"collect"}


def _build_operation_parser() -> argparse.ArgumentParser:
    """Parser for the legacy operation mode."""
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


def _build_collect_parser() -> argparse.ArgumentParser:
    """Parser for the 'collect' subcommand."""
    parser = argparse.ArgumentParser(
        prog="kicad-agent collect",
        description="Collect real-world KiCad training data from GitHub.",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("GITHUB_TOKEN"),
        help="GitHub PAT with public_repo scope (default: GITHUB_TOKEN env var).",
    )
    parser.add_argument(
        "--max-repos",
        type=int,
        default=500,
        help="Maximum repos to discover (default: 500).",
    )
    parser.add_argument(
        "--staging-dir",
        type=Path,
        default=Path("kicad_staging"),
        help="Local dir for downloaded files (default: kicad_staging).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("training_output/real_boards"),
        help="Output dir for train/val/test JSONL (default: training_output/real_boards).",
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


def _handle_collect(argv: list[str]) -> None:
    """Handle the 'collect' subcommand."""
    parser = _build_collect_parser()
    args = parser.parse_args(argv)

    if not args.token:
        print("Error: --token or GITHUB_TOKEN env var required", file=sys.stderr)
        sys.exit(1)

    from kicad_agent.training.real_dataset import run_pipeline

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    args.staging_dir.mkdir(parents=True, exist_ok=True)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    dataset = run_pipeline(
        token=args.token,
        staging_dir=args.staging_dir,
        max_repos=args.max_repos,
        output_dir=args.output_dir,
    )

    meta = dataset.metadata
    print(f"\nCollection complete: {len(dataset)} samples")
    print(f"  Discovered:    {meta.get('n_discovered', 0)} file pairs")
    print(f"  Parsed:        {meta.get('n_parsed', 0)} boards")
    print(f"  Duplicates:    {meta.get('n_duplicates_removed', 0)} removed")
    print(f"  Low quality:   {meta.get('n_quality_removed', 0)} removed")
    print(f"  Difficulty:    {dict(dataset.difficulty_counts)}")
    print(f"  Output:        {args.output_dir}/")

    sys.exit(0)


def main(argv: list[str] | None = None) -> None:
    """Entry point for the kicad-agent CLI."""
    if argv is None:
        argv = sys.argv[1:]

    # Route subcommands to their own parsers
    if argv and argv[0] in _SUBCOMMANDS:
        subcmd = argv[0]
        subcmd_argv = argv[1:]
        if subcmd == "collect":
            _handle_collect(subcmd_argv)
        return

    # Legacy operation mode
    parser = _build_operation_parser()
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
