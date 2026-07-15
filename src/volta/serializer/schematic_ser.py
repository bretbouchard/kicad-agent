"""Schematic (.kicad_sch) file serializer.

Serializes parsed KiCad schematic files back to disk via kiutils.
Schematics do NOT need UUID re-injection -- kiutils preserves schematic UUIDs.

Issue #2: When possible, uses targeted patch serialization to preserve original
file formatting. Falls back to full kiutils re-serialization for complex mutations.

Uses the shared normalizer module for kiutils output fixes (S-BUG-004).
Only schematic-specific fixes (lib_name, property id removal) remain here.

Usage:
    from volta.serializer.schematic_ser import serialize_schematic

    output_path = serialize_schematic(parse_result, Path("output.kicad_sch"))
"""

import logging
import re
from pathlib import Path
from typing import Any

from volta.io.atomic_write import atomic_write
from volta.parser.types import ParseResult
from volta.serializer.normalizer import normalize_kicad_output

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

    Post-processing uses the shared normalizer module (S-BUG-004) for
    generator quoting, generator_version removal, scientific notation,
    at-angle fixes, and whitespace normalization. Schematic-specific
    fixes (lib_name removal, property id removal) are applied separately.

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
        from volta.serializer.patch_serializer import (
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
            # patch_serialize returned None -- fall through to full serialization
            logger.info(
                "Falling back to full serialization for %s (complex mutations)",
                output_path.name,
            )

    # Full kiutils re-serialization
    parse_result.kiutils_obj.to_file(str(output_path))

    # S-BUG-004: Use shared normalizer for kiutils output fixes
    # (generator quoting, generator_version, sci notation, at-angle, whitespace)
    content = output_path.read_text(encoding="utf-8")
    content = normalize_kicad_output(content)

    # Schematic-specific fixes not covered by the normalizer:
    # Fix A: Remove (lib_name "...") from placed component symbols.
    # kiutils places it inline: (symbol (lib_name "Lib:Sym") (lib_id ...))
    # Only apply outside the lib_symbols section.
    content = _remove_lib_name_from_components(content)

    # Fix B: Remove (id N) from property lines in placed components.
    # kiutils adds (id N) to every property: (property "Key" (id 0) ...)
    # Only apply outside the lib_symbols section.
    content = _remove_property_ids_from_components(content)

    # Write via atomic_write for crash safety
    atomic_write(output_path, content)

    return output_path


def _find_lib_symbols_end(content: str) -> int:
    """Find the end position of the (lib_symbols ...) section.

    Returns the index after the closing paren of lib_symbols,
    or 0 if the section doesn't exist (meaning the entire file
    is placed components).
    """
    lib_idx = content.find('(lib_symbols')
    if lib_idx < 0:
        return 0

    depth = 0
    for i in range(lib_idx, len(content)):
        if content[i] == '(':
            depth += 1
        elif content[i] == ')':
            depth -= 1
            if depth == 0:
                end = i + 1
                if end < len(content) and content[end] == '\n':
                    end += 1
                return end
    return 0


def _remove_lib_name_from_components(content: str) -> str:
    """Remove (lib_name "...") tokens from placed component symbols.

    kiutils adds (lib_name "Lib:Sym") inline in component symbol blocks,
    which KiCad native format doesn't include. Only applies to placed
    components (outside the lib_symbols section).
    """
    lib_end = _find_lib_symbols_end(content)
    if lib_end == 0:
        return content

    before = content[:lib_end]
    after = content[lib_end:]
    cleaned = re.sub(r'\(lib_name "[^"]*"\) ', '', after)
    if cleaned == after:
        return content
    return before + cleaned


def _remove_property_ids_from_components(content: str) -> str:
    """Remove (id N) tokens from property lines in placed components.

    kiutils adds (id N) to every property line, which KiCad native
    format omits. Only applies to placed components (outside the
    lib_symbols section).
    """
    lib_end = _find_lib_symbols_end(content)
    if lib_end == 0:
        return content

    before = content[:lib_end]
    after = content[lib_end:]
    cleaned = re.sub(r' \(id \d+\)', '', after)
    if cleaned == after:
        return content
    return before + cleaned
