"""LayoutView — frozen dataclass consumed by Convention.check/apply (Plan 01 Task 1).

Phase 100 CR-01: `@dataclass(frozen=True)` — mutation via `dataclasses.replace`.
P1-1 (Council): from_schematic_ir reads ir.components (kiutils_obj.schematicSymbols);
                NEVER calls .serialize() / .write() / .to_file() on the IR.
P1-4 (Council): to_mutations() emits the round-trip dict list that
                SchematicRawWriter.apply_mutations consumes to write back to the
                .kicad_sch file (via atomic_write).
P1-R2-1 (Council Round 2): to_mutations() MUST emit `new_x` / `new_y` keys,
                           NOT `x` / `y`. SchematicRawWriter.apply_mutation reads
                           `new_x` / `new_y` (lines 420-421); legacy `x` / `y`
                           keys are silently ignored and the writer ignores angle.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from kicad_agent.ir.schematic_ir import SchematicIR


@dataclass(frozen=True)
class ComponentView:
    """Read-only projection of a kiutils SchematicSymbol."""

    ref: str
    lib_id: str
    position: tuple[float, float]  # (x_mm, y_mm) — read from symbol.position.X / .Y
    orientation: float  # degrees (0/90/180/270) — read from symbol.position.angle
    bounding_box: tuple[float, float, float, float]  # (min_x, min_y, max_x, max_y)


@dataclass(frozen=True)
class WireView:
    """Read-only projection of a wire (kiutils Connection in graphicalItems)."""

    points: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class LabelView:
    """Read-only projection of a label (kiutils LocalLabel / GlobalLabel)."""

    name: str
    position: tuple[float, float]


@dataclass(frozen=True)
class LayoutView:
    """Read-only projection of a SchematicIR for convention checks and transforms.

    P1-1 contract: built from SchematicIR via from_schematic_ir(). Reads
    `ir.components` (kiutils_obj.schematicSymbols), `ir.schematic.graphicalItems`
    (for wire Connection objects), and `ir.schematic.labels`. Projects each to
    frozen ComponentView / WireView / LabelView tuples. Does NOT copy or serialize
    the IR — wraps it by reference. NEVER calls .serialize() / .write() / .to_file()
    on the IR; downstream writes use LayoutView.to_mutations() →
    SchematicRawWriter.apply_mutations → atomic_write (P1-4 round-trip).
    """

    # schematic_ir may be None for synthetic test layouts (see _empty_layout helper
    # in tests). Convention.apply() implementations tolerate None.
    schematic_ir: Optional[SchematicIR]
    components: tuple[ComponentView, ...] = field(default=())
    wires: tuple[WireView, ...] = field(default=())
    labels: tuple[LabelView, ...] = field(default=())

    @classmethod
    def from_schematic_ir(cls, ir: SchematicIR) -> "LayoutView":
        """Build a LayoutView by projecting SchematicIR components / wires / labels.

        P1-1: Reads `ir.components` (list of kiutils SchematicSymbol). For each
        symbol reads .position.X / .Y / .angle, .libId, and the "Reference"
        property. Bounding box defaults to a small extent around the position
        (the live lib_symbol bounding-extents lookup is deferred — conventions
        check relative positions, not absolute extents, per LO-04).

        NEVER calls .serialize() / .write() / .to_file() on `ir`.
        """
        components: list[ComponentView] = []
        for sym in ir.components:
            ref = _read_reference(sym)
            lib_id = getattr(sym, "libId", "") or ""
            pos = getattr(sym, "position", None)
            x = float(getattr(pos, "X", 0.0) or 0.0) if pos else 0.0
            y = float(getattr(pos, "Y", 0.0) or 0.0) if pos else 0.0
            angle = float(getattr(pos, "angle", 0.0) or 0.0) if pos else 0.0
            # Bounding box: small extent around position. Real per-lib-symbol
            # extents lookup is deferred — conventions check relative spacing,
            # not absolute sizes (LO-04: no coordinates in output).
            bbox = (x - 1.27, y - 1.27, x + 1.27, y + 1.27)
            components.append(
                ComponentView(
                    ref=ref,
                    lib_id=lib_id,
                    position=(x, y),
                    orientation=angle,
                    bounding_box=bbox,
                )
            )

        wires: list[WireView] = []
        schematic = ir.schematic
        graphical = getattr(schematic, "graphicalItems", []) or []
        for item in graphical:
            cls_name = type(item).__name__
            if cls_name != "Connection":
                continue
            pts_raw = getattr(item, "points", None) or []
            pts: list[tuple[float, float]] = []
            for p in pts_raw:
                px = float(getattr(p, "X", 0.0) or 0.0)
                py = float(getattr(p, "Y", 0.0) or 0.0)
                pts.append((px, py))
            if pts:
                wires.append(WireView(points=tuple(pts)))

        labels: list[LabelView] = []
        for label_list_attr in ("labels", "globalLabels", "hierarchicalLabels"):
            label_list = getattr(schematic, label_list_attr, []) or []
            for lbl in label_list:
                name = getattr(lbl, "text", "") or getattr(lbl, "name", "") or ""
                pos = getattr(lbl, "position", None)
                lx = float(getattr(pos, "X", 0.0) or 0.0) if pos else 0.0
                ly = float(getattr(pos, "Y", 0.0) or 0.0) if pos else 0.0
                labels.append(LabelView(name=name, position=(lx, ly)))

        return cls(
            schematic_ir=ir,
            components=tuple(components),
            wires=tuple(wires),
            labels=tuple(labels),
        )

    def to_mutations(self) -> list[dict[str, Any]]:
        """Project this LayoutView's component positions into SchematicRawWriter mutations.

        P1-4 round-trip: Convention.apply() returns a new LayoutView whose
        ComponentView tuples differ from the original. This method projects
        those differences into move_symbol mutation dicts.

        P1-R2-1 (Council Round 2): SchematicRawWriter.apply_mutation reads
        `new_x` / `new_y` keys (lines 420-421 of schematic_raw_writer.py).
        Legacy `x` / `y` keys are silently ignored and the writer ignores the
        `angle` field entirely. We emit `new_x` / `new_y` exclusively.

        Emits one mutation per component:
            {"op": "move_symbol", "ref": <ref>, "new_x": <x>, "new_y": <y>}

        Note: angle is intentionally omitted — the writer cannot apply it
        (Phase 115 will extend the writer to honor angle; tracked as
        DEFERRED-TO-NAMED-TARGET for the IEEE315_PIN_ORIENTATION_01 convention).
        """
        mutations: list[dict[str, Any]] = []
        for comp in self.components:
            mutations.append(
                {
                    "op": "move_symbol",
                    "ref": comp.ref,
                    "new_x": float(comp.position[0]),
                    "new_y": float(comp.position[1]),
                }
            )
        return mutations


def _read_reference(sym: Any) -> str:
    """Read the Reference designator from a kiutils SchematicSymbol."""
    properties = getattr(sym, "properties", None) or []
    for prop in properties:
        if getattr(prop, "key", None) == "Reference":
            return getattr(prop, "value", "") or ""
    # Fallback: some symbols may carry a direct .reference attribute
    ref = getattr(sym, "reference", None)
    if isinstance(ref, str) and ref:
        return ref
    return ""
