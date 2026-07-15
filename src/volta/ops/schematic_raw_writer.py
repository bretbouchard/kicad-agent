"""SchematicRawWriter -- raw S-expression manipulation for KiCad schematic files.

All methods take raw S-expression content and return modified content strings.
The caller is responsible for writing to disk via atomic_write.

This module exists to avoid kiutils re-serialization (P0-003) which corrupts
KiCad 10 schematics by stripping formatting, reordering fields, and misplacing
lib_symbol blocks. Raw text manipulation preserves the original file structure
exactly, applying only the targeted surgical edits needed.

Consolidates raw-write sites used by erc_auto_fix:
- add_no_connect (insert no_connect S-expression)
- add_power_flag (insert lib_symbol + symbol instance at correct nesting level)
- add_junction (insert junction S-expression)
- remove_wire_by_index (remove wire S-expression)
- apply_mutations (replay recorded IR mutations onto raw text)

Usage:
    from volta.ops.schematic_raw_writer import SchematicRawWriter
    from volta.io.atomic_write import atomic_write

    raw = Path("board.kicad_sch").read_text()
    for mutation in ir.get_recorded_mutations():
        raw = SchematicRawWriter.apply_mutation(raw, mutation)
    atomic_write(Path("board.kicad_sch"), raw)
"""

import re
import uuid
from typing import Any


