"""Node feature extraction for bipartite component-net placement graphs.

Extracts fixed-size feature vectors for component nodes and net nodes,
encoding geometric, type, and connectivity information for downstream
GNN-based placement prediction.

Security (threat model):
  T-16-01: Component count cap at 500 enforced in graph construction.
  T-16-02: Bipartite graph avoids O(n^2) edge explosion from power nets.

Usage::

    from kicad_agent.placement.features import (
        extract_component_features,
        extract_net_features,
        COMP_FEATURE_DIM,
        NET_FEATURE_DIM,
    )
"""

from __future__ import annotations

import numpy
from numpy import float32

from kicad_agent.generation.intent import ComponentSpec, NetSpec

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COMP_FEATURE_DIM: int = 32
"""Component feature vector dimensionality."""

NET_FEATURE_DIM: int = 16
"""Net feature vector dimensionality."""

# ---------------------------------------------------------------------------
# Power net identification
# ---------------------------------------------------------------------------

_POWER_NETS: frozenset[str] = frozenset(
    {"GND", "VCC", "+3V3", "+5V", "VDD", "VSS", "GNDA", "VCCA"}
)

# ---------------------------------------------------------------------------
# Size estimation (mirrors PlacementEngine._estimate_size)
# ---------------------------------------------------------------------------


def _estimate_size(comp: ComponentSpec) -> float:
    """Estimate component size heuristic for feature encoding.

    Mirrors PlacementEngine._estimate_size: ICs are large, passives are small.
    """
    ref = comp.reference.upper()
    if ref.startswith("U"):
        return 10.0
    if ref.startswith("Q") or ref.startswith("TR"):
        return 8.0
    if ref.startswith("L") or ref.startswith("D"):
        return 5.0
    if ref.startswith("R") or ref.startswith("C"):
        return 2.0
    return 3.0


# ---------------------------------------------------------------------------
# Component feature extraction
# ---------------------------------------------------------------------------


def extract_component_features(
    comp: ComponentSpec,
    board_width: float,
    board_height: float,
) -> numpy.ndarray:
    """Extract a fixed-size feature vector for a component node.

    Returns a float32 array of length COMP_FEATURE_DIM (32):

    - [0]: estimated_size (IC=10, FET=8, L/D=5, R/C=2, default=3)
    - [1]: is_ic (1.0 if reference starts with 'U')
    - [2]: is_passive (1.0 if reference starts with 'R' or 'C')
    - [3]: is_connector (1.0 if reference starts with 'J')
    - [4]: is_fixed (1.0 if position is not None)
    - [5]: normalized_fixed_x (x / board_width, 0.0 if not fixed)
    - [6]: normalized_fixed_y (y / board_height, 0.0 if not fixed)
    - [7-14]: library_id character hash (first 8 chars, ord(ch)/255.0)
    - [15-22]: value string hash (first 8 chars, ord(ch)/255.0)
    - [23-31]: zero-padded reserved

    Args:
        comp: ComponentSpec to extract features from.
        board_width: Board width in mm (for position normalization).
        board_height: Board height in mm (for position normalization).

    Returns:
        float32 numpy array of shape (COMP_FEATURE_DIM,).
    """
    features = numpy.zeros(COMP_FEATURE_DIM, dtype=float32)

    # [0]: estimated size
    features[0] = _estimate_size(comp)

    # [1]: is_ic
    ref = comp.reference.upper()
    features[1] = 1.0 if ref.startswith("U") else 0.0

    # [2]: is_passive
    features[2] = 1.0 if (ref.startswith("R") or ref.startswith("C")) else 0.0

    # [3]: is_connector
    features[3] = 1.0 if ref.startswith("J") else 0.0

    # [4]: is_fixed
    is_fixed = comp.position is not None
    features[4] = 1.0 if is_fixed else 0.0

    # [5-6]: normalized fixed position
    if is_fixed and board_width > 0 and board_height > 0:
        features[5] = comp.position.x / board_width
        features[6] = comp.position.y / board_height

    # [7-14]: library_id character hash
    lib_chars = comp.library_id[:8]
    for i, ch in enumerate(lib_chars):
        features[7 + i] = ord(ch) / 255.0

    # [15-22]: value string hash
    val_chars = comp.value[:8]
    for i, ch in enumerate(val_chars):
        features[15 + i] = ord(ch) / 255.0

    # [23-31]: reserved (already zero)

    return features


# ---------------------------------------------------------------------------
# Net feature extraction
# ---------------------------------------------------------------------------


def extract_net_features(
    net: NetSpec,
    components: list[ComponentSpec],
) -> numpy.ndarray:
    """Extract a fixed-size feature vector for a net node.

    Returns a float32 array of length NET_FEATURE_DIM (16):

    - [0]: pin_count (number of pins)
    - [1]: component_count (unique component refs from pins)
    - [2]: is_power (1.0 if net name in POWER_NETS set)
    - [3]: criticality (3.0 for high-speed signal, 1.0 for power, 2.0 default)
    - [4]: fanout_ratio (pin_count / max(component_count, 1))
    - [5-15]: zero-padded reserved

    Args:
        net: NetSpec to extract features from.
        components: All components (used for reference lookup).

    Returns:
        float32 numpy array of shape (NET_FEATURE_DIM,).
    """
    features = numpy.zeros(NET_FEATURE_DIM, dtype=float32)

    # [0]: pin_count
    pin_count = len(net.pins)
    features[0] = float(pin_count)

    # [1]: component_count (unique refs from pins)
    comp_refs: set[str] = set()
    for pin in net.pins:
        parts = pin.split(".")
        if parts:
            comp_refs.add(parts[0])
    component_count = len(comp_refs)
    features[1] = float(component_count)

    # [2]: is_power
    is_power = net.name in _POWER_NETS
    features[2] = 1.0 if is_power else 0.0

    # [3]: criticality (power=1.0, high-speed signal=3.0, default=2.0)
    # High-speed signal heuristic: net name contains common high-speed keywords
    _HIGH_SPEED_KEYWORDS = frozenset({
        "SDA", "SCL", "CLK", "MOSI", "MISO", "CS", "TX", "RX",
        "USB", "HDMI", "SPI", "UART", "ETH", "SDIO",
    })
    net_name_upper = net.name.upper()
    is_high_speed = any(kw in net_name_upper for kw in _HIGH_SPEED_KEYWORDS)

    if is_power:
        features[3] = 1.0
    elif is_high_speed:
        features[3] = 3.0
    else:
        features[3] = 2.0

    # [4]: fanout_ratio
    features[4] = pin_count / max(component_count, 1)

    # [5-15]: reserved (already zero)

    return features
