"""Tests for PcbRawWriter zone lifecycle methods.

TDD RED phase: These tests define the expected behavior for:
- find_zone_block() -- locate zone by UUID
- find_zone_block_by_index() -- locate zone by index
- modify_zone_field() -- change zone fields (net, layer, clearance, priority, min_width)
- modify_zone_polygon() -- replace zone polygon outline
- remove_zone_block() -- delete zone from content
"""

import pytest


# ---------------------------------------------------------------------------
# Test fixtures: minimal zone S-expression content
# ---------------------------------------------------------------------------

ZONE_UUID_A = "11111111-2222-3333-4444-555555555555"
ZONE_UUID_B = "99999999-8888-7777-6666-000000000000"

PCB_WITH_TWO_ZONES = """\
(kicad_pcb
  (version 20260206)

  (zone
    (net 0 "")
    (layer "F.Cu")
    (uuid "{uuid_a}")
    (hatch edge 0.5)
    (connect_pads
      (clearance 0.5)
    )
    (min_thickness 0.25)
    (fill yes
      (thermal_gap 0.5)
      (thermal_bridge_width 0.5)
    )
    (polygon
      (pts
        (xy 10 10)
        (xy 90 10)
        (xy 90 90)
        (xy 10 90)
      )
    )
  )

  (zone
    (net 1 "GND")
    (layer "B.Cu")
    (uuid "{uuid_b}")
    (hatch edge 0.5)
    (connect_pads
      (clearance 0.8)
    )
    (min_thickness 0.3)
    (fill yes
      (thermal_gap 0.8)
      (thermal_bridge_width 0.8)
    )
    (polygon
      (pts
        (xy 0 0)
        (xy 100 0)
        (xy 100 100)
        (xy 0 100)
      )
    )
  )
)
""".format(uuid_a=ZONE_UUID_A, uuid_b=ZONE_UUID_B)

# Zone with nested parens to test depth handling
ZONE_WITH_NESTED = """\
(kicad_pcb
  (zone
    (net 0 "")
    (layer "F.Cu")
    (uuid "{uuid_a}")
    (hatch edge 0.5)
    (connect_pads
      (clearance 0.5)
    )
    (min_thickness 0.25)
    (fill yes
      (thermal_gap 0.5)
      (thermal_bridge_width 0.5)
      (island_removal_mode 1)
    )
    (polygon
      (pts
        (xy (nest1 (nest2 10)) 10)
        (xy 90 (nest3 (nest4 10)))
        (xy 90 90)
        (xy 10 90)
      )
    )
  )
)
""".format(uuid_a=ZONE_UUID_A)


# ---------------------------------------------------------------------------
# find_zone_block tests
# ---------------------------------------------------------------------------

class TestFindZoneBlock:
    """Test PcbRawWriter.find_zone_block() for UUID-based zone lookup."""

    def test_find_zone_by_uuid_returns_offsets(self):
        """find_zone_block() returns (start, end) for a known UUID."""
        from kicad_agent.ops.pcb_raw_writer import PcbRawWriter
        start, end = PcbRawWriter.find_zone_block(PCB_WITH_TWO_ZONES, ZONE_UUID_A)
        assert start is not None
        assert end is not None
        assert start < end
        # The block should contain the UUID
        block = PCB_WITH_TWO_ZONES[start:end]
        assert ZONE_UUID_A in block

    def test_find_zone_by_uuid_returns_none_when_not_found(self):
        """find_zone_block() returns (None, None) for unknown UUID."""
        from kicad_agent.ops.pcb_raw_writer import PcbRawWriter
        start, end = PcbRawWriter.find_zone_block(PCB_WITH_TWO_ZONES, "nonexistent-uuid")
        assert start is None
        assert end is None

    def test_find_zone_locates_second_zone(self):
        """find_zone_block() finds the second zone by its UUID."""
        from kicad_agent.ops.pcb_raw_writer import PcbRawWriter
        start, end = PcbRawWriter.find_zone_block(PCB_WITH_TWO_ZONES, ZONE_UUID_B)
        assert start is not None
        assert end is not None
        block = PCB_WITH_TWO_ZONES[start:end]
        assert ZONE_UUID_B in block
        assert '"GND"' in block

    def test_find_zone_handles_nested_parens(self):
        """find_zone_block() correctly handles deeply nested parens in zone."""
        from kicad_agent.ops.pcb_raw_writer import PcbRawWriter
        start, end = PcbRawWriter.find_zone_block(ZONE_WITH_NESTED, ZONE_UUID_A)
        assert start is not None
        assert end is not None
        block = ZONE_WITH_NESTED[start:end]
        assert "(zone" in block
        assert ZONE_UUID_A in block