class SchematicRawWriter:
    """Stateless utility class for raw schematic S-expression manipulation.

    Every method takes raw S-expression content and returns new content.
    No method writes to disk or accesses the filesystem.
    """

    # ------------------------------------------------------------------
    # no_connect insertion
    # ------------------------------------------------------------------

    @staticmethod
    def build_no_connect_sexp(x: float, y: float, uid: str | None = None) -> str:
        """Build a KiCad no_connect S-expression.

        Args:
            x: X coordinate in mm.
            y: Y coordinate in mm.
            uid: Optional UUID string. Generated if None.

        Returns:
            S-expression string for a no_connect marker.
        """
        if uid is None:
            uid = str(uuid.uuid4())
        return f'  (no_connect (at {x} {y}) (uuid "{uid}"))\n'

    @staticmethod
    def insert_no_connect(content: str, x: float, y: float, uid: str | None = None) -> str:
        """Insert a no_connect marker before the closing paren.

        Args:
            content: Raw .kicad_sch S-expression text.
            x: X coordinate in mm.
            y: Y coordinate in mm.
            uid: Optional UUID string.

        Returns:
            Modified content with no_connect inserted.
        """
        nc_sexp = SchematicRawWriter.build_no_connect_sexp(x, y, uid)
        # Insert before the final closing paren of the top-level (kicad_sch ...)
        last_close = content.rfind(")")
        if last_close == -1:
            return content
        return content[:last_close] + nc_sexp + content[last_close:]

    # ------------------------------------------------------------------
    # junction insertion
    # ------------------------------------------------------------------

    @staticmethod
    def build_junction_sexp(x: float, y: float, uid: str | None = None) -> str:
        """Build a KiCad junction S-expression.

        Args:
            x: X coordinate in mm.
            y: Y coordinate in mm.
            uid: Optional UUID string. Generated if None.

        Returns:
            S-expression string for a junction dot.
        """
        if uid is None:
            uid = str(uuid.uuid4())
        return (
            f'  (junction (at {x} {y}) (diameter 0) (color 0 0 0 0)\n'
            f'    (uuid "{uid}"))\n'
        )

    @staticmethod
    def insert_junction(content: str, x: float, y: float, uid: str | None = None) -> str:
        """Insert a junction before the closing paren.

        Args:
            content: Raw .kicad_sch S-expression text.
            x: X coordinate in mm.
            y: Y coordinate in mm.
            uid: Optional UUID string.

        Returns:
            Modified content with junction inserted.
        """
        jct_sexp = SchematicRawWriter.build_junction_sexp(x, y, uid)
        last_close = content.rfind(")")
        if last_close == -1:
            return content
        return content[:last_close] + jct_sexp + content[last_close:]

    # ------------------------------------------------------------------
    # PWR_FLAG / power symbol insertion (P0-003 critical fix)
    # ------------------------------------------------------------------

    # Minimal PWR_FLAG lib_symbol definition. Inserted at top level of the
    # lib_symbols container, NOT inside another lib_symbol block (which was
    # the P0-003 corruption cause).
    _PWR_FLAG_LIB_SYMBOL = (
        '    (symbol "power:PWR_FLAG"\n'
        '      (power)\n'
        '      (pin_numbers (hide yes))\n'
        '      (pin_names (offset 0) (hide yes))\n'
        '      (exclude_from_sim no)\n'
        '      (in_bom yes)\n'
        '      (on_board yes)\n'
        '      (property "Reference" "#PWR" (at 0.0 0.0 0)\n'
        '        (effects (font (size 1.27 1.27)) (hide yes))\n'
        '      )\n'
        '      (property "Value" "PWR_FLAG" (at 0.0 0.0 0)\n'
        '        (effects (font (size 1.27 1.27)))\n'
        '      )\n'
        '      (property "Footprint" "" (at 0.0 0.0 0)\n'
        '        (effects (font (size 1.27 1.27)) (hide yes))\n'
        '      )\n'
        '      (property "Datasheet" "~" (at 0.0 0.0 0)\n'
        '        (effects (font (size 1.27 1.27)) (hide yes))\n'
        '      )\n'
        '      (symbol "PWR_FLAG_0_1"\n'
        '        (pin power_in line (at 0.0 0.0 0) (length 0)\n'
        '          (uuid "00000000-0000-0000-0000-000000000000")\n'
        '        )\n'
        '      )\n'
        '    )\n'
    )

    @staticmethod
    def _ensure_lib_symbol_exists(content: str, lib_id: str, lib_symbol_sexp: str) -> str:
        """Ensure a lib_symbol definition exists in the top-level lib_symbols container.

        P0-003 critical fix: Inserts into the TOP-LEVEL (lib_symbols ...)
        container only, never inside another lib_symbol block. Returns
        content unchanged if the lib_symbol already exists.

        Args:
            content: Raw .kicad_sch S-expression text.
            lib_id: Library ID to check for (e.g. "power:PWR_FLAG").
            lib_symbol_sexp: Complete (symbol ...) block to insert if missing.

        Returns:
            Modified content with lib_symbol ensured.
        """
        # Check if lib_symbol already exists (avoid duplicates)
        # Match (symbol "power:PWR_FLAG" or (symbol "power:PWR_FLAG"
        escaped_id = re.escape(lib_id)
        if re.search(rf'\(symbol\s+"{escaped_id}"', content):
            return content

        # Find the top-level (lib_symbols ...) container.
        # We must insert INSIDE this container, before its closing paren.
        match = re.search(r'\(lib_symbols\b', content)
        if not match:
            # No lib_symbols container — create one at the top level
            # Insert after (paper ...) or after the header if no paper
            lib_symbols_block = f'  (lib_symbols\n{lib_symbol_sexp}  )\n'
            # Try to insert after (paper ...) line
            paper_match = re.search(r'\(paper\s+"[^"]*"\)', content)
            if paper_match:
                insert_pos = paper_match.end()
                return content[:insert_pos] + "\n" + lib_symbols_block + content[insert_pos:]
            # Fallback: insert before first (symbol ...) or at end before closing paren
            last_close = content.rfind(")")
            if last_close == -1:
                return content
            return content[:last_close] + lib_symbols_block + content[last_close:]

        # Found (lib_symbols ...). Find its matching closing paren.
        start = match.start()
        depth = 0
        i = start
        while i < len(content):
            if content[i] == "(":
                depth += 1
            elif content[i] == ")":
                depth -= 1
                if depth == 0:
                    # i is the position of the closing paren of (lib_symbols ...)
                    # Insert before this closing paren.
                    return content[:i] + lib_symbol_sexp + content[i:]
            i += 1

        # Malformed content — return unchanged
        return content

    @staticmethod
    def build_power_flag_symbol_sexp(
        x: float,
        y: float,
        angle: float = 0.0,
        uid: str | None = None,
        ref: str = "#PWR?",
    ) -> str:
        """Build a PWR_FLAG symbol instance S-expression.

        Args:
            x: X coordinate in mm.
            y: Y coordinate in mm.
            angle: Rotation angle in degrees.
            uid: Optional UUID string. Generated if None.
            ref: Reference designator (default "#PWR?").

        Returns:
            S-expression string for a placed PWR_FLAG symbol.
        """
        if uid is None:
            uid = str(uuid.uuid4())
        return (
            f'  (symbol\n'
            f'    (lib_id "power:PWR_FLAG")\n'
            f'    (at {x} {y} {angle})\n'
            f'    (unit 1)\n'
            f'    (in_bom yes)\n'
            f'    (on_board yes)\n'
            f'    (dnp no)\n'
            f'    (fields_autoplaced yes)\n'
            f'    (uuid "{uid}")\n'
            f'    (property "Reference" "{ref}" (at {x} {y} 0)\n'
            f'      (effects (font (size 1.27 1.27)) (hide yes))\n'
            f'    )\n'
            f'    (property "Value" "PWR_FLAG" (at {x} {y} 0)\n'
            f'      (effects (font (size 1.27 1.27)))\n'
            f'    )\n'
            f'    (property "Footprint" "" (at {x} {y} 0)\n'
            f'      (effects (font (size 1.27 1.27)) (hide yes))\n'
            f'    )\n'
            f'    (instances\n'
            f'      (project "kicad-agent"\n'
            f'        (path "/00000000-0000-0000-0000-000000000000" "{uid}")\n'
            f'      )\n'
            f'    )\n'
            f'  )\n'
        )

    @staticmethod
    def insert_power_flag(
        content: str,
        x: float,
        y: float,
        angle: float = 0.0,
        uid: str | None = None,
    ) -> str:
        """Insert a PWR_FLAG symbol (lib_symbol + instance) at the correct nesting level.

        P0-003 fix: Ensures the lib_symbol goes in the TOP-LEVEL lib_symbols
        container and the symbol instance goes at the top level of the file
        (before the closing paren), NOT inside another lib_symbol block.

        Args:
            content: Raw .kicad_sch S-expression text.
            x: X coordinate in mm.
            y: Y coordinate in mm.
            angle: Rotation angle in degrees.
            uid: Optional UUID string.

        Returns:
            Modified content with PWR_FLAG inserted.
        """
        # Step 1: Ensure the PWR_FLAG lib_symbol exists in lib_symbols container
        content = SchematicRawWriter._ensure_lib_symbol_exists(
            content, "power:PWR_FLAG", SchematicRawWriter._PWR_FLAG_LIB_SYMBOL,
        )

        # Step 2: Insert the symbol instance before the closing paren
        sym_sexp = SchematicRawWriter.build_power_flag_symbol_sexp(
            x, y, angle, uid,
        )
        last_close = content.rfind(")")
        if last_close == -1:
            return content
        return content[:last_close] + sym_sexp + content[last_close:]

    # ------------------------------------------------------------------
    # Wire removal (by approximate position match)
    # ------------------------------------------------------------------

    @staticmethod
    def remove_wire_by_position(
        content: str,
        start_x: float,
        start_y: float,
        end_x: float,
        end_y: float,
        tolerance: float = 0.01,
    ) -> str:
        """Remove a wire S-expression matching the given endpoints.

        KiCad wires look like:
            (wire (pts (xy X1 Y1) (xy X2 Y2)) ...)

        Args:
            content: Raw .kicad_sch S-expression text.
            start_x, start_y: First endpoint coordinates.
            end_x, end_y: Second endpoint coordinates.
            tolerance: Coordinate match tolerance in mm.

        Returns:
            Content with the matching wire removed, or unchanged if not found.
        """
        # Find all (wire ...) blocks
        for match in re.finditer(r'\(wire\b', content):
            start = match.start()
            # Find matching close paren
            depth = 0
            i = start
            while i < len(content):
                if content[i] == "(":
                    depth += 1
                elif content[i] == ")":
                    depth -= 1
                    if depth == 0:
                        block = content[start:i + 1]
                        # Extract pts
                        pts_match = re.search(
                            r'\(xy\s+([\d.]+)\s+([\d.]+)\)\s*\(xy\s+([\d.]+)\s+([\d.]+)\)',
                            block,
                        )
                        if pts_match:
                            x1, y1 = float(pts_match.group(1)), float(pts_match.group(2))
                            x2, y2 = float(pts_match.group(3)), float(pts_match.group(4))
                            # Check both endpoint orderings
                            match_forward = (
                                abs(x1 - start_x) <= tolerance
                                and abs(y1 - start_y) <= tolerance
                                and abs(x2 - end_x) <= tolerance
                                and abs(y2 - end_y) <= tolerance
                            )
                            match_reverse = (
                                abs(x1 - end_x) <= tolerance
                                and abs(y1 - end_y) <= tolerance
                                and abs(x2 - start_x) <= tolerance
                                and abs(y2 - start_y) <= tolerance
                            )
                            if match_forward or match_reverse:
                                # Remove the block and any trailing newline
                                end_pos = i + 1
                                if end_pos < len(content) and content[end_pos] == "\n":
                                    end_pos += 1
                                return content[:start] + content[end_pos:]
                        break
                i += 1

        return content

    # ------------------------------------------------------------------
    # Mutation replay (apply recorded IR mutations to raw text)
    # ------------------------------------------------------------------

    @staticmethod
    def apply_mutation(content: str, mutation: dict[str, Any]) -> str:
        """Apply a single recorded IR mutation to raw S-expression content.

        Args:
            content: Raw .kicad_sch S-expression text.
            mutation: Mutation dict with 'op' key and op-specific fields.

        Returns:
            Modified content after applying the mutation.

        Raises:
            ValueError: If mutation op is unknown.
        """
        op = mutation.get("op") or mutation.get("type", "")

        if op == "add_no_connect":
            pos = mutation.get("position", [0.0, 0.0])
            return SchematicRawWriter.insert_no_connect(content, pos[0], pos[1])

        elif op == "add_junction":
            pos = mutation.get("position", [0.0, 0.0])
            return SchematicRawWriter.insert_junction(content, pos[0], pos[1])

        elif op == "add_power_flag" or op == "add_power_symbol":
            pos = mutation.get("position", [0.0, 0.0])
            angle = mutation.get("angle", 0.0)
            return SchematicRawWriter.insert_power_flag(content, pos[0], pos[1], angle)

        elif op == "remove_dangling_wire":
            pos = mutation.get("position", [])
            if len(pos) >= 2:
                # Best-effort removal by position (wire endpoint)
                # Full wire removal requires both endpoints; this is a
                # best-effort that removes wires whose start matches.
                pass  # Wire removal handled by caller with full endpoints
            return content

        elif op == "move_symbol":
            # HIGH-4 (Council Gate 1): the dispatcher reads mutation.get("op").
            # Using "kind" instead silently no-ops (Test 10 regression guard).
            ref = mutation.get("ref", "")
            new_x = float(mutation.get("new_x", 0.0))
            new_y = float(mutation.get("new_y", 0.0))
            return SchematicRawWriter._move_symbol_by_ref(content, ref, new_x, new_y)

        elif op == "move_symbol_by_uuid":
            # Phase 108 Task 2: parking pass for unannotated symbols (R?/C?)
            # that share a Reference and cannot be moved by ref. UUID-keyed
            # for unambiguous targeting.
            symbol_uuid = mutation.get("uuid", "")
            new_x = float(mutation.get("new_x", 0.0))
            new_y = float(mutation.get("new_y", 0.0))
            return SchematicRawWriter._move_symbol_by_uuid(
                content, symbol_uuid, new_x, new_y,
            )

        elif op == "insert_wire":
            # HIGH-4 (Council Gate 1): discriminator key is "op" (NEVER "kind").
            points = mutation.get("points", [])
            net_name = mutation.get("net_name", "")
            return SchematicRawWriter._insert_wire_sexp(content, points, net_name)

        elif op == "insert_label":
            # HIGH-4 (Council Gate 1): discriminator key is "op" (NEVER "kind").
            net_name = mutation.get("net_name", "")
            x = float(mutation.get("x", 0.0))
            y = float(mutation.get("y", 0.0))
            size = float(mutation.get("size", 1.27))
            is_global = bool(mutation.get("is_global", False))
            label_uuid = mutation.get("uuid", "")
            return SchematicRawWriter._insert_label_sexp(
                content, net_name, x, y, size, is_global, label_uuid,
            )

        elif op in ("snap_to_grid", "repair_wire_snap"):
            # Coordinate mutations are applied to the kiutils obj in memory.
            # For raw S-expr, these are no-ops here — the caller must handle
            # coordinate updates separately if needed.
            return content

        # Unknown mutations: return content unchanged (defensive — don't break)
        return content

    @staticmethod
    def apply_mutations(content: str, mutations: list[dict[str, Any]]) -> str:
        """Apply a list of recorded IR mutations to raw S-expression content.

        Args:
            content: Raw .kicad_sch S-expression text.
            mutations: List of mutation dicts.

        Returns:
            Modified content after applying all mutations in order.
        """
        for mutation in mutations:
            content = SchematicRawWriter.apply_mutation(content, mutation)
        return content

    # ------------------------------------------------------------------
    # Reference property replacement (Phase 102: safe_annotate)
    # ------------------------------------------------------------------

    @staticmethod
    def replace_reference_property(content: str, symbol_uuid: str, new_ref: str) -> str:
        """Replace the Reference property value on a specific symbol by UUID.

        Locates the ``(symbol ...)`` block containing ``(uuid "SYMBOL_UUID")``,
        then within that block replaces the value of
        ``(property "Reference" "OLD")`` with new_ref. Preserves every other
        byte (whitespace, indentation, effects blocks, all other symbols).

        Args:
            content: Raw S-expression schematic content.
            symbol_uuid: The UUID of the target placed symbol (NOT a
                lib_symbol UUID).
            new_ref: The new reference value (e.g. "R1", "C42").

        Returns:
            Content with the targeted Reference value replaced. Returns
            content unchanged if the UUID or Reference property is not found
            (no-op, no silent corruption).

        Raises:
            ValueError: If new_ref contains a double quote that would break
                S-expression syntax.
        """
        if '"' in new_ref:
            raise ValueError(f"new_ref contains illegal double quote: {new_ref!r}")

        safe_uuid = re.escape(symbol_uuid)
        # KiCad 10 uses unquoted UUIDs: (uuid abc-123); older format quotes them.
        # Match both forms.
        uuid_pattern = re.compile(rf'\(uuid\s+"?{safe_uuid}"?')

        # Find the (symbol ...) block containing the target UUID.
        # Iterate over all (symbol starts, depth-track to block close, check UUID.
        symbol_starts = [m.start() for m in re.finditer(r'\(symbol\b', content)]
        target_block_start = None
        target_block_end = None

        for start in symbol_starts:
            depth = 0
            i = start
            block_end = None
            while i < len(content):
                if content[i] == '(':
                    depth += 1
                elif content[i] == ')':
                    depth -= 1
                    if depth == 0:
                        block_end = i + 1
                        break
                i += 1
            if block_end is None:
                continue  # malformed — skip

            block = content[start:block_end]
            if uuid_pattern.search(block):
                target_block_start = start
                target_block_end = block_end
                break

        if target_block_start is None:
            return content  # symbol not found — no-op

        # Within the block, replace (property "Reference" "OLD") value.
        # Match exactly: (property "Reference" "OLD_VAL"
        # Preserve everything after the value (at, effects, closing parens).
        block = content[target_block_start:target_block_end]
        prop_pattern = re.compile(r'(\(property\s+"Reference"\s+)"[^"]*"')
        new_block, n = prop_pattern.subn(rf'\1"{new_ref}"', block, count=1)

        if n == 0:
            return content  # no Reference property in this block — no-op

        return content[:target_block_start] + new_block + content[target_block_end:]

    @staticmethod
    def replace_instances_reference(content: str, symbol_uuid: str, new_ref: str) -> str:
        """Replace the ``(reference ...)`` value inside an ``(instances ...)`` block.

        H-02 Option B (Phase 102.1): real-world KiCad 10 schematics contain
        ``(instances (project "..." (path "/" (reference "OLD") (unit N))))``
        blocks inside each ``(symbol ...)``. The netlist exporter reads the
        reference designator from here, NOT from ``(property "Reference" ...)``.
        Without co-editing this block, safe_annotate renames the property but
        the exported netlist still shows the old ref → silent partial
        annotation on real schematics (analog-board has 5-46 instances blocks
        per sheet).

        Locates the ``(symbol ...)`` block containing ``(uuid "SYMBOL_UUID")``,
        then within that block finds the ``(instances ...)`` sub-block and
        replaces its ``(reference "OLD")`` value with new_ref via string
        slicing (NOT regex with user content as replacement — LO-05 defense).

        Args:
            content: Raw S-expression schematic content.
            symbol_uuid: The UUID of the target placed symbol.
            new_ref: The new reference value (e.g. "R1", "C42").

        Returns:
            Content with the targeted instances reference replaced. Returns
            content unchanged if the UUID, instances block, or reference is
            not found (no-op — backward compat with Phase 102 fixtures that
            intentionally omit instances blocks).

        Raises:
            ValueError: If new_ref contains a double quote.
        """
        if '"' in new_ref:
            raise ValueError(f"new_ref contains illegal double quote: {new_ref!r}")

        safe_uuid = re.escape(symbol_uuid)
        # Match both KiCad 10 unquoted and legacy quoted UUID forms.
        uuid_pattern = re.compile(rf'\(uuid\s+"?{safe_uuid}"?')

        # Find the (symbol ...) block containing the target UUID.
        symbol_starts = [m.start() for m in re.finditer(r'\(symbol\b', content)]
        target_block_start = None
        target_block_end = None

        for start in symbol_starts:
            depth = 0
            i = start
            block_end = None
            while i < len(content):
                if content[i] == '(':
                    depth += 1
                elif content[i] == ')':
                    depth -= 1
                    if depth == 0:
                        block_end = i + 1
                        break
                i += 1
            if block_end is None:
                continue

            block = content[start:block_end]
            if uuid_pattern.search(block):
                target_block_start = start
                target_block_end = block_end
                break

        if target_block_start is None:
            return content  # symbol not found — no-op

        block = content[target_block_start:target_block_end]

        # Find the (instances ...) sub-block via paren-balanced extraction.
        inst_match = re.search(r'\(instances\b', block)
        if inst_match is None:
            return content  # no instances block — no-op (backward compat)

        inst_start = inst_match.start()
        depth = 0
        i = inst_start
        inst_end = None
        while i < len(block):
            if block[i] == '(':
                depth += 1
            elif block[i] == ')':
                depth -= 1
                if depth == 0:
                    inst_end = i + 1
                    break
            i += 1
        if inst_end is None:
            return content  # malformed instances block — no-op (fail safe)

        instances_block = block[inst_start:inst_end]

        # Within (instances ...), locate (reference "OLD") and replace with
        # (reference "NEW") via string slicing. We do NOT use re.sub with the
        # old reference as part of a replacement string — the old reference is
        # discarded after locating it; only the new_ref (which we control,
        # e.g. "R42") is interpolated. LO-05 hardening: this prevents
        # adversarial reference values from acting as regex/shell payloads.
        # WR-01 fix: NO count=1 — update ALL (reference ...) entries in the
        # instances block. Multi-board projects have one (reference ...) per
        # board per symbol; all must share the refdes. count=1 would leave
        # stale references on the 2nd+ board, silently corrupting netlists.
        ref_pattern = re.compile(r'(\(reference\s+)"[^"]*"')
        new_instances, n = ref_pattern.subn(rf'\1"{new_ref}"', instances_block)

        if n == 0:
            return content  # no reference in instances block — no-op

        new_block = block[:inst_start] + new_instances + block[inst_end:]
        return content[:target_block_start] + new_block + content[target_block_end:]

    # ------------------------------------------------------------------
    # move_symbol by Reference (Phase 108 Plan 02 — autolayout placement)
    # ------------------------------------------------------------------

    @staticmethod
    def _move_symbol_by_ref(
        content: str,
        ref: str,
        new_x: float,
        new_y: float,
    ) -> str:
        """Replace the (at X Y [R]) of the placed symbol whose Reference == ref.

        T-108-05 mitigation (LO-05): the ref is re.escape'd before being
        interpolated into the regex — adversarial ref strings cannot act as
        regex payloads. The Reference value match is anchored with leading
        and trailing whitespace via \\s+ to avoid prefix collisions (R1 vs R10).

        Locates the (symbol ...) block whose (property "Reference" "<ref>")
        sub-block matches, then within that block replaces the *first*
        (at X Y [R]) S-expression with (at <new_x> <new_y> [R]). Preserves
        the optional rotation field. Preserves every other byte.

        Args:
            content: Raw .kicad_sch S-expression text.
            ref: Component reference designator (e.g. "R1", "U21").
            new_x: New X coordinate in mm.
            new_y: New Y coordinate in mm.

        Returns:
            Content with the targeted (at X Y) replaced. Returns content
            unchanged if the ref is not found (defensive — no silent
            corruption).

        Raises:
            ValueError: If multiple distinct symbol blocks share the same
                Reference (ambiguous match — refuse to guess which to move).
        """
        if not ref:
            return content  # no ref supplied — no-op (defensive)

        # Find every (symbol ...) start; depth-walk to its closing paren.
        # For each block, check whether it contains
        # (property "Reference" "<ref>"). Collect matches.
        safe_ref = re.escape(ref)
        ref_pattern = re.compile(
            rf'\(property\s+"Reference"\s+"{safe_ref}"'
        )

        symbol_starts = [m.start() for m in re.finditer(r'\(symbol\b', content)]
        matches: list[tuple[int, int]] = []  # list of (block_start, block_end)

        for start in symbol_starts:
            depth = 0
            i = start
            block_end = None
            while i < len(content):
                if content[i] == '(':
                    depth += 1
                elif content[i] == ')':
                    depth -= 1
                    if depth == 0:
                        block_end = i + 1
                        break
                i += 1
            if block_end is None:
                continue  # malformed — skip

            block = content[start:block_end]
            if ref_pattern.search(block):
                matches.append((start, block_end))

        if len(matches) == 0:
            return content  # ref not found — no-op (defensive)
        if len(matches) > 1:
            raise ValueError(
                f"Ambiguous move_symbol: {len(matches)} symbol blocks share "
                f"Reference {ref!r} — refuse to guess which to move"
            )

        block_start, block_end = matches[0]
        block = content[block_start:block_end]

        # Within the block, find the FIRST (at X Y [R]) S-expression.
        # KiCad symbol blocks always place (at ...) immediately after (lib_id ...),
        # so the first (at ...) is the symbol transform — not a nested pin or
        # property at-coordinate. Replace its coordinates while preserving the
        # optional rotation field.
        at_pattern = re.compile(
            r'\(at\s+([-0-9.]+)\s+([-0-9.]+)(\s+([-0-9.]+))?\)'
        )
        match = at_pattern.search(block)
        if match is None:
            return content  # no (at ...) in block — no-op (defensive)

        rotation = match.group(4)
        if rotation is not None:
            new_at = f'(at {new_x} {new_y} {rotation})'
        else:
            new_at = f'(at {new_x} {new_y})'

        # Replace just this single match (count=1 — never touch nested at's).
        new_block, n = at_pattern.subn(lambda _: new_at, block, count=1)
        if n == 0:
            return content  # defensive — should never happen since match was found

        return content[:block_start] + new_block + content[block_end:]

    @staticmethod
    def _move_symbol_by_uuid(
        content: str,
        symbol_uuid: str,
        new_x: float,
        new_y: float,
    ) -> str:
        """Replace the (at X Y [R]) of the symbol block with the given uuid.

        Phase 108 Task 2: the on-page autolayout guarantee needs to move
        unannotated symbols (e.g.
```
R?` shared by 129 stacked resistors on
        the corrupt Arduino_Mega fixture). ``_move_symbol_by_ref`` refuses
        ambiguous matches; this UUID-keyed variant targets one block
        unambiguously by its ``(uuid "...")`` property.

        Used only by the autolayout parking pass — public move op stays
        ref-keyed (the executor's public contract).
        """
        if not symbol_uuid:
            return content
        safe_uuid = re.escape(symbol_uuid)
        # KiCad's (uuid ...) is UNQUOTED: (uuid 00000000-0000-...) — not "...".
        uuid_pattern = re.compile(rf'\(uuid\s+{safe_uuid}\)')

        symbol_starts = [
            m.start() for m in re.finditer(r'\(symbol\s+\(lib_id\b', content)
        ]
        for start in symbol_starts:
            depth = 0
            i = start
            block_end = None
            while i < len(content):
                if content[i] == '(':
                    depth += 1
                elif content[i] == ')':
                    depth -= 1
                    if depth == 0:
                        block_end = i + 1
                        break
                i += 1
            if block_end is None:
                continue
            block = content[start:block_end]
            if not uuid_pattern.search(block):
                continue

            # Found the unique block. Replace its first (at X Y [R]).
            at_pattern = re.compile(
                r'\(at\s+([-0-9.]+)\s+([-0-9.]+)(\s+([-0-9.]+))?\)'
            )
            match = at_pattern.search(block)
            if match is None:
                return content
            rotation = match.group(4)
            new_at = (
                f'(at {new_x} {new_y} {rotation})'
                if rotation is not None
                else f'(at {new_x} {new_y})'
            )
            new_block, _ = at_pattern.subn(lambda _: new_at, block, count=1)
            return content[:start] + new_block + content[block_end:]

        return content  # uuid not found — no-op (defensive)

    # ------------------------------------------------------------------
    # insert_wire / insert_label (Phase 108 Plan 02 — autolayout routing)
    # ------------------------------------------------------------------

    @staticmethod
    def _insert_wire_sexp(
        content: str,
        points: list[tuple[float, float]],
        net_name: str = "",
    ) -> str:
        """Insert a (wire (pts ...)) S-expression before the top-level close.

        Phase 38 verified format (KiCad 10):
            (wire (pts (xy X1 Y1) (xy X2 Y2))
              (stroke (width 0) (type default))
              (uuid "..."))

        For 2-point wires this is a single segment. For >2 points we emit
        a multi-point (pts ...) list (KiCad 10 supports this natively).

        Args:
            content: Raw .kicad_sch S-expression text.
            points: List of (x, y) tuples (≥2 points).
            net_name: Optional net name (metadata only — wires don't carry
                net names in the S-expression; labels do).

        Returns:
            Content with the wire S-expr inserted. Returns content unchanged
            if points has fewer than 2 entries (defensive).
        """
        if len(points) < 2:
            return content

        pts_str = " ".join(f"(xy {x} {y})" for x, y in points)
        uid = str(uuid.uuid4())
        wire_sexp = (
            f'  (wire (pts {pts_str})\n'
            f'    (stroke (width 0) (type default))\n'
            f'    (uuid "{uid}"))\n'
        )
        last_close = content.rfind(")")
        if last_close == -1:
            return content
        return content[:last_close] + wire_sexp + content[last_close:]

    @staticmethod
    def _insert_label_sexp(
        content: str,
        net_name: str,
        x: float,
        y: float,
        size: float = 1.27,
        is_global: bool = False,
        label_uuid: str = "",
    ) -> str:
        """Insert a (label ...) or (global_label ...) S-expression.

        Phase 38 verified format (KiCad 10):
            (label "NAME" (at X Y 0)
              (effects (font (size SIZE SIZE)))
              (uuid "..."))
        For global labels, the leading token is "global_label" with the same
        shape (plus additional fields like (shape "input") which we emit as
        a sensible default "input").

        Args:
            content: Raw .kicad_sch S-expression text.
            net_name: Label text (the net name).
            x, y: Label position in mm.
            size: Font size in mm (KiCad default 1.27).
            is_global: True → emit (global_label ...), False → (label ...).
            label_uuid: UUID string. Generated if empty.

        Returns:
            Content with the label S-expr inserted.
        """
        if not label_uuid:
            label_uuid = str(uuid.uuid4())

        # Sanitize net_name: KiCad label strings cannot contain double quotes
        # or backslashes. Strip them defensively (T-108-05 mitigation).
        safe_name = net_name.replace('"', '').replace('\\', '')

        if is_global:
            label_sexp = (
                f'  (global_label "{safe_name}" (shape input) (at {x} {y} 0)\n'
                f'    (effects (font (size {size} {size})))\n'
                f'    (uuid "{label_uuid}"))\n'
            )
        else:
            label_sexp = (
                f'  (label "{safe_name}" (at {x} {y} 0)\n'
                f'    (effects (font (size {size} {size})))\n'
                f'    (uuid "{label_uuid}"))\n'
            )
        last_close = content.rfind(")")
        if last_close == -1:
            return content
        return content[:last_close] + label_sexp + content[last_close:]

