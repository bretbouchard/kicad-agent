"""Schematic (.kicad_sch) file serializer.

Serializes parsed KiCad schematic files back to disk via kiutils.
Schematics do NOT need UUID re-injection -- kiutils preserves schematic UUIDs.

Issue #2: When possible, uses targeted patch serialization to preserve original
file formatting. Falls back to full kiutils re-serialization for complex mutations.

Usage:
    from kicad_agent.serializer.schematic_ser import serialize_schematic

    output_path = serialize_schematic(parse_result, Path("output.kicad_sch"))
"""

import logging
from pathlib import Path
from typing import Any

from kicad_agent.parser.types import ParseResult

logger = logging.getLogger(__name__)


def serialize_schematic(
    parse_result: ParseResult,
    output_path: Path,
    *,
    ir: Any = None,
) -> Path:
    """Serialize a parsed schematic back to a .kicad_sch file.

    Issue #2: Tries targeted patch serialization first to preserve original
    formatting. Falls back to full kiutils re-serialization when mutations
    are too complex for patching (symbol additions, removals, etc.).

    Args:
        parse_result: ParseResult from parse_schematic().
        output_path: Target file path for the serialized schematic.
        ir: Optional SchematicIR for mutation-aware patch serialization.

    Returns:
        The output path (same as input output_path).
    """
    if parse_result.file_type != "schematic":
        raise ValueError(
            f"Expected file_type='schematic', got file_type={parse_result.file_type!r}"
        )

    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Issue #2: Try patch serialization first
    if ir is not None and parse_result.raw_content:
        from kicad_agent.serializer.patch_serializer import (
            can_patch_serialize,
            patch_serialize,
        )
        mutation_log = ir.mutation_log
        if mutation_log and can_patch_serialize(mutation_log):
            patched = patch_serialize(
                parse_result.raw_content,
                mutation_log,
                parse_result.kiutils_obj,
            )
            if patched is not None:
                output_path.write_text(patched)
                logger.info(
                    "Patch serialization: applied %d mutations to %s "
                    "(formatting preserved)",
                    len(mutation_log), output_path.name,
                )
                return output_path
            # patch_serialize returned None — fall through to full serialization
            logger.info(
                "Falling back to full serialization for %s (complex mutations)",
                output_path.name,
            )

    # Full kiutils re-serialization (original behavior)
    parse_result.kiutils_obj.to_file(str(output_path))
    return output_path
