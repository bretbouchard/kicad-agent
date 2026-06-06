"""PCB IR -- thin wrapper over a Board object with mutation tracking.

D-05: Holds reference to Board (not a copy).
D-06: Tracks mutations, dirty flag.
D-07: PCB-specific IR.

Supports two Board backends:
  1. NativeBoard (native parser, Plan 01) -- preferred, no UUID loss.
  2. kiutils Board (legacy fallback) -- requires UUID map.

When the native parser succeeds, _native_board is set and PcbIR methods
use NativeBoard attributes directly. When it fails, PcbIR falls back to
the kiutils path and requires a UUID map.

Usage (native path):
    from kicad_agent.ir.pcb_ir import PcbIR
    from kicad_agent.parser.pcb_native_parser import NativeParser

    native_board = NativeParser.parse_pcb(Path("my_board.kicad_pcb"))
    ir = PcbIR.from_native(native_board)
    footprints = ir.footprints

Usage (kiutils fallback):
    from kicad_agent.ir.pcb_ir import PcbIR
    from kicad_agent.parser import parse_pcb
    from kicad_agent.parser.uuid_extractor import extract_uuids

    result = parse_pcb(Path("my_board.kicad_pcb"))
    uuid_map = extract_uuids(result.raw_content, "pcb")
    ir = PcbIR(_parse_result=result, _uuid_map=uuid_map)
    footprints = ir.footprints
"""

import logging
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

from kiutils.board import Board
from kiutils.footprint import Footprint
from kiutils.items.common import Net, Position, Property, Effects

from kicad_agent.ir.base import BaseIR
from kicad_agent.parser.types import ParseResult
from kicad_agent.parser.uuid_extractor import UUIDMap

if TYPE_CHECKING:
    from kicad_agent.parser.pcb_native_types import (
        NativeBoard,
        NativeNet,
        NativeFootprint,
        NativePad,
    )

logger = logging.getLogger(__name__)


