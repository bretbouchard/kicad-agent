#!/usr/bin/env python3
"""Validate operation count consistency across all documentation sources.

Checks that the operation count in the Pydantic schema, the operation registry,
CLAUDE.md, and skills/prompt.md Quick Reference all agree. Exits with code 0
on success, 1 on mismatch, 2 on parse/import errors.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLAUDE_MD = ROOT / ".claude" / "CLAUDE.md"
PROMPT_MD = ROOT / "skills" / "prompt.md"


def count_registry_ops() -> int:
    """Count ops in OPERATION_REGISTRY (authoritative source)."""
    from volta.ops.registry import OPERATION_REGISTRY

    return len(OPERATION_REGISTRY)


def count_schema_ops() -> int:
    """Count ops in the Operation discriminated union in schema.py."""
    import volta.ops.schema as schema_module

    schema_types: set[str] = set()
    for name in dir(schema_module):
        obj = getattr(schema_module, name)
        if hasattr(obj, "model_fields") and "op_type" in obj.model_fields:
            field = obj.model_fields["op_type"]
            if field.default is not None:
                schema_types.add(field.default)
    return len(schema_types)


def count_claude_md_ops() -> int | None:
    """Parse CLAUDE.md for the operation count number.

    Looks for the pattern 'N operation types' in the kicad-agent operations
    description line.
    """
    text = CLAUDE_MD.read_text()
    match = re.search(r"(\d+)\s+operation types", text)
    if match:
        return int(match.group(1))
    return None


def count_prompt_md_ops() -> int | None:
    """Count documented ops in skills/prompt.md Quick Reference table.

    Counts table rows where the first column looks like an op_type
    (backtick-wrapped snake_case identifier).
    """
    text = PROMPT_MD.read_text()

    # Find the Quick Reference section
    quick_ref_match = re.search(
        r"## Operation Quick Reference\s*\n(.+?)(?=\n---|\n## |\Z)",
        text,
        re.DOTALL,
    )
    if not quick_ref_match:
        return None

    section = quick_ref_match.group(1)

    # Count table rows with backtick-wrapped op names (pipe-separated lines)
    # Pattern: | `op_name` | ... |
    op_rows = re.findall(r"^\|\s*`(\w+)`\s*\|", section, re.MULTILINE)
    return len(op_rows)


def main() -> int:
    errors: list[str] = []

    # Registry is the authoritative count
    try:
        registry_count = count_registry_ops()
    except Exception as exc:
        print(f"ERROR: Failed to import registry: {exc}", file=sys.stderr)
        return 2

    # Schema count
    try:
        schema_count = count_schema_ops()
    except Exception as exc:
        print(f"WARN: Could not count schema ops: {exc}", file=sys.stderr)
        schema_count = None

    # CLAUDE.md count
    claude_count = count_claude_md_ops()
    if claude_count is None:
        errors.append("CLAUDE.md: could not find 'N operation types' pattern")

    # prompt.md count
    prompt_count = count_prompt_md_ops()
    if prompt_count is None:
        errors.append("skills/prompt.md: could not find Quick Reference table")

    # Build results
    sources: dict[str, int | None] = {
        "Operation registry": registry_count,
        "Pydantic schema": schema_count,
        "CLAUDE.md": claude_count,
        "prompt.md Quick Ref": prompt_count,
    }

    print("Operation count by source:")
    for name, count in sources.items():
        status = str(count) if count is not None else "PARSE_ERROR"
        print(f"  {name}: {status}")

    # Check all non-None counts agree
    non_none_counts = {k: v for k, v in sources.items() if v is not None}
    unique_counts = set(non_none_counts.values())

    if errors:
        print("\nParse errors:")
        for err in errors:
            print(f"  - {err}")

    if len(unique_counts) == 1:
        count = unique_counts.pop()
        print(f"\nPASS: All sources agree on {count} operations.")
        return 0
    else:
        print(f"\nMISMATCH: Sources disagree: {non_none_counts}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
