"""Layer stackup metadata extracted from KiCad board setup.

SI-02: Extracts copper/dielectric layer metadata including thickness,
copper weight, and dielectric constant for impedance calculations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LayerInfo:
    """Metadata for a single layer in the PCB stackup.

    Attributes:
        name: Layer name (e.g. "F.Cu", "dielectric 1").
        layer_type: Layer type ("copper", "core", "prepreg", or other).
        thickness_mm: Layer thickness in mm (None if not specified).
        material: Material name (e.g. "FR4"). None if not specified.
        epsilon_r: Dielectric constant. None for copper layers or if not specified.
        loss_tangent: Loss tangent. None for copper layers or if not specified.
    """

    name: str
    layer_type: str
    thickness_mm: float | None
    material: str | None
    epsilon_r: float | None
    loss_tangent: float | None


@dataclass(frozen=True)
class LayerStackup:
    """Ordered layer stackup metadata from a KiCad board.

    Frozen dataclass representing the complete layer stackup extracted
    from a kiutils Board object's setup.stackup.

    Attributes:
        layers: Ordered tuple of LayerInfo from top to bottom.
        total_thickness_mm: Total board thickness from board.general.thickness.
    """

    layers: tuple[LayerInfo, ...]
    total_thickness_mm: float

    @property
    def copper_layer_count(self) -> int:
        """Number of copper layers in the stackup."""
        return sum(1 for layer in self.layers if layer.layer_type == "copper")

    @property
    def dielectric_layers(self) -> tuple[LayerInfo, ...]:
        """Subset of layers that are dielectric (core or prepreg)."""
        return tuple(
            layer
            for layer in self.layers
            if layer.layer_type in ("core", "prepreg")
        )

    @staticmethod
    def from_board(board: Any) -> LayerStackup:
        """Extract layer stackup from a kiutils Board object.

        Accesses board.setup.stackup.layers for per-layer metadata
        and board.general.thickness for total board thickness.

        If the board has no explicit stackup definition (stackup is None
        or layers is empty), returns LayerStackup with empty layers tuple
        and copper_layer_count=0.

        Args:
            board: A kiutils Board object with setup and general attributes.

        Returns:
            Frozen LayerStackup instance.
        """
        total_thickness = 0.0
        if hasattr(board, "general") and hasattr(board.general, "thickness"):
            thickness_val = board.general.thickness
            total_thickness = float(thickness_val) if thickness_val is not None else 0.0

        # Handle missing or empty stackup
        if not hasattr(board, "setup") or not hasattr(board.setup, "stackup"):
            return LayerStackup(layers=(), total_thickness_mm=total_thickness)

        stackup = board.setup.stackup
        if stackup is None or not hasattr(stackup, "layers") or not stackup.layers:
            return LayerStackup(layers=(), total_thickness_mm=total_thickness)

        layer_infos: list[LayerInfo] = []
        for sl in stackup.layers:
            # Extract thickness (may be None or string from kiutils)
            thickness_mm: float | None = None
            if hasattr(sl, "thickness") and sl.thickness is not None:
                try:
                    thickness_mm = float(sl.thickness)
                except (ValueError, TypeError):
                    thickness_mm = None

            # Extract material
            material: str | None = None
            if hasattr(sl, "material") and sl.material is not None:
                material = str(sl.material)

            # Extract epsilon_r (dielectric constant)
            epsilon_r: float | None = None
            if hasattr(sl, "epsilonR") and sl.epsilonR is not None:
                try:
                    epsilon_r = float(sl.epsilonR)
                except (ValueError, TypeError):
                    epsilon_r = None

            # Extract loss tangent
            loss_tangent: float | None = None
            if hasattr(sl, "lossTangent") and sl.lossTangent is not None:
                try:
                    loss_tangent = float(sl.lossTangent)
                except (ValueError, TypeError):
                    loss_tangent = None

            layer_type = str(sl.type) if hasattr(sl, "type") and sl.type else ""
            name = str(sl.name) if hasattr(sl, "name") else ""

            layer_infos.append(
                LayerInfo(
                    name=name,
                    layer_type=layer_type,
                    thickness_mm=thickness_mm,
                    material=material,
                    epsilon_r=epsilon_r,
                    loss_tangent=loss_tangent,
                )
            )

        return LayerStackup(
            layers=tuple(layer_infos),
            total_thickness_mm=total_thickness,
        )
