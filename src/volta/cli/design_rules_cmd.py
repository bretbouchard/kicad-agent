"""CLI subcommand: volta design-rules <schematic>

DOMAIN-04: Run domain-specific design rules against a schematic.

Usage:
    volta design-rules compressor.kicad_sch
    volta design-rules compressor.kicad_sch --config design-rules.yaml
    volta design-rules compressor.kicad_sch --format json --output report.json
    volta design-rules compressor.kicad_sch --format markdown --output report.md
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

from volta.analysis.builtin_rules import get_builtin_rules
from volta.analysis.design_rule_engine import DesignRuleEngine
from volta.analysis.rule_config import RuleConfigLoader
from volta.analysis.rule_report import (
    generate_json_report,
    generate_markdown_report,
)

logger = logging.getLogger(__name__)


def design_rules_command(args: argparse.Namespace) -> int:
    """Execute the design-rules subcommand.

    Args:
        args: Parsed CLI arguments with:
            schematic: Path to .kicad_sch file.
            config: Optional path to YAML config.
            format: Output format ("json" or "markdown").
            output: Optional output file path.

    Returns:
        Exit code: 0 if no CRITICAL violations, 1 if CRITICAL found, 2 on error.
    """
    schematic_path = Path(args.schematic)
    if not schematic_path.exists():
        print(f"Error: schematic not found: {schematic_path}", file=sys.stderr)
        return 2

    # Load config
    config_loader = RuleConfigLoader(getattr(args, "config", None))
    try:
        config = config_loader.load()
    except ValueError as e:
        print(f"Config error: {e}", file=sys.stderr)
        return 2

    # Extract topology (Phase 46 integration point)
    try:
        topology = _extract_topology(schematic_path)
    except Exception as e:
        print(f"Error parsing schematic: {e}", file=sys.stderr)
        return 2

    # Run rules
    engine = DesignRuleEngine(
        rules=get_builtin_rules(),
        disabled_rules=config.disabled_rules,
        config=config.rule_configs,
    )
    report = engine.run(topology)

    # Generate output
    output_format = getattr(args, "format", "markdown")
    if output_format == "json":
        output_text = generate_json_report(report)
    else:
        output_text = generate_markdown_report(report)

    # Write output
    output_path = getattr(args, "output", None)
    if output_path:
        Path(output_path).write_text(output_text)
        print(f"Report written to {output_path}")
    else:
        print(output_text)

    # Exit code based on severity
    if report.summary.get("CRITICAL", 0) > 0:
        return 1
    return 0


def _extract_topology(schematic_path: Path) -> Any:
    """Extract CircuitTopology from a schematic file.

    Delegates to the topology extraction pipeline. This is the
    integration point between Phase 46 (topology graph) and
    Phase 48 (design rules).
    """
    from volta.analysis.topology_graph import extract_topology

    return extract_topology(schematic_path)


def register_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the design-rules subcommand with argparse.

    Args:
        subparsers: Subparser group from main CLI.
    """
    parser = subparsers.add_parser(
        "design-rules",
        help="Run domain-specific design rules against a schematic",
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
        help="Path to YAML rule configuration file",
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
    parser.set_defaults(func=design_rules_command)
