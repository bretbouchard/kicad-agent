"""Phase 102 — SchematicRawWriter.replace_reference_property unit tests.

Validates the raw S-expression Reference property replacement method used by
the safe_annotate op (Phase 102). The method surgically replaces the value of
(property "Reference" "OLD") inside the (symbol ...) block identified by UUID.
"""
import difflib

import pytest

from kicad_agent.ops.schematic_raw_writer import SchematicRawWriter

SYMBOL_TEMPLATE = '''
  (symbol (lib_id "Device:R") (at {x} {y} 0) (unit 1)
    (in_bom yes) (on_board yes) (dnp no)
    (uuid "{uuid}")
    (property "Reference" "{ref}" (at 52.032 50 0)
      (effects (font (size 1.27 1.27)))
    )
    (property "Value" "330R" (at 50 50 0)
      (effects (font (size 1.27 1.27)))
    )
  )
'''


def test_replace_reference_property_basic():
    """Simple R? -> R1 replacement: only the value string changes."""
    content = SYMBOL_TEMPLATE.format(x=50, y=50, uuid="abc-123", ref="R?")
    result = SchematicRawWriter.replace_reference_property(content, "abc-123", "R1")
    assert '(property "Reference" "R1"' in result
    assert '(property "Reference" "R?"' not in result
    # Everything else preserved
    assert '(uuid "abc-123")' in result
    assert '(property "Value" "330R"' in result


def test_replace_reference_property_uuid_targeting():
    """Two symbols with same Reference; only the UUID-targeted one changes.

    Pitfall 2 mitigation: duplicates must not cause ambiguous replacement.
    """
    sym1 = SYMBOL_TEMPLATE.format(x=50, y=50, uuid="uuid-001", ref="R1")
    sym2 = SYMBOL_TEMPLATE.format(x=100, y=50, uuid="uuid-002", ref="R1")
    content = sym1 + sym2
    result = SchematicRawWriter.replace_reference_property(content, "uuid-002", "R42")
    assert result.count('(property "Reference" "R1"') == 1
    assert result.count('(property "Reference" "R42"') == 1
    # The uuid-002 block has R42, uuid-001 block still has R1
    assert '(uuid "uuid-002")' in result
    idx_r42 = result.find("R42")
    idx_uuid002 = result.find("uuid-002")
    # R42 should be after uuid-002 in document order (same block)
    assert idx_r42 > idx_uuid002


def test_replace_reference_property_not_found():
    """UUID not present -> content returned unchanged (no silent corruption)."""
    content = SYMBOL_TEMPLATE.format(x=50, y=50, uuid="abc-123", ref="R?")
    result = SchematicRawWriter.replace_reference_property(content, "nonexistent", "R1")
    assert result == content


def test_replace_reference_property_preserves_other_bytes():
    """Full content except the value string is byte-identical (exactly 1 line changed)."""
    content = SYMBOL_TEMPLATE.format(x=50, y=50, uuid="abc-123", ref="R?")
    result = SchematicRawWriter.replace_reference_property(content, "abc-123", "R1")
    diff = list(difflib.unified_diff(content.splitlines(), result.splitlines(), n=0))
    # Expect exactly 1 line changed (the Reference property line): 1 deletion + 1 addition
    changed_lines = [
        line for line in diff
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    ]
    assert len(changed_lines) == 2


def test_replace_reference_property_rejects_quote_in_new_ref():
    """new_ref containing a double quote is rejected (T-102-02-01 mitigation)."""
    content = SYMBOL_TEMPLATE.format(x=50, y=50, uuid="abc-123", ref="R?")
    with pytest.raises(ValueError):
        SchematicRawWriter.replace_reference_property(content, "abc-123", 'R1"evil')
