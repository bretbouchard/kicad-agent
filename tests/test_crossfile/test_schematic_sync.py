"""Tests for schematic-to-PCB synchronization logic."""
import pytest
from volta.crossfile.schematic_sync import (
    NetlistComponent, NetlistNet, SyncResult,
    _add_net_to_content, _extract_pcb_footprint_refs,
    _extract_pcb_net_names, _find_footprint_block,
    _find_matching_close, _find_pad_in_footprint,
    _inject_pad_net, _remove_footprint_block,
    _update_footprint_lib_id, parse_netlist,
)

PCB_RAW = bytes.fromhex("286b696361645f706362202876657273696f6e20323032343036313829202867656e657261746f72206b696361642d636c69290a0a092867656e6572616c2028746869636b6e65737320312e3629290a092870617065722022413422290a0a09286e65745f73656374696f6e0a0909286e65742030202222290a0909286e657420312022474e4422290a0909286e6574203220222b33563322290a09290a0a0928666f6f747072696e7420225265736973746f725f534d443a525f303630335f313630384d6574726963220a0909286c617965722022462e437522290a09092875756964202261616161616161612d626262622d636363632d646464642d65656565656565656565656522290a0909286174203130203230290a09092870726f706572747920225265666572656e63652220225231220a0909092861742030202d312e32290a090909286c617965722022462e53696c6b5322290a09090928656666656374732028666f6e74202873697a6520312031292028746869636b6e65737320302e3135292929290a09092870726f7065727479202256616c756522202231306b220a090909286174203020312e32290a090909286c617965722022462e46616222290a09090928656666656374732028666f6e74202873697a6520312031292028746869636b6e65737320302e3135292929290a0909287061642022312220736d6420726f756e647265637420286174202d302e3438203029202873697a6520302e353620302e36322920286c61796572732022462e4375222022462e4d61736b222022462e50617374652229290a0909287061642022322220736d6420726f756e64726563742028617420302e3438203029202873697a6520302e353620302e36322920286c61796572732022462e4375222022462e4d61736b222022462e50617374652229290a09290a0a0928666f6f747072696e742022436170616369746f725f534d443a435f303630335f313630384d6574726963220a0909286c617965722022462e437522290a09092875756964202231313131313131312d323232322d333333332d343434342d35353535353535353535353522290a0909286174203330203430290a09092870726f706572747920225265666572656e63652220224331220a0909092861742030202d312e32290a090909286c617965722022462e53696c6b5322290a09090928656666656374732028666f6e74202873697a6520312031292028746869636b6e65737320302e3135292929290a09092870726f7065727479202256616c75652220223130306e46220a090909286174203020312e32290a090909286c617965722022462e46616222290a09090928656666656374732028666f6e74202873697a6520312031292028746869636b6e65737320302e3135292929290a0909287061642022312220736d6420726f756e647265637420286174202d302e3438203029202873697a6520302e353620302e36322920286c61796572732022462e4375222022462e4d61736b222022462e50617374652229290a0909287061642022322220736d6420726f756e64726563742028617420302e3438203029202873697a6520302e353620302e36322920286c61796572732022462e4375222022462e4d61736b222022462e50617374652229290a09290a0a290a").decode("utf-8")

