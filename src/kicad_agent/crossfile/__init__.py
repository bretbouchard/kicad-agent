"""Cross-file operations for maintaining schematic-to-PCB consistency.

XFILE-01: Atomic operations that coordinate mutations across multiple
KiCad files (schematic + PCB pairs) in a single all-or-nothing transaction.

XFILE-02/XFILE-03: Library reference propagation -- when a symbol or
footprint library reference changes, propagate to all instances.
"""

from kicad_agent.crossfile.atomic import AtomicOperation, AtomicResult
from kicad_agent.crossfile.propagation import (
    PropagationResult,
    propagate_footprint_ref,
    propagate_symbol_ref,
)

__all__ = [
    "AtomicOperation",
    "AtomicResult",
    "PropagationResult",
    "propagate_footprint_ref",
    "propagate_symbol_ref",
]