# ---------------------------------------------------------------------------
# find_zone_block_by_index tests
# ---------------------------------------------------------------------------

class TestFindZoneBlockByIndex:
    """Test PcbRawWriter.find_zone_block_by_index() for index-based lookup."""

    def test_find_zone_by_index_zero(self):
        """find_zone_block_by_index() returns first zone at index 0."""
        from kicad_agent.ops.pcb_raw_writer import PcbRawWriter
        start, end = PcbRawWriter.find_zone_block_by_index(PCB_WITH_TWO_ZONES, 0)
        assert start is not None
        assert end is not None
        block = PCB_WITH_TWO_ZONES[start:end]
        assert ZONE_UUID_A in block

    def test_find_zone_by_index_one(self):
        """find_zone_block_by_index() returns second zone at index 1."""
        from kicad_agent.ops.pcb_raw_writer import PcbRawWriter
        start, end = PcbRawWriter.find_zone_block_by_index(PCB_WITH_TWO_ZONES, 1)
        assert start is not None
        assert end is not None
        block = PCB_WITH_TWO_ZONES[start:end]
        assert ZONE_UUID_B in block

    def test_find_zone_by_index_out_of_range(self):
        """find_zone_block_by_index() returns (None, None) for out-of-range index."""
        from kicad_agent.ops.pcb_raw_writer import PcbRawWriter
        start, end = PcbRawWriter.find_zone_block_by_index(PCB_WITH_TWO_ZONES, 99)
        assert start is None
        assert end is None


# ---------------------------------------------------------------------------
# modify_zone_field tests
# ---------------------------------------------------------------------------

class TestModifyZoneField:
    """Test PcbRawWriter.modify_zone_field() for zone field changes."""

    def test_modify_zone_net_name(self):
        """modify_zone_field() changes net name in a zone block."""
        from kicad_agent.ops.pcb_raw_writer import PcbRawWriter
        result = PcbRawWriter.modify_zone_field(
            PCB_WITH_TWO_ZONES, ZONE_UUID_B, "net_name", "VCC"
        )
        assert 'net 1 "VCC"' in result
        assert 'net 1 "GND"' not in result
        # First zone should be unchanged
        assert ZONE_UUID_A in result

    def test_modify_zone_layer(self):
        """modify_zone_field() changes layer in a zone block."""
        from kicad_agent.ops.pcb_raw_writer import PcbRawWriter
        result = PcbRawWriter.modify_zone_field(
            PCB_WITH_TWO_ZONES, ZONE_UUID_A, "layer", "B.Cu"
        )
        assert '(layer "B.Cu")' in result
        # The zone block should contain the modified layer
        start, end = PcbRawWriter.find_zone_block(result, ZONE_UUID_A)
        assert start is not None
        block = result[start:end]
        assert '(layer "B.Cu")' in block

    def test_modify_zone_clearance(self):
        """modify_zone_field() changes clearance in connect_pads."""
        from kicad_agent.ops.pcb_raw_writer import PcbRawWriter
        result = PcbRawWriter.modify_zone_field(
            PCB_WITH_TWO_ZONES, ZONE_UUID_B, "clearance", 1.5
        )
        start, end = PcbRawWriter.find_zone_block(result, ZONE_UUID_B)
        block = result[start:end]
        assert "(clearance 1.5)" in block

    def test_modify_zone_priority(self):
        """modify_zone_field() changes priority in a zone block."""
        from kicad_agent.ops.pcb_raw_writer import PcbRawWriter
        result = PcbRawWriter.modify_zone_field(
            PCB_WITH_TWO_ZONES, ZONE_UUID_A, "priority", 5
        )
        start, end = PcbRawWriter.find_zone_block(result, ZONE_UUID_A)
        block = result[start:end]
        assert "(priority 5)" in block

    def test_modify_zone_min_width(self):
        """modify_zone_field() changes min_thickness in a zone block."""
        from kicad_agent.ops.pcb_raw_writer import PcbRawWriter
        result = PcbRawWriter.modify_zone_field(
            PCB_WITH_TWO_ZONES, ZONE_UUID_A, "min_width", 0.4
        )
        start, end = PcbRawWriter.find_zone_block(result, ZONE_UUID_A)
        block = result[start:end]
        assert "(min_thickness 0.4)" in block

    def test_modify_zone_returns_original_when_not_found(self):
        """modify_zone_field() returns original content when UUID not found."""
        from kicad_agent.ops.pcb_raw_writer import PcbRawWriter
        result = PcbRawWriter.modify_zone_field(
            PCB_WITH_TWO_ZONES, "nonexistent-uuid", "layer", "B.Cu"
        )
        assert result == PCB_WITH_TWO_ZONES