NETLIST_SEXPR = """(export
\t(version "E")
\t(design
\t\t(source "/project/schematic.kicad_sch")
\t\t(date "2026-06-05")
\t\t(tool "Eeschema 10.0.1")
\t)
\t(components
\t\t(comp
\t\t\t(ref "R1")
\t\t\t(value "10k")
\t\t\t(footprint "Resistor_SMD:R_0603_1608Metric")
\t\t\t(libsource (lib "Device") (part "R"))
\t\t)
\t\t(comp
\t\t\t(ref "C1")
\t\t\t(value "100nF")
\t\t\t(footprint "Capacitor_SMD:C_0603_1608Metric")
\t\t\t(libsource (lib "Device") (part "C"))
\t\t)
\t\t(comp
\t\t\t(ref "U1")
\t\t\t(value "RP2350B")
\t\t\t(footprint "Analog-Ecosystem:QFN-80-1EP_7x7mm_P0.4mm_EP5.6x5.6mm")
\t\t\t(libsource (lib "MCU_RaspberryPi") (part "RP2350"))
\t\t)
\t)
\t(nets
\t\t(net
\t\t\t(code "0")
\t\t\t(name "")
\t\t\t(node (ref "R1") (pin "1") (pintype "passive"))
\t\t)
\t\t(net
\t\t\t(code "1")
\t\t\t(name "GND")
\t\t\t(node (ref "R1") (pin "2") (pintype "passive"))
\t\t\t(node (ref "C1") (pin "2") (pintype "passive"))
\t\t)
\t\t(net
\t\t\t(code "2")
\t\t\t(name "+3V3")
\t\t\t(node (ref "C1") (pin "1") (pintype "passive"))
\t\t\t(node (ref "U1") (pin "3") (pintype "input"))
\t\t)
\t\t(net
\t\t\t(code "3")
\t\t\t(name "SDA")
\t\t\t(node (ref "U1") (pin "1") (pintype "bidirectional"))
\t\t)
\t)
)"""


class TestParseNetlist:
    def test_parse_components(self):
        components, nets = parse_netlist(NETLIST_SEXPR)
        assert len(components) == 3
        assert components[0].ref == "R1"

    def test_parse_nets(self):
        components, nets = parse_netlist(NETLIST_SEXPR)
        gnd = next(n for n in nets if n.name == "GND")
        assert ("R1", "2") in gnd.nodes


class TestFindFootprintBlock:
    def test_find_existing(self):
        start, end = _find_footprint_block(PCB_RAW, "R1")
        assert start is not None
        assert end is not None
        block = PCB_RAW[start:end]
        assert "R1" in block

    def test_find_nonexistent(self):
        start, end = _find_footprint_block(PCB_RAW, "X99")
        assert start is None


class TestFindPad:
    def test_find_pad(self):
        start, end = _find_footprint_block(PCB_RAW, "R1")
        pad_start, _ = _find_pad_in_footprint(PCB_RAW[start:end], "1")
        assert pad_start is not None

    def test_missing_pad(self):
        start, end = _find_footprint_block(PCB_RAW, "R1")
        pad_start, _ = _find_pad_in_footprint(PCB_RAW[start:end], "99")
        assert pad_start is None


class TestInjectPadNet:
    def test_inject(self):
        start, end = _find_footprint_block(PCB_RAW, "R1")
        new_block = _inject_pad_net(PCB_RAW[start:end], "1", "GND")
        assert '(net "GND")' in new_block

    def test_update(self):
        start, end = _find_footprint_block(PCB_RAW, "R1")
        fp = PCB_RAW[start:end]
        updated = _inject_pad_net(_inject_pad_net(fp, "1", "+5V"), "1", "GND")
        assert '(net "GND")' in updated


class TestExtractPcbFootprintRefs:
    def test_extracts(self):
        refs = _extract_pcb_footprint_refs(PCB_RAW)
        assert "R1" in refs
        assert "C1" in refs


class TestExtractPcbNetNames:
    def test_extracts(self):
        nets = _extract_pcb_net_names(PCB_RAW)
        assert "GND" in nets


class TestUpdateFootprintLibId:
    def test_update(self):
        result = _update_footprint_lib_id(PCB_RAW, "R1", "NewLib:R_New")
        assert "NewLib:R_New" in result


class TestRemoveFootprintBlock:
    def test_remove(self):
        result = _remove_footprint_block(PCB_RAW, "R1")
        assert "R1" not in result
        assert "C1" in result


class TestAddNetToContent:
    def test_add(self):
        result = _add_net_to_content(PCB_RAW, 5, "SDA")
        assert '(net 5 "SDA")' in result


class TestSyncResult:
    def test_no_changes(self):
        assert not SyncResult().has_changes

    def test_has_changes(self):
        assert SyncResult(updated_nets=["GND"]).has_changes
