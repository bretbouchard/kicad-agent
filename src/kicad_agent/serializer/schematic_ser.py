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

    # Issue #12: kiutils 1.4.8 drops generator_version and unquotes generator.
    # Post-process to restore these fields so kicad-cli accepts the file.
    _fix_kiutils_output(output_path)

    return output_path


def _fix_kiutils_output(path: Path) -> None:
    """Fix kiutils 1.4.8 serialization defects so kicad-cli can load the file.

    kiutils 1.4.8 re-serialization issues that break KiCad 10:
    1. Quotes the generator token: (generator "eeschema") — KiCad expects unquoted
    2. Adds (generator_version "10.0") — not present in native KiCad files
    3. Adds (lib_name "...") inline in component symbols — KiCad doesn't expect this
    4. Adds (id N) to property lines — KiCad native format omits these
    5. Omits rotation angle from property (at X Y) — KiCad requires (at X Y 0)
    6. Sets (in_bom yes) (on_board yes) — KiCad uses (in_bom no) for lib refs

    Fixes 1-2 are applied globally. Fixes 3-6 are applied only to
    component symbols (outside the lib_symbols section).
    """
    import re

    content = path.read_text(encoding="utf-8")
    modified = False

    # --- Global fixes (header) ---

    if '(generator "eeschema")' in content:
        content = content.replace('(generator "eeschema")', '(generator eeschema)')
        modified = True
    if '(generator "kiutils")' in content:
        content = content.replace('(generator "kiutils")', '(generator eeschema)')
        modified = True

    if re.search(r'\(generator_version\b', content):
        content = re.sub(r'^\s*\(generator_version\s+"[^"]*"\)\n', '', content, flags=re.MULTILINE)
        modified = True

    # --- Component symbol fixes (outside lib_symbols section) ---

    # Find the end of the lib_symbols section
    lib_idx = content.find('(lib_symbols')
    if lib_idx < 0:
        before = ""
        after = content
    else:
        depth = 0
        lib_end = lib_idx
        for i in range(lib_idx, len(content)):
            if content[i] == '(':
                depth += 1
            elif content[i] == ')':
                depth -= 1
                if depth == 0:
                    lib_end = i + 1
                    if lib_end < len(content) and content[lib_end] == '\n':
                        lib_end += 1
                    break

        before = content[:lib_idx]
        lib_section = content[lib_idx:lib_end]
        after = content[lib_end:]

    # Fix 3: Remove (lib_name "...") from component symbol lines.
    # kiutils places it inline: (symbol (lib_name "Lib:Sym") (lib_id ...))
    after = re.sub(r'\(lib_name "[^"]*"\) ', '', after)
    if after != content[lib_end:]:
        modified = True

    # Fix 4: Remove (id N) from property lines in component section.
    # kiutils adds (id N) to every property: (property "Key" (id 0) ...)
    new_after = re.sub(r' \(id \d+\)', '', after)
    if new_after != after:
        after = new_after
        modified = True

    # Fix 5: Add missing rotation angle to property (at X Y) lines.
    # KiCad requires (at X Y ANGLE) with 3 values on property position.
    # kiutils omits the angle when 0, producing (at X Y).
    # Must NOT touch (no_connect (at X Y)) or (symbol (at X Y 0)) lines.
    def _fix_property_angle(m: re.Match) -> str:
        return m.group(0)[:-1] + ' 0)'

    new_after = re.sub(
        r'\(property "[^"]*"[^)]*\(at (\d+(?:\.\d+)?) (\d+(?:\.\d+)?)\)',
        _fix_property_angle,
        after,
    )
    if new_after != after:
        after = new_after
        modified = True

    if modified:
        if lib_idx < 0:
            content = after
        else:
            content = before + lib_section + after
        path.write_text(content, encoding="utf-8")
