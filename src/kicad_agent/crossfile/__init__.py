"""Cross-file operations for maintaining schematic-to-PCB consistency.

XFILE-01: Atomic operations that coordinate mutations across multiple
KiCad files (schematic + PCB pairs) in a single all-or-nothing transaction.
"""

from kicad_agent.crossfile.atomic import AtomicOperation, AtomicResult

__all__ = ["AtomicOperation", "AtomicResult"]