@dataclass
class PcbIR(BaseIR):
    """Thin wrapper over a Board object with mutation tracking.

    D-05: Holds reference to Board (not a copy).
    D-06: Tracks mutations, dirty flag, UUID map reference.
    D-07: PCB-specific IR.

    Supports NativeBoard (preferred) and kiutils Board (fallback).
    When _native_board is set, UUID map is not required.
    """

    _raw_written: bool = False  # Set when raw sexp manipulation writes the file directly
    _native_board: "NativeBoard | None" = None

    @property
    def raw_written(self) -> bool:
        """Whether raw S-expression manipulation has written the file directly.

        When True, the executor skips kiutils serialization to avoid data loss.
        """
        return self._raw_written

    @property
    def _is_native(self) -> bool:
        """Whether this IR wraps a NativeBoard (True) or kiutils Board (False)."""
        return self._native_board is not None

    @classmethod
    def from_native(cls, native_board: "NativeBoard") -> "PcbIR":
        """Create PcbIR from a NativeBoard (no kiutils dependency).

        Args:
            native_board: Parsed NativeBoard from NativeParser.

        Returns:
            PcbIR instance backed by NativeBoard. No UUID map required.
        """
        # Create a minimal ParseResult -- kiutils_obj is the NativeBoard itself
        parse_result = ParseResult(
            kiutils_obj=native_board,
            raw_content=native_board.raw_content,
            file_path=Path(native_board.file_path) if native_board.file_path else Path(""),
            file_type="pcb",
        )
        return cls(_parse_result=parse_result, _uuid_map=None, _native_board=native_board)

    def __post_init__(self) -> None:
        """Validate file type matches PCB. UUID map only required for kiutils path."""
        super().__post_init__()
        if self.file_type != "pcb":
            raise ValueError(
                f"Expected file_type='pcb', got {self.file_type!r}"
            )
        # UUID map required only for kiutils fallback (native path preserves UUIDs)
        if self._native_board is None and self._uuid_map is None:
            raise ValueError(
                "PcbIR requires a UUID map for kiutils serialization. "
                "kiutils drops all UUID tokens from PCB files. "
                "Use extract_uuids() from kicad_agent.parser.uuid_extractor, "
                "or use PcbIR.from_native() with NativeParser."
            )

    @property
    def board(self) -> Any:
        """Direct access to the underlying Board object.

        Returns NativeBoard when native parser succeeded, kiutils Board otherwise.
        """
        if self._native_board is not None:
            return self._native_board
        return self._parse_result.kiutils_obj

    @property
    def footprints(self) -> list:
        """Access to PCB footprints."""
        if self._native_board is not None:
            return self._native_board.footprints
        return self._parse_result.kiutils_obj.footprints

    @property
    def nets(self) -> list:
        """Access to PCB nets."""
        if self._native_board is not None:
            return self._native_board.nets
        return self._parse_result.kiutils_obj.nets

    @property
    def trace_items(self) -> list:
        """Access to PCB trace items (segments, arcs, vias)."""
        return self.board.traceItems

    # -------------------------------------------------------------------
    # Net mutation methods
    # -------------------------------------------------------------------

    def add_net(self, net_name: str = "", net_number: Optional[int] = None) -> Any:
        """Add a new net to the PCB.

        Args:
            net_name: Net name. Empty string triggers auto-generation as "N_<number>".
            net_number: Explicit net number. None triggers auto-assignment (max existing + 1).

        Returns:
            The created Net or NativeNet object.

        Raises:
            ValueError: If net_name already exists (when explicitly named).
        """
        # Auto-assign net number: max existing + 1
        if net_number is None:
            max_num = max((n.number for n in self.board.nets), default=0)
            net_number = max_num + 1

        # Auto-generate name if empty
        if net_name == "":
            net_name = f"N_{net_number}"

        # Check for duplicate name
        if self.get_net_by_name(net_name) is not None:
            raise ValueError(f"Net '{net_name}' already exists")

        # Check for duplicate net number
        for n in self.board.nets:
            if n.number == net_number:
                raise ValueError(f"Net number {net_number} already in use by '{n.name}'")

        if self._is_native:
            from kicad_agent.parser.pcb_native_types import NativeNet
            net = NativeNet(number=net_number, name=net_name)
        else:
            net = Net(number=net_number, name=net_name)

        self.board.nets.append(net)
        self._record_mutation("add_net", {
            "net_name": net_name,
            "net_number": net_number,
        })
        return net

    def remove_net(self, net_name: str) -> None:
        """Remove a net from the PCB, disconnecting all pads.

        Raises:
            ValueError: If net_name not found, or net_name is "" (net 0 is reserved).
        """
        if net_name == "":
            raise ValueError("Cannot remove net 0 (reserved unconnected net)")

        net = self.get_net_by_name(net_name)
        if net is None:
            raise ValueError(f"Net '{net_name}' not found")

        # Disconnect all pads connected to this net
        for fp in self.board.footprints:
            for pad in fp.pads:
                if self._is_native:
                    # NativePad has .net_name directly
                    if pad.net_name == net_name:
                        pad.net_name = ""
                        pad.net_number = 0
                else:
                    # kiutils pad has .net (Net object)
                    if pad.net is not None and pad.net.name == net_name:
                        pad.net = None

        # Remove the net from the board in-place (avoids stale list references)
        self.board.nets[:] = [n for n in self.board.nets if n.name != net_name]
        self._record_mutation("remove_net", {"net_name": net_name})

    def rename_net(self, old_name: str, new_name: str) -> None:
        """Rename a net, propagating to all connected pads.

        Raises:
            ValueError: If old_name not found or new_name already exists.
        """
        net = self.get_net_by_name(old_name)
        if net is None:
            raise ValueError(f"Net '{old_name}' not found")

        if self.get_net_by_name(new_name) is not None:
            raise ValueError(f"Net '{new_name}' already exists")

        if self._is_native:
            # Update the net in board.nets
            for i, n in enumerate(self.board.nets):
                if n.name == old_name:
                    n.name = new_name
                    break

            # Propagate to all connected pads
            for fp in self.board.footprints:
                for pad in fp.pads:
                    if pad.net_name == old_name:
                        pad.net_name = new_name
        else:
            # Update the net in board.nets
            for i, n in enumerate(self.board.nets):
                if n.name == old_name:
                    self.board.nets[i] = Net(number=n.number, name=new_name)
                    break

            # Propagate to all connected pads (create new Net to avoid shared reference)
            for fp in self.board.footprints:
                for pad in fp.pads:
                    if pad.net is not None and pad.net.name == old_name:
                        pad.net = Net(number=pad.net.number, name=new_name)

        self._record_mutation("rename_net", {
            "old_name": old_name,
            "new_name": new_name,
        })

    def get_net_by_name(self, net_name: str) -> Any:
        """Find a net by name. Returns None if not found."""
        for n in self.board.nets:
            if n.name == net_name:
                return n
        return None

    def get_net_pads(self, net_name: str) -> list[tuple[str, str]]:
        """Get all (footprint_libId, pad_number) tuples for pads on the named net.

        Returns:
            List of (footprint_libId, pad_number) tuples.
            Empty list if net not found or no pads connected.
        """
        pads: list[tuple[str, str]] = []
        for fp in self.board.footprints:
            fp_lib_id = getattr(fp, "lib_id", None) or getattr(fp, "libId", "")
            for pad in fp.pads:
                if self._is_native:
                    if pad.net_name == net_name:
                        pads.append((fp_lib_id, pad.number))
                else:
                    if pad.net is not None and pad.net.name == net_name:
                        pads.append((fp_lib_id, pad.number))
        return pads

    # -------------------------------------------------------------------
    # Footprint query and mutation methods
    # -------------------------------------------------------------------

    def get_footprint_by_ref(self, reference: str) -> Optional[Any]:
        """Find a PCB footprint by its reference designator.

        KiCad footprints store the reference in the properties dict with
        key 'Reference'.

        Args:
            reference: Reference designator to search for (e.g. "J1").

        Returns:
            kiutils Footprint object, or None if not found.
        """
        for fp in self.board.footprints:
            ref = fp.properties.get("Reference", "")
            if ref == reference:
                return fp
        return None

    def swap_footprint(self, reference: str, new_footprint_lib_id: str) -> dict[str, Any]:
        """Swap a footprint while preserving all pad-to-net connections.

        This changes the footprint's lib_id but preserves pad net assignments
        for pads that exist in the new footprint (by matching pad numbers).

        IMPORTANT: This does NOT reload the footprint geometry from the library.
        It only updates the lib_id string and preserves pad net connections.

        Args:
            reference: Reference designator of the footprint to swap.
            new_footprint_lib_id: New footprint library reference.

        Returns:
            Dict with 'old_lib_id', 'new_lib_id', 'preserved_nets' count.

        Raises:
            ValueError: If reference not found.
        """
        fp = self.get_footprint_by_ref(reference)
        if fp is None:
            raise ValueError(f"Footprint '{reference}' not found")

        old_lib_id = getattr(fp, "lib_id", None) or getattr(fp, "libId", "")

        if self._is_native:
            # Save current pad-to-net mapping
            pad_nets: dict[str, tuple[str, int]] = {}
            for pad in fp.pads:
                if pad.net_name:
                    pad_nets[pad.number] = (pad.net_name, pad.net_number)

            # Update the lib_id
            fp.lib_id = new_footprint_lib_id

            # Restore pad nets for matching pad numbers
            preserved_count = 0
            for pad in fp.pads:
                if pad.number in pad_nets:
                    pad.net_name, pad.net_number = pad_nets[pad.number]
                    preserved_count += 1
                else:
                    pad.net_name = ""
                    pad.net_number = 0
        else:
            # Save current pad-to-net mapping
            pad_nets_k: dict[str, Any] = {}
            for pad in fp.pads:
                if pad.net is not None:
                    pad_nets_k[pad.number] = Net(number=pad.net.number, name=pad.net.name)

            # Update the libId
            fp.libId = new_footprint_lib_id

            # Restore pad nets for matching pad numbers
            preserved_count = 0
            for pad in fp.pads:
                if pad.number in pad_nets_k:
                    pad.net = Net(number=pad_nets_k[pad.number].number, name=pad_nets_k[pad.number].name)
                    preserved_count += 1
                else:
                    pad.net = None

        self._record_mutation("swap_footprint", {
            "reference": reference,
            "old_lib_id": old_lib_id,
            "new_lib_id": new_footprint_lib_id,
            "preserved_nets": preserved_count,
        })

        return {
            "old_lib_id": old_lib_id,
            "new_lib_id": new_footprint_lib_id,
            "preserved_nets": preserved_count,
        }

    def update_footprint_from_library(
        self,
        reference: str,
        lib_id_override: Optional[str] = None,
        pcb_path: Optional[Path] = None,
    ) -> dict[str, Any]:
        """Reload a footprint's geometry from the library, preserving placement.

        Loads the fresh footprint definition from the library .kicad_mod file
        and replaces the geometry in the PCB while preserving position, rotation,
        reference designator, value, and pad-to-net connections.

        This uses raw S-expression replacement rather than kiutils serialization
        to avoid data loss (kiutils drops UUIDs and reformats the entire file).

        Args:
            reference: Reference designator of the footprint to update.
            lib_id_override: Optional new lib_id. None = refresh from existing library.
            pcb_path: Path to the PCB file (needed for library resolution).

        Returns:
            Dict with update details: lib_id, preserved_nets, lost_nets, new_pads.

        Raises:
            ValueError: If reference not found or library cannot be resolved.
        """
        from kicad_agent.lib_resolver import resolve_footprint_path

        fp = self.get_footprint_by_ref(reference)
        if fp is None:
            raise ValueError(f"Footprint '{reference}' not found")

        if self._is_native:
            lib_id = lib_id_override or fp.lib_id
            saved_angle = fp.position[2] if len(fp.position) > 2 else 0.0
            saved_x, saved_y = fp.position[0], fp.position[1]
            saved_lib_id = fp.lib_id

            pad_nets: dict[str, tuple[str, str]] = {}
            for pad in fp.pads:
                if pad.net_name:
                    pad_nets[pad.number] = (pad.net_name, "")
        else:
            lib_id = lib_id_override or fp.libId
            saved_angle = fp.position.angle if fp.position.angle is not None else 0.0
            saved_x, saved_y = fp.position.X, fp.position.Y
            saved_lib_id = fp.libId

            pad_nets: dict[str, tuple[str, str]] = {}
            for pad in fp.pads:
                if pad.net is not None:
                    pad_nets[pad.number] = (pad.net.name, "")

        # --- Save state to preserve ---
        saved_position = f"(at {saved_x} {saved_y}"
        if saved_angle != 0.0:
            saved_position += f" {saved_angle}"
        saved_position += ")"

        saved_reference = fp.properties.get("Reference", "")
        saved_value = fp.properties.get("Value", "")
        saved_layer = fp.layer

        # --- Save PCB-embedded-only fields from raw content ---
        # These fields exist only in PCB-embedded footprints, not in library .kicad_mod files
        raw_content = self._parse_result.raw_content
        old_fp_start, old_fp_end = _find_footprint_block(raw_content, reference)
        if old_fp_start is None:
            raise ValueError(
                f"Could not find footprint block for '{reference}' in raw content"
            )
        old_raw_block = raw_content[old_fp_start:old_fp_end]

        # Extract PCB-embedded-only fields and dedent by one tab level.
        # Old block lines are at \t\t level; after embedding adds one tab,
        # they'd become \t\t\t. Dedenting to \t ensures correct \t\t after embedding.
        saved_uuid = _extract_field(old_raw_block, r'^\t\t\(uuid "([^"]+)"\)', 'footprint UUID')
        saved_path_line = _dedent_one_tab(_extract_raw_line(old_raw_block, r'^\t\t\(path '))
        saved_sheetname_line = _dedent_one_tab(_extract_raw_line(old_raw_block, r'^\t\t\(sheetname '))
        saved_sheetfile_line = _dedent_one_tab(_extract_raw_line(old_raw_block, r'^\t\t\(sheetfile '))
        saved_units_block = _dedent_one_tab(_extract_raw_block(old_raw_block, r'^\t\t\(units'))
        saved_ki_fp_filters = _dedent_one_tab(_extract_raw_line(old_raw_block, r'^\t\t\(property ki_fp_filters'))

        # --- Resolve and load library footprint ---
        if pcb_path is None:
            pcb_path = self._parse_result.file_path
        mod_path = resolve_footprint_path(lib_id, pcb_path)
        lib_content = mod_path.read_text(encoding="utf-8")

        # --- Build replacement footprint S-expression ---
        # Build the new footprint from library content
        # The library .kicad_mod is a complete footprint file - extract the top-level sexp
        new_fp_sexpr = lib_content.strip()

        # Strip library-only fields that don't belong in embedded PCB footprints
        new_fp_sexpr = _strip_library_metadata(new_fp_sexpr)

        # Inject preserved state into the new footprint S-expression
        new_fp_sexpr = _inject_lib_id(new_fp_sexpr, lib_id)
        new_fp_sexpr = _inject_at_position(new_fp_sexpr, saved_position)
        new_fp_sexpr = _inject_layer(new_fp_sexpr, saved_layer)
        new_fp_sexpr = _inject_reference(new_fp_sexpr, saved_reference)
        new_fp_sexpr = _inject_value(new_fp_sexpr, saved_value)

        # Re-inject PCB-embedded-only fields
        if saved_uuid:
            new_fp_sexpr = _insert_after_field(new_fp_sexpr, r'^\t\(layer "[^"]*"\)', f'\n\t(uuid "{saved_uuid}")')
        if saved_path_line:
            new_fp_sexpr = _insert_before_attr(new_fp_sexpr, saved_path_line)
        if saved_sheetname_line:
            new_fp_sexpr = _insert_before_attr(new_fp_sexpr, saved_sheetname_line)
        if saved_sheetfile_line:
            new_fp_sexpr = _insert_before_attr(new_fp_sexpr, saved_sheetfile_line)
        if saved_units_block:
            new_fp_sexpr = _insert_before_attr(new_fp_sexpr, saved_units_block)
        if saved_ki_fp_filters:
            new_fp_sexpr = _insert_before_attr(new_fp_sexpr, saved_ki_fp_filters)

        # Restore pad net assignments
        preserved_count = 0
        lost_nets: list[str] = []
        new_pad_numbers: list[str] = []
        for pad_num, (net_name, _) in pad_nets.items():
            result = _inject_pad_net(new_fp_sexpr, pad_num, net_name)
            if result is not None:
                new_fp_sexpr = result
                preserved_count += 1
            else:
                lost_nets.append(f"{pad_num}:{net_name}")

        # Check for pads in new footprint that weren't in old
        old_pad_nums = set(pad_nets.keys())
        new_fp_pads = _extract_pad_numbers(new_fp_sexpr)
        for pn in new_fp_pads:
            if pn not in old_pad_nums:
                new_pad_numbers.append(pn)

        # --- Replace in raw content ---
        # The footprint block must be indented with one tab (top-level under kicad_pcb)
        new_fp_indented = "\t" + new_fp_sexpr.replace("\n", "\n\t")
        new_raw = raw_content[:old_fp_start] + new_fp_indented + raw_content[old_fp_end:]

        # Write atomically via executor helper (Council C-02)
        from kicad_agent.ops.executor import OperationExecutor

        file_path = self._parse_result.file_path
        OperationExecutor._raw_write_atomic(file_path, new_raw)
        self._parse_result = replace(self._parse_result, raw_content=new_raw)
        self._raw_written = True

        self._record_mutation("update_footprint_from_library", {
            "reference": reference,
            "lib_id": lib_id,
            "old_lib_id": saved_lib_id,
            "preserved_nets": preserved_count,
            "lost_nets": lost_nets,
            "new_pads": new_pad_numbers,
        })

        return {
            "reference": reference,
            "lib_id": lib_id,
            "old_lib_id": saved_lib_id,
            "preserved_nets": preserved_count,
            "lost_nets": lost_nets,
            "new_pads": new_pad_numbers,
        }

    def get_footprint_pads(self, reference: str) -> list[tuple[str, str]]:
        """Get (pad_number, net_name) tuples for a footprint.

        Args:
            reference: Reference designator of the footprint.

        Returns:
            List of (pad_number, net_name) tuples. Unconnected pads have net_name="".
        """
        fp = self.get_footprint_by_ref(reference)
        if fp is None:
            return []
        result: list[tuple[str, str]] = []
        for pad in fp.pads:
            if self._is_native:
                net_name = pad.net_name
            else:
                net_name = pad.net.name if pad.net is not None else ""
            result.append((pad.number, net_name))
        return result

    def get_board_bounds(self) -> tuple[float, float, float, float] | None:
        """Extract board outline bounds as (x_min, y_min, x_max, y_max).

        Uses the first graphic line on Edge.Cuts to approximate bounds.
        Returns None if no board outline is found.

        Returns:
            Tuple of (x_min, y_min, x_max, y_max) in mm, or None.
        """
        segments: list[tuple[float, float]] = []
        for graphic in self.board.graphicItems:
            if getattr(graphic, 'layer', None) == "Edge.Cuts":
                start = getattr(graphic, 'start', None)
                end = getattr(graphic, 'end', None)
                if start is not None and end is not None:
                    segments.append((start.X, start.Y))
                    segments.append((end.X, end.Y))
                elif getattr(graphic, 'center', None) is not None:
                    cx, cy = graphic.center.X, graphic.center.Y
                    r = getattr(graphic, 'radius', getattr(graphic, 'end', None))
                    if r is not None:
                        radius = r.X - cx if hasattr(r, 'X') else float(r)
                        segments.append((cx - radius, cy - radius))
                        segments.append((cx + radius, cy + radius))

        # Also check footprint graphics on Edge.Cuts
        for fp in self.footprints:
            fp_gi = getattr(fp, 'graphic_items', None) or getattr(fp, 'graphicItems', [])
            for graphic in fp_gi:
                if getattr(graphic, 'layer', None) == "Edge.Cuts":
                    start = getattr(graphic, 'start', None)
                    end = getattr(graphic, 'end', None)
                    if start is not None and end is not None:
                        fp_pos = fp.position
                        if hasattr(fp_pos, 'X'):
                            fp_x, fp_y = fp_pos.X, fp_pos.Y
                        else:
                            fp_x = fp_pos[0] if len(fp_pos) > 0 else 0.0
                            fp_y = fp_pos[1] if len(fp_pos) > 1 else 0.0
                        segments.append((start.X + fp_x, start.Y + fp_y))
                        segments.append((end.X + fp_x, end.Y + fp_y))

        if not segments:
            return None

        xs = [s[0] for s in segments]
        ys = [s[1] for s in segments]
        return (min(xs), min(ys), max(xs), max(ys))

    def extract_netlist(self) -> dict[str, list[tuple[float, float]]]:
        """Extract netlist mapping net names to pad positions.

        Returns:
            Dict mapping net name to list of (x, y) pad positions in mm.
        """
        netlist: dict[str, list[tuple[float, float]]] = {}
        for fp in self.footprints:
            fp_pos = fp.position
            if hasattr(fp_pos, 'X'):
                fp_x, fp_y = fp_pos.X, fp_pos.Y
            else:
                fp_x = fp_pos[0] if len(fp_pos) > 0 else 0.0
                fp_y = fp_pos[1] if len(fp_pos) > 1 else 0.0

            for pad in fp.pads:
                if self._is_native:
                    if pad.net_name:
                        pad_pos = pad.position
                        pad_x = fp_x + (pad_pos[0] if len(pad_pos) > 0 else 0.0)
                        pad_y = fp_y + (pad_pos[1] if len(pad_pos) > 1 else 0.0)
                        net_name = pad.net_name
                        if net_name not in netlist:
                            netlist[net_name] = []
                        netlist[net_name].append((round(pad_x, 4), round(pad_y, 4)))
                else:
                    if pad.net is not None and pad.net.name:
                        pad_x = fp_x + (pad.position.X if hasattr(pad.position, 'X') else 0)
                        pad_y = fp_y + (pad.position.Y if hasattr(pad.position, 'Y') else 0)
                        net_name = pad.net.name
                        if net_name not in netlist:
                            netlist[net_name] = []
                        netlist[net_name].append((round(pad_x, 4), round(pad_y, 4)))
        return netlist

    def extract_obstacles(
        self,
        clearance_mm: float = 0.3,
    ) -> list:
        """Extract SpatialBox obstacles from all placed footprints.

        For each footprint, extracts courtyard bounding boxes (F.CrtYd / B.CrtYd
        graphic items) as forbidden routing zones. If no courtyard is defined,
        computes a bounding box from pad positions plus clearance margin.

        Args:
            clearance_mm: Extra clearance margin around obstacles in mm.
                Defaults to 0.3mm (sufficient for most SMD clearances).

        Returns:
            List of SpatialBox objects for use by RoutingGraph.
        """
        from kicad_agent.spatial.primitives import SpatialBox

        obstacles: list[SpatialBox] = []

        for fp in self.footprints:
            fp_pos = fp.position
            if hasattr(fp_pos, "__len__") and len(fp_pos) >= 2:
                fp_x = fp_pos[0] if len(fp_pos) > 0 else 0.0
                fp_y = fp_pos[1] if len(fp_pos) > 1 else 0.0
                fp_angle = fp_pos[2] if len(fp_pos) > 2 else 0.0
            elif hasattr(fp_pos, "X"):
                fp_x, fp_y = fp_pos.X, fp_pos.Y
                fp_angle = getattr(fp_pos, "angle", None) or 0.0
            else:
                continue

            ref = fp.properties.get("Reference", fp.reference if hasattr(fp, "reference") else "?")

            # Strategy 1: Use courtyard data if available.
            # NativeBoard uses graphic_items with rect items.
            # kiutils uses graphicItems with FpLine segments.
            courtyard_found = False
            courtyard_xs: list[float] = []
            courtyard_ys: list[float] = []

            # Try native format (graphic_items with rects).
            graphic_items = getattr(fp, "graphic_items", None) or []
            for gi in graphic_items:
                if (getattr(gi, "item_type", None) == "rect"
                        and getattr(gi, "layer", None) in ("F.CrtYd", "B.CrtYd")):
                    if gi.start is not None and gi.end is not None:
                        courtyard_xs.extend([gi.start.X, gi.end.X])
                        courtyard_ys.extend([gi.start.Y, gi.end.Y])
                        courtyard_found = True

            # Try kiutils format (graphicItems with lines).
            if not courtyard_found:
                graphic_items_ki = getattr(fp, "graphicItems", None) or []
                for gi in graphic_items_ki:
                    layer = getattr(gi, "layer", "")
                    if layer in ("F.CrtYd", "B.CrtYd"):
                        if (hasattr(gi, "start") and gi.start is not None
                                and hasattr(gi, "end") and gi.end is not None):
                            courtyard_xs.extend([gi.start.X, gi.end.X])
                            courtyard_ys.extend([gi.start.Y, gi.end.Y])
                            courtyard_found = True

            if courtyard_found and courtyard_xs:
                x1 = min(courtyard_xs)
                y1 = min(courtyard_ys)
                x2 = max(courtyard_xs)
                y2 = max(courtyard_ys)
                # Apply footprint rotation to courtyard corners.
                if fp_angle != 0.0:
                    import math as _math
                    _rad = _math.radians(fp_angle)
                    _cos = _math.cos(_rad)
                    _sin = _math.sin(_rad)
                    corners = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
                    rotated = [
                        (fp_x + cx * _cos - cy * _sin,
                         fp_y + cx * _sin + cy * _cos)
                        for cx, cy in corners
                    ]
                    rxs = [c[0] for c in rotated]
                    rys = [c[1] for c in rotated]
                    x1, y1 = min(rxs), min(rys)
                    x2, y2 = max(rxs), max(rys)
                else:
                    x1 += fp_x
                    y1 += fp_y
                    x2 += fp_x
                    y2 += fp_y
                obstacles.append(SpatialBox(
                    x1=round(x1 - clearance_mm, 4),
                    y1=round(y1 - clearance_mm, 4),
                    x2=round(x2 + clearance_mm, 4),
                    y2=round(y2 + clearance_mm, 4),
                    entity_type="footprint",
                    entity_id=fp.uuid if hasattr(fp, "uuid") else "",
                    layer="F.CrtYd",
                    reference=ref,
                ))
                continue

            if courtyard_found:
                continue

            # Strategy 2: Compute bounding box from pads + margin.
            pad_xs: list[float] = []
            pad_ys: list[float] = []
            for pad in fp.pads:
                pad_pos = pad.position
                if hasattr(pad_pos, "X"):
                    local_x, local_y = pad_pos.X, pad_pos.Y
                elif hasattr(pad_pos, "__len__") and len(pad_pos) >= 2:
                    local_x = pad_pos[0]
                    local_y = pad_pos[1]
                else:
                    continue
                if fp_angle != 0.0:
                    import math as _math
                    _rad = _math.radians(fp_angle)
                    _cos = _math.cos(_rad)
                    _sin = _math.sin(_rad)
                    px = fp_x + local_x * _cos - local_y * _sin
                    py = fp_y + local_x * _sin + local_y * _cos
                else:
                    px = fp_x + local_x
                    py = fp_y + local_y
                pad_xs.append(px)
                pad_ys.append(py)

            if pad_xs:
                # Add pad half-size estimate as extra margin
                obstacles.append(SpatialBox(
                    x1=round(min(pad_xs) - clearance_mm, 4),
                    y1=round(min(pad_ys) - clearance_mm, 4),
                    x2=round(max(pad_xs) + clearance_mm, 4),
                    y2=round(max(pad_ys) + clearance_mm, 4),
                    entity_type="footprint",
                    entity_id=fp.uuid if hasattr(fp, "uuid") else "",
                    layer="",
                    reference=ref,
                ))

        return obstacles

    def extract_net_id_map(self) -> dict[str, int]:
        """Extract mapping from net name to net ID number.

        Returns:
            Dict mapping net names to their integer net ID.
        """
        net_map: dict[str, int] = {}
        if self._is_native:
            for net in self.board.nets:
                net_map[net.name] = net.number
        else:
            for net in self.board.nets:
                net_map[net.name] = net.number
        return net_map

    def extract_net_path(self, net_name: str) -> tuple[tuple[float, float], ...]:
        """Extract ordered waypoints for a net's route from board segments.

        Walks the segment list, groups segments by net, and builds an
        ordered path by connecting adjacent endpoints.

        Args:
            net_name: Net name to extract route for.

        Returns:
            Tuple of (x, y) waypoints, or empty tuple if net has no segments.
        """
        board = self.board
        segments = board.segments if hasattr(board, "segments") else []
        if not segments:
            return ()

        # Collect segments matching the net.
        net_segs: list[tuple[tuple[float, float], tuple[float, float]]] = []
        for seg in segments:
            seg_net = getattr(seg, "net", "")
            if str(seg_net) != net_name:
                continue
            start = getattr(seg, "start", None)
            end = getattr(seg, "end", None)
            if start is None or end is None:
                continue
            sx = float(getattr(start, "x", getattr(start, "X", 0)))
            sy = float(getattr(start, "y", getattr(start, "Y", 0)))
            ex = float(getattr(end, "x", getattr(end, "X", 0)))
            ey = float(getattr(end, "y", getattr(end, "Y", 0)))
            net_segs.append(((sx, sy), (ex, ey)))

        if not net_segs:
            return ()

        # Build ordered path by chaining segments endpoint-to-endpoint.
        path: list[tuple[float, float]] = [net_segs[0][0], net_segs[0][1]]
        used: set[int] = {0}
        max_iters = len(net_segs)

        for _ in range(max_iters):
            last = path[-1]
            found = False
            for i, (s, e) in enumerate(net_segs):
                if i in used:
                    continue
                if abs(s[0] - last[0]) < 0.01 and abs(s[1] - last[1]) < 0.01:
                    path.append(e)
                    used.add(i)
                    found = True
                    break
                if abs(e[0] - last[0]) < 0.01 and abs(e[1] - last[1]) < 0.01:
                    path.append(s)
                    used.add(i)
                    found = True
                    break
            if not found:
                break

        return tuple(path)

    def insert_track_segments(self, sexpr_block: str) -> None:
        """Insert track segment S-expressions into the PCB file.

        Appends the segments before the closing ) of the .kicad_pcb file.
        Delegates to PcbRawWriter for content manipulation (Council C-02).
        """
        from kicad_agent.ops.executor import OperationExecutor
        from kicad_agent.ops.pcb_raw_writer import PcbRawWriter

        raw = self._parse_result.raw_content
        new_raw = PcbRawWriter.insert_segments(raw, sexpr_block)
        if new_raw == raw:
            return
        self._parse_result = replace(self._parse_result, raw_content=new_raw)
        OperationExecutor._raw_write_atomic(self._parse_result.file_path, new_raw)
        self._raw_written = True
        self.mark_dirty("insert_track_segments")

    def _update_parse_result(self, new_result: ParseResult, new_uuid_map: UUIDMap) -> None:
        """Update parse result after raw content write.

        Re-parses the file to keep the in-memory kiutils Board in sync
        with raw S-expression modifications. Handles IR registry bookkeeping.
        """
        from kicad_agent.ir.base import _ir_registry, _ir_registry_lock

        old_id = id(self._parse_result)
        new_id = id(new_result)
        with _ir_registry_lock:
            _ir_registry.discard(old_id)
            if new_id in _ir_registry:
                raise RuntimeError("New ParseResult already has an IR wrapper")
            _ir_registry.add(new_id)
        self._parse_result = new_result
        self._uuid_map = new_uuid_map
        self._raw_written = True


