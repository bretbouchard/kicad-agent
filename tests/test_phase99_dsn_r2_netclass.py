"""R-2: net class emission + H-2 self-contained per-class via padstacks."""
from __future__ import annotations

from pathlib import Path

import pytest

from volta.routing.dsn_generator import generate_dsn

_REPO_ROOT = Path(__file__).resolve().parents[1]

# Minimal PCB content with a named net_class "Power" (H-2 fixture).
_POWER_CLASS_PCB = """\
(kicad_pcb
  (net 0 "")
  (net 1 "VCC")
  (net_class "Power"
    (clearance 0.3)
    (trace_width 0.5)
    (via_diameter 0.8)
    (via_drill 0.4)
    (add_net "VCC")
  )
  (net_class "Default"
    (clearance 0.2)
    (trace_width 0.25)
  )
  (footprint "Test:R"
    (at 10 10 0)
    (layer "F.Cu")
    (property "Reference" "R1")
    (pad "1" smd rect (at -1 0) (size 1 1) (layers "F.Cu"))
    (pad "2" smd rect (at 1 0) (size 1 1) (layers "F.Cu"))
  )
)
"""


def test_r2_named_class_emitted_with_width_and_clearance() -> None:
    """A named net_class "Power" produces (class "Power" ... (width 500) (clearance 300))."""
    dsn = generate_dsn(_POWER_CLASS_PCB)
    assert '(class "Power"' in dsn, "Named class 'Power' not emitted"
    # 0.5mm * 1000 = 500um; 0.3mm * 1000 = 300um
    assert "(width 500)" in dsn, "track_width 0.5mm did not convert to 500um"
    assert "(clearance 300)" in dsn, "clearance 0.3mm did not convert to 300um"


def test_r2_add_net_members_appear_as_bare_tokens() -> None:
    """Each add_net member of a named class appears as a bare token in the class scope."""
    dsn = generate_dsn(_POWER_CLASS_PCB)
    # VCC is the add_net member of Power class.
    assert '(class "Power" VCC' in dsn, "add_net 'VCC' not emitted as bare token in class"


def test_r2_default_class_still_emitted() -> None:
    """Nets not in any named class still appear in a default class (backward compat)."""
    dsn = generate_dsn(_POWER_CLASS_PCB)
    assert "(class default" in dsn, "Default class not emitted"


def test_r2_h2_self_contained_per_class_padstack() -> None:
    """H-2 fix: named class with via_diameter emits BOTH (use_via "Via[Power]") AND
    (padstack "Via[Power]" ...) in the SAME plan (self-contained DSN validity)."""
    dsn = generate_dsn(_POWER_CLASS_PCB)
    assert '(use_via "Via[Power]")' in dsn, (
        "Per-class via reference (use_via \"Via[Power]\") missing — class cannot route"
    )
    assert '(padstack "Via[Power]"' in dsn, (
        "Per-class padstack definition missing — DSN not self-contained (H-2 bug)"
    )
