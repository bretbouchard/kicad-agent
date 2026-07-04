"""KiCad paper sizes + page-bounds helpers for the autolayout engine.

The deterministic autolayout engine (Phase 108) emits grid-snapped X/Y
coordinates for every component via SugiyamaLayout.assign_coordinates.
Stage 5 grows coordinates unbounded from origin — without page awareness
a multi-subcircuit board blows past A4 width (297mm) and components land
off the printable page. This module closes that gap.

ISO 216 (A-series) dimensions from the standard; ANSI Y14.1 (US sizes)
included for KiCad fixtures that declare them. Width/height are in
KiCad's *landscape* orientation (the eeschema default): width > height.

Single responsibility: paper lookup + raw-content paper extraction. The
fit-to-page math lives in SugiyamaLayout.fit_to_page (sugiyama.py).
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# KiCad default — every freshly-created schematic from kicad-cli / the GUI
# starts on A4 unless the user explicitly changes it.
KICAD_DEFAULT_PAPER: str = "A4"

# Reserved margin around the page edge. KiCad's title block lives in the
# bottom-right corner (~180x40mm on A4); a uniform 20mm margin keeps
# components clear of the title block AND the page border.
USABLE_PAGE_MARGIN_MM: float = 20.0

# ISO 216 + ANSI Y14.1 paper sizes (landscape orientation: width >= height).
# Values in millimeters. Source: ISO 216:2007 §2.2 + ANSI Y14.1-2012.
PAPER_SIZES_MM: dict[str, tuple[float, float]] = {
    # ISO A-series (width x height, landscape)
    "A0": (1189.0, 841.0),
    "A1": (841.0, 594.0),
    "A2": (594.0, 420.0),
    "A3": (420.0, 297.0),
    "A4": (297.0, 210.0),
    "A5": (210.0, 148.0),
    # ANSI Y14.1 (US customary)
    "A": (279.4, 215.9),   # US Letter
    "B": (431.8, 279.4),   # US Tabloid
    "C": (558.8, 431.8),
    "D": (863.6, 558.8),
    "E": (1117.6, 863.6),
    # Aliases (KiCad accepts these in some versions)
    "USLetter": (279.4, 215.9),
    "USLegal": (355.6, 215.9),
}

# Matches `(paper "A4")` in raw .kicad_sch S-expression text. KiCad 10's
# grammar requires the paper name as a quoted string; user-defined paper
# sizes use `(paper User W H)` but those are vanishingly rare in fixtures.
_PAPER_RE = re.compile(r'\(paper\s+"([^"]+)"\)')


def parse_paper_from_sch(raw_content: str) -> str:
    """Extract the paper size declared in a .kicad_sch S-expression.

    Returns the paper name (e.g. ``"A4"``) or ``KICAD_DEFAULT_PAPER`` if
    the file has no ``(paper ...)`` declaration (synthetic/minimal fixtures).
    """
    match = _PAPER_RE.search(raw_content)
    if match:
        return match.group(1)
    return KICAD_DEFAULT_PAPER


def paper_dims_mm(paper: str) -> tuple[float, float]:
    """Look up paper dimensions as ``(width_mm, height_mm)`` landscape.

    Falls back to A4 with a warning if the paper name is unrecognized —
    better to lay out on a slightly wrong page than crash the op.
    """
    dims = PAPER_SIZES_MM.get(paper)
    if dims is None:
        logger.warning(
            "Unknown paper size %r — falling back to A4 (%.1f x %.1f mm). "
            "Update PAPER_SIZES_MM if this paper should be supported.",
            paper, *PAPER_SIZES_MM["A4"],
        )
        return PAPER_SIZES_MM[KICAD_DEFAULT_PAPER]
    return dims


def usable_area_mm(
    paper: str,
    margin_mm: float = USABLE_PAGE_MARGIN_MM,
) -> tuple[float, float, float, float]:
    """Return the in-bounds rectangle ``(x_min, y_min, x_max, y_max)``.

    Components whose ``(at X Y)`` falls outside this rectangle are
    considered off-page by the verification gate.
    """
    width, height = paper_dims_mm(paper)
    return (margin_mm, margin_mm, width - margin_mm, height - margin_mm)