def _restore_properties(
    fp: Footprint, reference: str, value: str
) -> None:
    """Restore Reference and Value properties on a freshly-loaded footprint.

    kiutils stores footprint properties as a plain dict.
    """
    fp.properties["Reference"] = reference
    fp.properties["Value"] = value


# ---------------------------------------------------------------------------
# Raw S-expression helpers for PCB footprint replacement
# ---------------------------------------------------------------------------


def _find_footprint_block(content: str, reference: str) -> tuple[Optional[int], Optional[int]]:
    """Find the start and end positions of a footprint block by reference.

    Delegates to PcbRawWriter._find_footprint_block (Council C-02 consolidation).
    """
    from kicad_agent.ops.pcb_raw_writer import PcbRawWriter
    return PcbRawWriter._find_footprint_block(content, reference)


def _find_matching_close(content: str, open_pos: int) -> Optional[int]:
    """Find the matching closing paren for an S-expression.

    Delegates to PcbRawWriter._find_matching_close (Council C-02 consolidation).
    """
    from kicad_agent.ops.pcb_raw_writer import PcbRawWriter
    return PcbRawWriter._find_matching_close(content, open_pos)


def _strip_library_metadata(sexp: str) -> str:
    """Remove library-only fields that don't belong in embedded PCB footprints.

    KiCad library .kicad_mod files include version/generator/compatibility fields
    that are not valid inside a PCB's embedded footprint blocks.
    """
    # Remove (version ...), (generator "..."), (generator_version "...")
    # In the library file these are at single-tab indent under (footprint ...)
    for pattern in [
        r'^\t\(version [^\)]*\)\s*\n',
        r'^\t\(generator "[^"]*"\)\s*\n',
        r'^\t\(generator_version "[^"]*"\)\s*\n',
        r'^\t\(compatibility "[^"]*"\s*\([^\)]*\)\)\s*\n',
    ]:
        sexp = re.sub(pattern, '', sexp, flags=re.MULTILINE)
    return sexp


