"""Layer classification utility for KiCad canonical layer names.

SI-03: Classifies KiCad layer names into functional categories using
regex patterns matching canonical layer naming conventions.
"""

from __future__ import annotations

import re
from typing import Final

# Pre-compiled regex patterns for canonical KiCad layer names
_COPPER_PATTERN: Final = re.compile(r"^(F|B|In\d+)\.Cu$")
_SILKSCREEN_PATTERN: Final = re.compile(r"^(F|B)\.SilkS$")
_MASK_PATTERN: Final = re.compile(r"^(F|B)\.Mask$")
_PASTE_PATTERN: Final = re.compile(r"^(F|B)\.Paste$")
_EDGE_CUTS_PATTERN: Final = re.compile(r"^Edge\.Cuts$")
_COURTYARD_PATTERN: Final = re.compile(r"^(F|B)\.Courtyard$")


class LayerClassifier:
    """Stateless utility for classifying KiCad layer names.

    All methods are class methods using pre-compiled regex patterns.
    Empty string returns False for all boolean checks and "other" for classify().
    """

    @classmethod
    def is_copper(cls, layer_name: str) -> bool:
        """Return True if layer_name is a copper layer (F.Cu, B.Cu, In1.Cu, etc.)."""
        return bool(_COPPER_PATTERN.match(layer_name))

    @classmethod
    def is_silkscreen(cls, layer_name: str) -> bool:
        """Return True if layer_name is a silkscreen layer (F.SilkS, B.SilkS)."""
        return bool(_SILKSCREEN_PATTERN.match(layer_name))

    @classmethod
    def is_mask(cls, layer_name: str) -> bool:
        """Return True if layer_name is a solder mask layer (F.Mask, B.Mask)."""
        return bool(_MASK_PATTERN.match(layer_name))

    @classmethod
    def is_paste(cls, layer_name: str) -> bool:
        """Return True if layer_name is a solder paste layer (F.Paste, B.Paste)."""
        return bool(_PASTE_PATTERN.match(layer_name))

    @classmethod
    def is_edge_cuts(cls, layer_name: str) -> bool:
        """Return True if layer_name is the Edge.Cuts layer."""
        return bool(_EDGE_CUTS_PATTERN.match(layer_name))

    @classmethod
    def is_courtyard(cls, layer_name: str) -> bool:
        """Return True if layer_name is a courtyard layer (F.Courtyard, B.Courtyard)."""
        return bool(_COURTYARD_PATTERN.match(layer_name))

    @classmethod
    def classify(cls, layer_name: str) -> str:
        """Return the functional category of a KiCad layer name.

        Returns one of: "copper", "silkscreen", "mask", "paste",
        "edge_cuts", "courtyard", or "other" for unrecognized layers.
        """
        if cls.is_copper(layer_name):
            return "copper"
        if cls.is_silkscreen(layer_name):
            return "silkscreen"
        if cls.is_mask(layer_name):
            return "mask"
        if cls.is_paste(layer_name):
            return "paste"
        if cls.is_edge_cuts(layer_name):
            return "edge_cuts"
        if cls.is_courtyard(layer_name):
            return "courtyard"
        return "other"
