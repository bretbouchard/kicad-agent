"""Normalize malformed placed symbols so KiCad 10 can load the schematic.

KiCad 10's strict parser rejects placed symbols that are missing any of:
  - ``(dnp no)`` field
  - non-empty ``(property "Value" "...")``
  - ``(pin "<n>" (uuid ...))`` blocks for each declared pin
  - ``(instances ...)`` block with a unique per-project reference
  - rotation field on the symbol-level ``(at X Y R)`` (3 numbers required)

These malformations accumulate when generation scripts (or older kiutils
serializers) produce schematics without filling in every required field.
The Arduino_Mega fixture is the worst case: 129 ``R?`` symbols with no
instances, empty Value, no pin UUIDs — KiCad 10 refuses to load the file.

This module provides ``normalize_placed_symbols(raw_content)`` which
repairs every malformed placed symbol in place. It is:
  - Idempotent (re-running on a normalized file is a no-op)
  - Conservative (only adds missing fields; never removes or reorders)
  - Annotation-aware (assigns unique R1/R2/... references to ``R?`` wildcards)

Used by both:
  - ``scripts/repair_arduino_mega_fixture.py`` (one-shot fixture repair)
  - ``ops/handlers/autolayout.py`` (pre-placement normalization step,
    so the autolayout pipeline always works on well-formed symbols)
"""
from __future__ import annotations

import logging
import re
import uuid as uuid_module
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Matches placed symbols: (symbol (lib_id "...") (at X Y [R]) ...)
# Distinct from library definitions inside (lib_symbols ...) which start
# with (symbol "lib_id:name" ...).
_SYMBOL_START_RE = re.compile(r'\(symbol\s+\(lib_id\b')

# Root sheet UUID — indented 2 spaces in KiCad's standard layout.
_ROOT_UUID_RE = re.compile(r'^\s*\(uuid\s+([0-9a-fA-F-]+)\)', re.MULTILINE)

# Project name — read from any existing (instances (project "...")).
_PROJECT_RE = re.compile(r'\(instances\s+\(project\s+"([^"]+)"')

# Matches a (property "Reference" "X") to extract the reference designator.
_REF_RE = re.compile(r'\(property\s+"Reference"\s+"([^"]+)"')


@dataclass
class NormalizeStats:
    """Result of a normalization pass. All counts are >= 0.

    Mutable internally so each repair step can increment fields
    independently without rebuilding the whole dataclass.
    """
    symbols_normalized: int = 0       # blocks that got at least one fix
    wildcards_annotated: int = 0      # R? -> R1, R2, ... renames
    rotation_fixes: int = 0           # (at X Y) -> (at X Y 0)
    instances_added: int = 0          # (instances ...) blocks inserted
    pin_uuids_added: int = 0          # (pin "n" (uuid ...)) blocks inserted
    dnp_added: int = 0                # (dnp no) fields inserted
    values_populated: int = 0         # (property "Value" "") -> (property "Value" "R")

    def add(self, **kwargs: int) -> None:
        """Increment one or more fields. Mutates in place."""
        for key, delta in kwargs.items():
            setattr(self, key, getattr(self, key) + delta)


def _walk_block(content: str, start: int) -> int | None:
    """Return index after the closing paren of the S-expr block at ``start``."""
    depth = 0
    i = start
    while i < len(content):
        c = content[i]
        if c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return None


def _next_ref_for_prefix(prefix: str, used_refs: set[str]) -> str:
    """Return the next free ``<prefix><N>`` reference (R1, R2, ...)."""
    n = 1
    while f"{prefix}{n}" in used_refs:
        n += 1
    ref = f"{prefix}{n}"
    used_refs.add(ref)
    return ref


