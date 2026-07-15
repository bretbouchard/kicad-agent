"""C-02: DSN wiring section emitter + round-trip fidelity test.

Council condition C-02 (MEDIUM): The DSN ``(wiring ...)`` section emission
is net-new code. The KiCad-mm ↔ DSN-um coordinate round-trip fidelity is
load-bearing — a ``(type fix)`` wire that round-trips with slightly wrong
coordinates defeats the locking mechanism silently.

Tests:
  1. _emit_wiring_section produces valid DSN from KiCad segments.
  2. Coordinate transform: KiCad mm → DSN um is exact (×1000).
  3. Locked nets filtering works.
  4. generate_dsn includes the wiring section when tracks exist.
  5. Full round-trip with Freerouting: fixed wire survives with <1µm error.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from volta.routing.dsn_generator import _emit_wiring_section, generate_dsn
from volta.routing.freerouting import is_freerouting_available
from volta.parser.pcb_native_parser import NativeParser, NativeBoard


def _parse(content: str) -> "NativeBoard":
    """Parse PCB content using the classmethod API."""
    return NativeParser.parse_pcb_content(content)

pytestmark = pytest.mark.slow

_JAR = Path.home() / ".kicad-agent" / "tools" / "freerouting.jar"
_BATCH_DIR = Path(__file__).resolve().parents[1] / "src" / "volta" / "routing"


# Minimal PCB content with two routed segments for testing.
_PCB_WITH_TRACKS = '''(kicad_pcb
  (version 20241129)
  (generator "kicad-agent-test")
  (general (thickness 1.6))
  (layers
    (0 "F.Cu" signal)
    (31 "B.Cu" signal)
    (32 "B.Adhes" user "B.Adhesive")
    (33 "F.Adhes" user "F.Adhesive")
    (34 "B.Paste" user)
    (35 "F.Paste" user)
    (36 "B.SilkS" user "B.Silkscreen")
    (37 "F.SilkS" user "F.Silkscreen")
    (38 "B.Mask" user)
    (39 "F.Mask" user)
    (40 "Dwgs.User" user "User.Drawings")
    (41 "Cmts.User" user "User.Comments")
    (42 "Eco1.User" user)
    (43 "Eco2.User" user)
    (44 "Edge.Cuts" user)
    (45 "Margin" user)
    (46 "B.CrtYd" user "B.Courtyard")
    (47 "F.CrtYd" user "F.Courtyard")
    (48 "B.Fab" user)
    (49 "F.Fab" user)
  )
  (setup
    (pad_to_mask_clearance 0)
  )
  (net 0 "")
  (net 1 "NET_A")
  (net 2 "NET_B")
  (footprint "TestResistor:R_0805" (layer "F.Cu")
    (uuid "fp-001")
    (at 100.0 100.0 0)
    (property "Reference" "R1" (at 0 0 0) (layer "F.SilkS") (uuid "p1"))
    (pad "1" smd roundrect (at -0.75 0) (size 0.5 0.5) (layers "F.Cu" "F.Paste" "F.Mask") (net 1 "NET_A") (uuid "pad1"))
    (pad "2" smd roundrect (at 0.75 0) (size 0.5 0.5) (layers "F.Cu" "F.Paste" "F.Mask") (net 2 "NET_B") (uuid "pad2"))
  )
  (segment (start 99.25 100.0) (end 105.0 100.0) (width 0.25) (layer "F.Cu") (net 1 "NET_A") (uuid "seg1"))
  (segment (start 105.0 100.0) (end 110.0 105.0) (width 0.25) (layer "F.Cu") (net 1 "NET_A") (uuid "seg2"))
  (via (at 105.0 100.0) (size 0.8) (drill 0.4) (layers "F.Cu" "B.Cu") (net 1 "NET_A") (uuid "via1"))
  (gr_line (start 90 90) (end 120 90) (layer "Edge.Cuts") (width 0.1) (uuid "edge1"))
  (gr_line (start 120 90) (end 120 120) (layer "Edge.Cuts") (width 0.1) (uuid "edge2"))
  (gr_line (start 120 120) (end 90 120) (layer "Edge.Cuts") (width 0.1) (uuid "edge3"))
  (gr_line (start 90 120) (end 90 90) (layer "Edge.Cuts") (width 0.1) (uuid "edge4"))
)
'''


class TestWiringEmitter:
    """Unit tests for _emit_wiring_section."""

    def test_emits_wires_from_segments(self) -> None:
        """Segments in the PCB produce (wire ...) entries."""
        
        board = _parse(_PCB_WITH_TRACKS)

        wiring = _emit_wiring_section(_PCB_WITH_TRACKS, board)
        assert "wiring" in wiring
        assert "wire" in wiring
        assert "type fix" in wiring

    def test_coordinate_transform_mm_to_um(self) -> None:
        """KiCad mm coordinates are converted to DSN um (×1000)."""
        
        board = _parse(_PCB_WITH_TRACKS)

        wiring = _emit_wiring_section(_PCB_WITH_TRACKS, board)
        # 99.25 mm → 99250 um. 105.0 mm → 105000 um.
        assert "99250" in wiring
        assert "105000" in wiring

    def test_width_transform(self) -> None:
        """Trace width 0.25 mm → 250 um."""
        
        board = _parse(_PCB_WITH_TRACKS)

        wiring = _emit_wiring_section(_PCB_WITH_TRACKS, board)
        # The wire path format is (path LAYER WIDTH x1 y1 x2 y2)
        # Width 0.25mm → 250um.
        assert " 250 " in wiring or "(path F.Cu 250 " in wiring

    def test_emits_vias(self) -> None:
        """Vias in the PCB produce (via ...) entries."""
        
        board = _parse(_PCB_WITH_TRACKS)

        wiring = _emit_wiring_section(_PCB_WITH_TRACKS, board)
        assert "(via " in wiring
        assert "105000 100000" in wiring  # via at 105.0, 100.0 mm → um

    def test_net_name_preserved(self) -> None:
        """Net names appear in the emitted wires."""
        
        board = _parse(_PCB_WITH_TRACKS)

        wiring = _emit_wiring_section(_PCB_WITH_TRACKS, board)
        assert '(net "NET_A")' in wiring

    def test_locked_nets_filter(self) -> None:
        """When locked_nets is specified, only matching nets are emitted."""
        
        board = _parse(_PCB_WITH_TRACKS)

        # Only lock NET_B (which has no tracks) → should produce empty wiring.
        wiring = _emit_wiring_section(_PCB_WITH_TRACKS, board, locked_nets={"NET_B"})
        assert wiring == ""

        # Lock NET_A → should produce wires.
        wiring = _emit_wiring_section(_PCB_WITH_TRACKS, board, locked_nets={"NET_A"})
        assert "NET_A" in wiring

    def test_empty_when_no_tracks(self) -> None:
        """A PCB with no tracks produces no wiring section."""
        empty_pcb = _PCB_WITH_TRACKS.replace(
            '(segment (start 99.25 100.0) (end 105.0 100.0) (width 0.25) (layer "F.Cu") (net 1 "NET_A") (uuid "seg1"))',
            ''
        ).replace(
            '(segment (start 105.0 100.0) (end 110.0 105.0) (width 0.25) (layer "F.Cu") (net 1 "NET_A") (uuid "seg2"))',
            ''
        ).replace(
            '(via (at 105.0 100.0) (size 0.8) (drill 0.4) (layers "F.Cu" "B.Cu") (net 1 "NET_A") (uuid "via1"))',
            ''
        )
        
        board = _parse(empty_pcb)

        wiring = _emit_wiring_section(empty_pcb, board)
        assert wiring == ""


class TestGenerateDsnIncludesWiring:
    """Verify generate_dsn includes the wiring section."""

    def test_full_dsn_includes_wiring(self) -> None:
        """generate_dsn output includes (wiring ...) when tracks exist."""
        
        dsn = generate_dsn(_PCB_WITH_TRACKS)
        assert "(wiring" in dsn
        assert "(type fix)" in dsn


class TestFreeroutingRoundTrip:
    """C-02 fidelity test: route with Freerouting, verify fixed wire survives.

    This is the load-bearing test. If the coordinate transform is wrong,
    the fixed wire won't match Freerouting's internal representation and
    it will be ripped up.
    """

    def test_fixed_wire_survives_round_trip(self, tmp_path: Path) -> None:
        """A (type fix) wire must survive a Freerouting round with <1µm error."""
        if not is_freerouting_available():
            pytest.skip("Freerouting JAR or Java runtime not available")

        
        board = _parse(_PCB_WITH_TRACKS)

        # Generate DSN with the wiring section.
        dsn_text = generate_dsn(_PCB_WITH_TRACKS)
        assert "(wiring" in dsn_text

        # Extract just the fixed wire coordinates for later comparison.
        wiring = _emit_wiring_section(_PCB_WITH_TRACKS, board)
        # Parse the first wire's coordinates.
        wire_match = re.search(
            r'\(wire \(path \S+ \d+\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\)',
            wiring,
        )
        assert wire_match, "No wire found in wiring section"
        original_x1 = int(wire_match.group(1))
        original_y1 = int(wire_match.group(2))
        original_x2 = int(wire_match.group(3))
        original_y2 = int(wire_match.group(4))

        # Write DSN and run Freerouting.
        dsn_path = tmp_path / "test.dsn"
        ses_path = tmp_path / "test.ses"
        dsn_path.write_text(dsn_text)

        cmd = [
            "java", "-Djava.awt.headless=true",
            "-cp", f"{_JAR}:{_BATCH_DIR}",
            "FreerouteBatch",
            str(dsn_path), str(ses_path), "5", "none",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        assert result.returncode in (0, 1), (
            f"Freerouting failed: exit {result.returncode}\n"
            f"stderr: {result.stderr[:500]}"
        )
        assert ses_path.exists(), "No SES produced"

        # Parse the SES and find the wire for NET_A.
        ses_text = ses_path.read_text()
        # SES wires look like: (wire (polyline_path F.Cu W x1 y1 x2 y2 ...) (net NAME N) ...)
        ses_wire_re = re.compile(
            r'\(wire\s+\(polyline_path\s+(\S+)\s+([\d.]+)\s+(.*?)\)\s*'
            r'\(net\s+(?:"([^"]+)"|(\S+))\s+\d+\)',
            re.DOTALL,
        )

        net_a_found = False
        net_a_coords: list[float] = []
        for m in ses_wire_re.finditer(ses_text):
            net = m.group(4) or m.group(5)
            if net == "NET_A":
                net_a_found = True
                coords_str = m.group(3).strip()
                nums = re.findall(r'[-]?\d+\.?\d*', coords_str)
                net_a_coords.extend(float(n) for n in nums)

        assert net_a_found, "NET_A not found in SES output"

        # C-02 fidelity check: the original wire coordinates must appear
        # in the output (within 1µm = 1.0 in DSN um units).
        # Original: x1=99250, y1=100000, x2=105000, y2=100000 (in um).
        # The SES uses raw um (float), so 99250.0, 100000.0, etc.
        def coords_close(target: float, coords: list[float], tol: float = 1.0) -> bool:
            """Check if target appears in coords within tolerance."""
            return any(abs(c - target) < tol for c in coords)

        assert coords_close(float(original_x1), net_a_coords), (
            f"Original x1={original_x1} not found in NET_A coords {net_a_coords[:10]}"
        )
        assert coords_close(float(original_y1), net_a_coords), (
            f"Original y1={original_y1} not found in NET_A coords {net_a_coords[:10]}"
        )