def _inject_lib_id(sexp: str, lib_id: str) -> str:
    """Replace the footprint's lib_id in the (footprint "LIB:NAME" ...) S-expression."""
    safe = _escape_sexpr_value(lib_id)
    return re.sub(
        r'^\(footprint "([^"]*)"',
        f'(footprint "{safe}"',
        sexp,
        count=1,
    )


def _inject_at_position(sexp: str, at_sexp: str) -> str:
    """Replace or insert the (at ...) position in the footprint S-expression.

    Library footprints don't have (at ...), so we insert it after (layer "...").
    """

    # Try to replace existing (at ...)
    at_pattern = re.compile(r'^\t\(at [^\)]*\)', re.MULTILINE)
    if at_pattern.search(sexp):
        return at_pattern.sub(f'\t{at_sexp}', sexp, count=1)

    # No existing (at ...) — insert after (layer "...") line
    layer_match = re.search(r'^\t\(layer "[^"]*"\)\s*$', sexp, re.MULTILINE)
    if layer_match:
        insert_pos = layer_match.end()
        return sexp[:insert_pos] + f'\n\t{at_sexp}' + sexp[insert_pos:]

    # Fallback: insert after the first (property ...) block
    prop_match = re.search(r'^\t\(property ', sexp, re.MULTILINE)
    if prop_match:
        insert_pos = prop_match.start()
        return sexp[:insert_pos] + f'\t{at_sexp}\n' + sexp[insert_pos:]

    return sexp