# ---------------------------------------------------------------------------
# modify_zone_polygon tests
# ---------------------------------------------------------------------------

class TestModifyZonePolygon:
    """Test PcbRawWriter.modify_zone_polygon() for polygon replacement."""

    def test_modify_zone_polygon_replaces_points(self):
        """modify_zone_polygon() replaces the polygon outline points."""
        from kicad_agent.ops.pcb_raw_writer import PcbRawWriter
        new_polygon = [(1.0, 2.0), (3.0, 4.0), (5.0, 6.0)]
        result = PcbRawWriter.modify_zone_polygon(
            PCB_WITH_TWO_ZONES, ZONE_UUID_A, new_polygon
        )
        start, end = PcbRawWriter.find_zone_block(result, ZONE_UUID_A)
        block = result[start:end]
        assert "(xy 1 2)" in block
        assert "(xy 3 4)" in block
        assert "(xy 5 6)" in block
        # Old points should be gone
        assert "(xy 10 10)" not in block

    def test_modify_zone_polygon_returns_original_when_not_found(self):
        """modify_zone_polygon() returns original content when UUID not found."""
        from kicad_agent.ops.pcb_raw_writer import PcbRawWriter
        result = PcbRawWriter.modify_zone_polygon(
            PCB_WITH_TWO_ZONES, "nonexistent-uuid", [(1, 2), (3, 4), (5, 6)]
        )
        assert result == PCB_WITH_TWO_ZONES


# ---------------------------------------------------------------------------
# remove_zone_block tests
# ---------------------------------------------------------------------------

class TestRemoveZoneBlock:
    """Test PcbRawWriter.remove_zone_block() for zone deletion."""

    def test_remove_zone_by_uuid(self):
        """remove_zone_block() removes the zone block from content."""
        from kicad_agent.ops.pcb_raw_writer import PcbRawWriter
        result = PcbRawWriter.remove_zone_block(PCB_WITH_TWO_ZONES, ZONE_UUID_A)
        assert ZONE_UUID_A not in result
        assert ZONE_UUID_B in result
        # Count zones in result
        assert result.count("(zone") == 1

    def test_remove_zone_returns_original_when_not_found(self):
        """remove_zone_block() returns original content when UUID not found."""
        from kicad_agent.ops.pcb_raw_writer import PcbRawWriter
        result = PcbRawWriter.remove_zone_block(PCB_WITH_TWO_ZONES, "nonexistent-uuid")
        assert result == PCB_WITH_TWO_ZONES

    def test_remove_all_zones_leaves_none(self):
        """remove_zone_block() can remove all zones sequentially."""
        from kicad_agent.ops.pcb_raw_writer import PcbRawWriter
        result = PcbRawWriter.remove_zone_block(PCB_WITH_TWO_ZONES, ZONE_UUID_A)
        result = PcbRawWriter.remove_zone_block(result, ZONE_UUID_B)
        assert "(zone" not in result
