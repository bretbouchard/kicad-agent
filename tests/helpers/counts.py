"""Dynamic count helpers -- never stale, always correct.

Provides functions that compute operation, schema, and tool counts dynamically
from the actual source code. Tests should use these instead of hardcoded integers
so that adding a new operation/schema/tool never breaks the test suite.

Council audit references: T-1 through T-5.
"""

from __future__ import annotations

from pathlib import Path

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "src" / "volta" / "ops"


def count_op_classes() -> int:
    """Count all Op subclasses in schema.py and its _schema_*.py sub-modules."""
    import re

    schema_path = SCHEMA_DIR / "schema.py"
    names: list[str] = []

    content = schema_path.read_text(encoding="utf-8")
    names.extend(re.findall(r"^class (\w+Op)\(BaseModel\)", content, re.MULTILINE))

    for submod in sorted(SCHEMA_DIR.glob("_schema_*.py")):
        sub_content = submod.read_text(encoding="utf-8")
        names.extend(
            re.findall(r"^class (\w+Op)\(BaseModel\)", sub_content, re.MULTILINE)
        )

    return len(names)


def count_schema_files() -> int:
    """Count _schema_*.py files in ops/."""
    return len(sorted(SCHEMA_DIR.glob("_schema_*.py")))


def count_operation_tools() -> int:
    """Count tools generated from operation schemas in edit_server."""
    from volta.mcp.edit_server import _OPERATION_TOOLS  # noqa: WPS433

    return len(_OPERATION_TOOLS)