def _inject_layer(sexp: str, layer: str) -> str:
    """Replace the (layer "...") in the footprint S-expression."""
    safe = _escape_sexpr_value(layer)
    return re.sub(
        r'^\t\(layer "[^"]*"\)',
        f'\t(layer "{safe}")',
        sexp,
        count=1,
        flags=re.MULTILINE,
    )


def _escape_sexpr_value(s: str) -> str:
    """Escape special characters for safe embedding in S-expression strings.

    Uses KiCad's doubled-quote convention: literal quotes become "".
    """
    return s.replace('"', '""')


def _inject_reference(sexp: str, reference: str) -> str:
    """Replace the Reference property value in the footprint S-expression."""
    safe = _escape_sexpr_value(reference)
    return re.sub(
        r'\(property "Reference" "[^"]*"',
        f'(property "Reference" "{safe}"',
        sexp,
        count=1,
    )


def _inject_value(sexp: str, value: str) -> str:
    """Replace the Value property value in the footprint S-expression."""
    safe = _escape_sexpr_value(value)
    return re.sub(
        r'\(property "Value" "[^"]*"',
        f'(property "Value" "{safe}"',
        sexp,
        count=1,
    )


def _inject_pad_net(sexp: str, pad_number: str, net_name: str) -> Optional[str]:
    """Inject or replace the (net ...) in a specific pad of the footprint.

    Finds the pad by number and injects/replaces its net assignment.
    Returns the modified sexp, or None if the pad wasn't found.
    """

    # Find pad blocks by number - pads look like (pad "N" ...  )
    # We need to find the specific pad and inject (net "name") before its closing paren
    # Pad format: (pad "NUMBER" TYPE SHAPE (at X Y) (size W H) ... (net "NAME") ...)

    # Strategy: find all pad blocks, match by number, inject net
    # This is tricky because pads are nested. Let's use a simpler approach:
    # Find (pad "NUMBER" ... and then find the matching close paren
    pattern = re.compile(r'\(pad "' + re.escape(pad_number) + r'"')

    for match in pattern.finditer(sexp):
        pad_start = match.start()
        pad_end = _find_matching_close(sexp, pad_start)
        if pad_end is None:
            continue

        pad_block = sexp[pad_start:pad_end + 1]

        # Check if pad already has a net assignment
        safe_net = _escape_sexpr_value(net_name)
        if '(net ' in pad_block:
            # Replace existing net
            new_pad = re.sub(
                r'\(net "[^"]*"\)',
                f'(net "{safe_net}")',
                pad_block,
                count=1,
            )
        else:
            # Insert net before the closing paren
            # Strip trailing whitespace, remove closing ), then add net + closing
            trimmed = pad_block.rstrip()
            new_pad = trimmed[:-1] + f'\n\t\t(net "{safe_net}")\n\t)'

        return sexp[:pad_start] + new_pad + sexp[pad_end + 1:]

    return None


