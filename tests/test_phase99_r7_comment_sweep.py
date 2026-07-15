"""R-7: verify no '122B' references remain in src/."""
from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"


def test_no_phase_122b_references_in_src() -> None:
    """Pure-Python scan: zero files under src/ may contain '122B'."""
    failures: list[str] = []
    for p in _SRC.rglob("*.py"):
        if "122B" in p.read_text(encoding="utf-8", errors="replace"):
            failures.append(str(p.relative_to(_REPO_ROOT)))
    assert not failures, (
        "Phase 122B references remain in src/:\n" + "\n".join(failures)
    )


def test_phase_99_references_present() -> None:
    """Swept lines now reference 'Phase 99' (sanity check).

    Council IN-06: the phase-number coupling here is INTENTIONAL. This test
    is a regression guard for the Phase 122B -> Phase 99 comment sweep done
    in Plan 99-01 Task 1. If these assertions break because the phase is
    renumbered, the fix is to update both the source comments AND this test
    list together — the specificity is the point (it verifies the sweep
    touched exactly these files). Do not loosen to a generic "Phase N" check.
    """
    targets = [
        ("src/volta/handler.py", "Phase 99 Gap 4"),
        ("src/volta/routing/pathfinder.py", "Phase 99 Gap 2"),
        ("src/volta/routing/graph.py", "Phase 99 Gap 2"),
    ]
    for rel_path, expected in targets:
        text = (_REPO_ROOT / rel_path).read_text(encoding="utf-8")
        assert expected in text, f"{rel_path} missing '{expected}'"
