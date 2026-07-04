"""CLI subcommand: kicad-agent check-conventions <schematic> (Plan 03 Task 1).

Phase 111: Run the IEEE 315 / H&H convention catalog against a KiCad schematic.

Usage:
    kicad-agent check-conventions compressor.kicad_sch
    kicad-agent check-conventions compressor.kicad_sch --format json --output report.json
    kicad-agent check-conventions compressor.kicad_sch --apply  # run TRANSFORM conventions
    kicad-agent check-conventions compressor.kicad_sch --config .kicad-agent/conventions.yaml

P0-2 (Council Round 1 fix): Uses REAL APIs:
  - parse_schematic(path)            [NOT parse_schematic_file — does not exist]
  - SchematicRawWriter.apply_mutations  [NOT SchematicIR.serialize — does not exist]

P2-2 (Council Round 1 fix): Rejects non-.kicad_sch paths with exit code 2.
P1-3 (Council Round 1 fix): --apply dedupes violations by rule_id (each
                             TRANSFORM convention's apply() runs at most once).
P101-INV-01: NEVER kiutils.Schematic.to_file().
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from kicad_agent.conventions.catalog import get_v1_catalog
from kicad_agent.conventions.engine import ConventionEngine
from kicad_agent.conventions.layout_view import LayoutView
from kicad_agent.conventions.loader import ConventionConfigLoader
from kicad_agent.conventions.serializers import (
    violations_to_json,
    violations_to_markdown,
    write_json_report,
    write_markdown_report,
)
# P0-2: REAL parser entry point (NOT parse_schematic_file)
from kicad_agent.parser.schematic_parser import parse_schematic
from kicad_agent.parser.types import ParseResult
from kicad_agent.ir.schematic_ir import SchematicIR
# atomic_write imported lazily inside --apply branch to avoid hard dep at import time
# (mirrors Phase 48 design_rules_cmd pattern).

logger = logging.getLogger(__name__)


def check_conventions_command(args: argparse.Namespace) -> int:
    """Execute the check-conventions subcommand.

    Returns:
        0 = no errors, 1 = errors found, 2 = invocation error.
    """
    schematic_path = Path(args.schematic).resolve()

    # P2-2: path traversal mitigation — reject non-.kicad_sch paths early.
    if schematic_path.suffix != ".kicad_sch":
        print(
            f"Error: expected .kicad_sch file, got: {schematic_path.name}",
            file=sys.stderr,
        )
        return 2
    if not schematic_path.is_file():
        print(f"Error: schematic not found: {schematic_path}", file=sys.stderr)
        return 2

    # Config: explicit --config, else auto-discover (bounded by .git per Plan 01 P2-3)
    config_path = getattr(args, "config", None)
    if config_path is None:
        discovered = ConventionConfigLoader.discover()
        config_path = str(discovered) if discovered else None

    loader = ConventionConfigLoader(config_path)
    try:
        config = loader.load()
    except ValueError as e:
        print(f"Config error: {e}", file=sys.stderr)
        return 2

    # P0-2: Build SchematicIR via REAL parse_schematic + SchematicIR(_parse_result=...)
    try:
        parse_result: ParseResult = parse_schematic(schematic_path)
        schematic_ir = SchematicIR(_parse_result=parse_result)
        layout = LayoutView.from_schematic_ir(schematic_ir)
    except Exception as e:  # noqa: BLE001 — surface as invocation error
        print(f"Error parsing schematic: {e}", file=sys.stderr)
        return 2

    engine = ConventionEngine(conventions=get_v1_catalog(), config=config)
    violations = engine.run(layout)

    # --apply: run TRANSFORM conventions and persist via REAL SchematicRawWriter path
    if getattr(args, "apply", False):
        from kicad_agent.io.atomic_write import atomic_write
        from kicad_agent.ops.schematic_raw_writer import SchematicRawWriter

        # Build a rule_id -> Convention lookup over enabled catalog entries.
        catalog = get_v1_catalog()
        catalog_by_rule = {c.rule_id: c for c in catalog if c.rule_id not in config.disabled_conventions}

        # P1-3: dedupe by rule_id so each TRANSFORM convention's apply() runs
        # AT MOST ONCE per call (whole-layout transform semantics).
        seen_rule_ids: set[str] = set()
        current_layout = layout
        for v in violations:
            if v.rule_id in seen_rule_ids:
                continue
            seen_rule_ids.add(v.rule_id)
            conv = catalog_by_rule.get(v.rule_id)
            if conv is None:
                continue
            current_layout = conv.apply(current_layout)

        # P1-4 round-trip: LayoutView.to_mutations() → SchematicRawWriter.apply_mutations
        # → atomic_write. P1-R2-1: to_mutations() emits new_x/new_y (writer ignores
        # angle and legacy x/y keys — see layout_view.py).
        mutations = current_layout.to_mutations()
        if mutations:
            new_raw_content = SchematicRawWriter.apply_mutations(
                parse_result.raw_content, mutations,
            )
            atomic_write(schematic_path, new_raw_content)

    # Output: write to file or stdout
    fmt = getattr(args, "format", "markdown")
    output_path = getattr(args, "output", None)
    if output_path:
        if fmt == "json":
            write_json_report(violations, Path(output_path), str(schematic_path))
        else:
            write_markdown_report(violations, Path(output_path), str(schematic_path))
    else:
        if fmt == "json":
            import json
            print(json.dumps(violations_to_json(violations, str(schematic_path)), indent=2))
        else:
            print(violations_to_markdown(violations, str(schematic_path)))

    has_errors = any(v.severity == "error" for v in violations)
    return 1 if has_errors else 0


def register_parser(subparsers) -> None:
    """Register this subcommand with the parent CLI's subparser group."""
    parser = subparsers.add_parser(
        "check-conventions",
        help=(
            "Run IEEE 315 / H&H convention catalog against a KiCad schematic."
        ),
    )
    parser.add_argument(
        "schematic",
        type=str,
        help="Path to .kicad_sch file to check",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to .kicad-agent/conventions.yaml (default: auto-discover)",
    )
    parser.add_argument(
        "--format",
        choices=["json", "markdown"],
        default="markdown",
        help="Output format (default: markdown)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output file path (default: stdout)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Run TRANSFORM conventions and write modified schematic via "
            "SchematicRawWriter + atomic_write"
        ),
    )
    parser.set_defaults(func=check_conventions_command)