def _extract_pad_numbers(sexp: str) -> list[str]:
    """Extract all pad numbers from a footprint S-expression."""
    return re.findall(r'\(pad "([^"]+)"', sexp)


def _extract_field(block: str, pattern: str, desc: str = "") -> Optional[str]:
    """Extract a single captured group from a regex match in a block."""
    match = re.search(pattern, block, re.MULTILINE)
    return match.group(1) if match else None


def _extract_raw_line(block: str, pattern: str) -> Optional[str]:
    """Extract a full matching line from a block."""
    match = re.search(pattern + r'[^\n]*', block, re.MULTILINE)
    return match.group(0) if match else None


def _dedent_one_tab(text: Optional[str]) -> Optional[str]:
    """Strip one leading tab from each line in text.

    Used when extracting PCB-embedded fields from the old footprint block
    (which are at 2-tab level) for re-injection into the library footprint
    (at 1-tab level before embedding adds one tab back).
    """
    if text is None:
        return None
    return "\n".join(
        line[1:] if line.startswith("\t") else line
        for line in text.split("\n")
    )


def _extract_raw_block(block: str, start_pattern: str) -> Optional[str]:
    """Extract a balanced S-expression block starting with the given pattern."""
    match = re.search(start_pattern, block, re.MULTILINE)
    if not match:
        return None
    start = match.start()
    end = _find_matching_close(block, start + 1)
    if end is None:
        return None
    return block[start:end + 1]


def _insert_after_field(sexp: str, field_pattern: str, insertion: str) -> str:
    """Insert text after the line matching field_pattern."""
    match = re.search(field_pattern, sexp, re.MULTILINE)
    if match:
        pos = match.end()
        return sexp[:pos] + insertion + sexp[pos:]
    return sexp


def _insert_before_attr(sexp: str, line_to_insert: str) -> str:
    """Insert a line before the (attr ...) line in the footprint."""
    attr_match = re.search(r'^\t\(attr ', sexp, re.MULTILINE)
    if attr_match:
        pos = attr_match.start()
        return sexp[:pos] + line_to_insert + '\n' + sexp[pos:]
    # Fallback: insert before (pad ...) blocks
    pad_match = re.search(r'^\t\(pad ', sexp, re.MULTILINE)
    if pad_match:
        pos = pad_match.start()
        return sexp[:pos] + line_to_insert + '\n' + sexp[pos:]
    return sexp