def _normalize_block(
    block: str,
    root_uuid: str,
    project_name: str,
    used_refs: set[str],
) -> tuple[str, NormalizeStats]:
    """Normalize a single placed (symbol (lib_id ...)) block.

    Returns ``(repaired_block, stats)``. The stats reflect only the changes
    made to THIS block. Idempotent: a block that already has every required
    field returns ``(block, NormalizeStats())`` with all-zero counts.
    """
    s = NormalizeStats()
    ref_match = _REF_RE.search(block)
    if ref_match is None:
        return block, s  # no Reference property — can't normalize, leave alone

    ref = ref_match.group(1)
    prefix = re.match(r'([A-Za-z]+)', ref)
    prefix_str = prefix.group(1) if prefix else "X"

    # --- 1. Fix missing rotation on symbol-level (at X Y) -> (at X Y 0) ---
    before = block
    block = re.sub(
        r'(\(symbol\s+\(lib_id\s+"[^"]+"\)\s+\(at\s+[-\d.]+\s+[-\d.]+)\)',
        r'\1 0)',
        block,
        count=1,
    )
    if block != before:
        s.add(symbols_normalized=1, rotation_fixes=1)

    # --- 2. Add (dnp no) if missing ---
    if '(dnp' not in block:
        before = block
        block = block.replace(
            '(on_board no)\n', '(on_board no) (dnp no)\n', 1,
        )
        if '(dnp' not in block:
            block = block.replace(
                '(on_board no)', '(on_board no) (dnp no)', 1,
            )
        if block != before:
            s.add(symbols_normalized=1, dnp_added=1)

    # --- 3. Populate empty Value ---
    if '(property "Value" ""' in block:
        block = block.replace(
            '(property "Value" ""', f'(property "Value" "{prefix_str}"', 1,
        )
        s.add(symbols_normalized=1, values_populated=1)

    # --- 4. Annotate wildcards (R? -> R1, R2, ...) ---
    if '?' in ref:
        new_ref = _next_ref_for_prefix(prefix_str, used_refs)
        block = block.replace(
            f'(property "Reference" "{ref}"',
            f'(property "Reference" "{new_ref}"',
            1,
        )
        ref = new_ref
        s.add(symbols_normalized=1, wildcards_annotated=1)

    # --- 5. Add pin UUID blocks if missing ---
    if '(pin "' not in block:
        # Device:R_Small_US and Device:C_Small_US have 2 pins. Default to
        # 2 pins for passives; the lib_symbols section has the truth but
        # we don't have it in scope here. 2 covers the vast majority of
        # corrupt fixtures (R/C stacks).
        pin_block = (
            f'    (pin "1" (uuid {uuid_module.uuid4()}))\n'
            f'    (pin "2" (uuid {uuid_module.uuid4()}))\n'
        )
        last_close = block.rfind(')')
        insert_point = last_close
        while insert_point > 0 and block[insert_point - 1] in ' \t':
            insert_point -= 1
        block = block[:insert_point] + pin_block + block[insert_point:]
        s.add(symbols_normalized=1, pin_uuids_added=2)

    # --- 6. Add (instances ...) block if missing ---
    if '(instances' not in block:
        instances_block = (
            f'    (instances\n'
            f'      (project "{project_name}"\n'
            f'        (path "/{root_uuid}"\n'
            f'          (reference "{ref}") (unit 1)\n'
            f'        )\n'
            f'      )\n'
            f'    )\n'
        )
        last_close = block.rfind(')')
        insert_point = last_close
        while insert_point > 0 and block[insert_point - 1] in ' \t':
            insert_point -= 1
        block = block[:insert_point] + instances_block + block[insert_point:]
        s.add(symbols_normalized=1, instances_added=1)

    return block, s


def normalize_placed_symbols(
    raw_content: str,
    project_name: str | None = None,
    root_uuid: str | None = None,
) -> tuple[str, NormalizeStats]:
    """Normalize every malformed placed symbol in ``raw_content``.

    Args:
        raw_content: Raw ``.kicad_sch`` S-expression text.
        project_name: Project name for ``(instances (project "..."))`` blocks.
            If ``None``, read from an existing instances block; fall back to
            ``"project"`` if none exists.
        root_uuid: Root sheet UUID for the ``(path "/<uuid>")`` in instances.
            If ``None``, read from the file's top-level ``(uuid ...)``.

    Returns:
        ``(new_content, NormalizeStats)``. Idempotent — running on an
        already-normalized file returns it unchanged with zero stats.
    """
    # Resolve root_uuid + project_name dynamically if not provided.
    if root_uuid is None:
        m = _ROOT_UUID_RE.search(raw_content)
        root_uuid = m.group(1) if m else "00000000-0000-0000-0000-000000000000"
    if project_name is None:
        m = _PROJECT_RE.search(raw_content)
        project_name = m.group(1) if m else "project"

    # Collect existing references so wildcard annotation doesn't collide.
    used_refs: set[str] = set()
    for m in _REF_RE.finditer(raw_content):
        ref = m.group(1)
        if '?' not in ref:
            used_refs.add(ref)

    # Walk every placed symbol; normalize in place.
    repairs: list[tuple[int, int, str]] = []
    total = NormalizeStats()
    for m in _SYMBOL_START_RE.finditer(raw_content):
        start = m.start()
        end = _walk_block(raw_content, start)
        if end is None:
            continue
        block = raw_content[start:end]
        repaired, stats = _normalize_block(
            block, root_uuid, project_name, used_refs,
        )
        if repaired != block:
            repairs.append((start, end, repaired))
            total.add(
                symbols_normalized=stats.symbols_normalized,
                wildcards_annotated=stats.wildcards_annotated,
                rotation_fixes=stats.rotation_fixes,
                instances_added=stats.instances_added,
                pin_uuids_added=stats.pin_uuids_added,
                dnp_added=stats.dnp_added,
                values_populated=stats.values_populated,
            )

    if not repairs:
        return raw_content, total

    # Apply repairs in reverse so offsets stay valid.
    new_content = raw_content
    for start, end, repaired in reversed(repairs):
        new_content = new_content[:start] + repaired + new_content[end:]
    return new_content, total
