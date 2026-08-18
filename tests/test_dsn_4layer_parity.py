"""4-layer DSN round-trip parity (volta-fnz).

The stackup-based via padstacks (THT/blind/buried) were implemented in the
Phase 99 R-4 work with inline fixtures; this test closes the loop on a
REAL board (backplane.kicad_pcb, F/In1/In2/B.Cu): the generated DSN must
parse back as a well-formed s-expression whose structure matches the
board's stackup — declared layers, padstack layer-spans, per-footprint
images — proving the DSN a router receives faithfully represents a
4-layer board.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sexpdata

BACKPLANE = Path("tests/fixtures/backplane/backplane.kicad_pcb")


def _generate() -> str:
    from volta.routing.dsn_generator import generate_dsn

    return generate_dsn(BACKPLANE.read_text(), BACKPLANE)


def _parse(dsn: str):
    # The Specctra header declares the string-quote character
    # self-referentially ((string_quote ")) — standard DSN that plain
    # s-expression parsers cannot know (KiCad emits the same). Strip that
    # one declaration line for structural parsing; every other token is
    # plain s-expr.
    body = "\n".join(
        line for line in dsn.splitlines() if "(string_quote" not in line
    )
    return sexpdata.loads(body)


def _find(tree, name: str) -> list:
    """All sub-lists whose head symbol equals `name`."""
    out = []
    if isinstance(tree, list):
        if tree and _sym(tree[0]) == name:
            out.append(tree)
        for item in tree:
            out.extend(_find(item, name))
    return out


def _sym(item) -> str:
    # sexpdata.Symbol subclasses String: str() yields the token text.
    return str(item)


_TREE_CACHE: list | None = None


def _tree() -> list:
    global _TREE_CACHE
    if _TREE_CACHE is None:
        _TREE_CACHE = _parse(_generate())
    return _TREE_CACHE


class TestFourLayerParity:

    def test_dsn_parses_as_well_formed_sexpr(self):
        assert isinstance(_tree(), list) and len(_tree()) > 0

    def test_all_four_copper_layers_declared(self):
        structure = _find(_tree(), "structure")
        assert structure, "DSN must carry a (structure ...) section"
        declared = {
            _sym(l[1])
            for l in _find(structure[0], "layer")
        }
        for layer in ("F.Cu", "In1.Cu", "In2.Cu", "B.Cu"):
            assert layer in declared, f"{layer} must be declared for routing"

    def test_tht_via_spans_all_copper_layers(self):
        padstacks = {
            _sym(p[1]): p for p in _find(_tree(), "padstack")
        }
        assert "Via[0-1]" in padstacks
        shape_layers = {
            _sym(s[1][1]) for s in _find(padstacks["Via[0-1]"], "shape")
        }
        assert shape_layers == {"F.Cu", "In1.Cu", "In2.Cu", "B.Cu"}

    def test_blind_via_spans_outer_and_first_inner(self):
        padstacks = {
            _sym(p[1]): p for p in _find(_tree(), "padstack")
        }
        assert "Via[0-In1]" in padstacks
        shape_layers = {
            _sym(s[1][1]) for s in _find(padstacks["Via[0-In1]"], "shape")
        }
        assert shape_layers == {"F.Cu", "In1.Cu"}

    def test_buried_via_spans_first_two_inners(self):
        padstacks = {
            _sym(p[1]): p for p in _find(_tree(), "padstack")
        }
        assert "Via[In1-In2]" in padstacks
        shape_layers = {
            _sym(s[1][1]) for s in _find(padstacks["Via[In1-In2]"], "shape")
        }
        assert shape_layers == {"In1.Cu", "In2.Cu"}

    def test_images_exist_for_board_footprints(self):
        images = _find(_tree(), "image")
        assert len(images) > 0, "library must carry footprint images"
        # Substantive images carry pins; outline-only images also valid.
        with_content = [
            img for img in images if _find(img, "pin") or _find(img, "outline")
        ]
        assert len(with_content) > 0, "at least one image must have pins/outlines"

    def test_network_section_carries_board_nets(self):
        networks = _find(_tree(), "net")
        names = {_sym(n[1]) for n in networks}
        assert "GND" in names, "board GND net must be routable"

    def test_regeneration_is_deterministic(self):
        # Parity means the generation is stable: same board -> same DSN.
        a = _generate()
        b = _generate()
        assert a == b
