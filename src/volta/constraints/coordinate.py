"""CoordinateConverter for schematic-to-PCB coordinate mapping.

CP-06: Full affine transform (Y-flip, rotation, scale, offset) for
schematic (Y-up) to PCB (Y-down) coordinate conversion.

Defaults to Y-flip (board_height_mm - y) which covers 90% of cases.
Rotation and scale params handle edge cases (rotated boards,
mils-to-mm conversion). Inverse transform (pcb_to_schematic) supports
bidirectional queries.

Usage:
    from volta.constraints.coordinate import CoordinateConverter

    conv = CoordinateConverter(board_height_mm=100.0)
    pcb_pos = conv.schematic_to_pcb((50.0, 25.0))
    # (50.0, 75.0) -- Y-flipped

    original = conv.pcb_to_schematic(pcb_pos)
    # (50.0, 25.0) -- inverse
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class CoordinateConverter:
    """Affine transform for schematic <-> PCB coordinate conversion.

    Transform order for schematic_to_pcb:
    1. Y-flip: (x, board_height_mm - y)
    2. Scale: multiply both coords by self.scale
    3. Rotation: 2D rotation matrix (if rotation_deg != 0)
    4. Offset: add self.offset_x, self.offset_y

    pcb_to_schematic applies the inverse of each step in reverse order.

    Attributes:
        board_height_mm: PCB board height in mm (for Y-flip).
        offset_x: X translation after other transforms.
        offset_y: Y translation after other transforms.
        rotation_deg: Rotation angle in degrees (counterclockwise).
        scale: Uniform scale factor (1.0 = no scaling).
    """

    board_height_mm: float
    offset_x: float = 0.0
    offset_y: float = 0.0
    rotation_deg: float = 0.0
    scale: float = 1.0

    def schematic_to_pcb(self, pos: tuple[float, float]) -> tuple[float, float]:
        """Transform schematic position to PCB coordinate space.

        Args:
            pos: (x, y) position in schematic coordinates (Y-up).

        Returns:
            (x, y) position in PCB coordinates (Y-down + transforms).
        """
        x, y = pos

        # Step 1: Y-flip (schematic Y-up -> PCB Y-down)
        y = self.board_height_mm - y

        # Step 2: Scale
        x *= self.scale
        y *= self.scale

        # Step 3: Rotation (counterclockwise by rotation_deg)
        if self.rotation_deg != 0.0:
            rad = math.radians(self.rotation_deg)
            cos_r = math.cos(rad)
            sin_r = math.sin(rad)
            new_x = x * cos_r - y * sin_r
            new_y = x * sin_r + y * cos_r
            x, y = new_x, new_y

        # Step 4: Offset
        x += self.offset_x
        y += self.offset_y

        return (x, y)

    def pcb_to_schematic(self, pos: tuple[float, float]) -> tuple[float, float]:
        """Inverse transform -- PCB position to schematic space.

        Applies inverse of each step in reverse order.

        Args:
            pos: (x, y) position in PCB coordinates.

        Returns:
            (x, y) position in schematic coordinates (Y-up).
        """
        x, y = pos

        # Inverse step 4: subtract offset
        x -= self.offset_x
        y -= self.offset_y

        # Inverse step 3: inverse rotation (negative angle)
        if self.rotation_deg != 0.0:
            rad = math.radians(-self.rotation_deg)
            cos_r = math.cos(rad)
            sin_r = math.sin(rad)
            new_x = x * cos_r - y * sin_r
            new_y = x * sin_r + y * cos_r
            x, y = new_x, new_y

        # Inverse step 2: divide by scale
        x /= self.scale
        y /= self.scale

        # Inverse step 1: inverse Y-flip
        y = self.board_height_mm - y

        return (x, y)
