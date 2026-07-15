"""Parser performance profiling and optimization tests (TDD RED phase).

Tests for:
- Symbol index optimization (O(1) lookups instead of O(n) tree walks)
- Large file parsing performance (1MB, 5MB targets)
- Depth pre-scan enforcement
- Stress testing with 1000+ footprints
- Fuzz resilience on random valid S-expression content
- Memory/cache management (pre_download_adapter, get_cache_info)
"""

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from volta.parser.pcb_native_parser import (
    NativeParser,
    _build_symbol_index,
    _find_all_symbols,
    _find_symbol,
    _pre_scan_depth,
)


# ---------------------------------------------------------------------------
# Synthetic PCB content generator
# ---------------------------------------------------------------------------


def _generate_footprint_block(
    fp_id: int,
    pad_count: int = 4,
    include_graphics: bool = True,
) -> str:
    """Generate a single (footprint ...) S-expression block."""
    pads = ""
    for p in range(pad_count):
        pads += f"""
      (pad {p} smd rect (at {p * 2.54:.2f} 0) (size 1.5 1.0)
        (layers "F.Cu" "F.Paste" "F.Mask")
        (net {fp_id + p} "NET{fp_id + p}"))"""
    graphics = ""
    if include_graphics:
        graphics = f"""
      (fp_line (start 0 -3) (end 10 -3) (layer "F.SilkS") (width 0.12))
      (fp_circle (center 5 0) (radius 2) (layer "F.SilkS") (width 0.12))"""
    return f"""  (footprint "Device:R{fp_id}" (layer "F.Cu")
    (at {fp_id * 5.0:.1f} {fp_id * 3.0:.1f})
    (uuid "fp-{fp_id:06d}")
    (property "Reference" "R{fp_id}")
    (property "Value" "10k"){pads}{graphics}
  )"""


def _generate_pcb_content(
    footprint_count: int = 100,
    net_count: int = 50,
    pad_count: int = 4,
) -> str:
    """Generate synthetic .kicad_pcb S-expression content.

    Produces a valid KiCad PCB structure with configurable footprint count.
    All sections are nested inside the root (kicad_pcb ...) block so
    sexpdata.loads parses a single root S-expression.
    """
    # Header (opens kicad_pcb block)
    header = '(kicad_pcb (version 20240108) (generator "volta-test")\n'

    # General section
    general = """
  (general (thickness 1.6))
"""

    # Layers
    layers = """  (layers
    (0 "F.Cu" signal)
    (31 "B.Cu" signal)
    (32 "B.Adhes" user)
    (33 "F.Adhes" user)
    (34 "B.Paste" user)
    (35 "F.Paste" user)
    (36 "B.SilkS" user)
    (37 "F.SilkS" user)
    (38 "B.Mask" user)
    (39 "F.Mask" user)
  )
"""

    # Setup
    setup = """  (setup
    (stackup
      (layer "F.Cu" (thickness 0.035) (type "copper"))
      (layer "dielectric 1" (thickness 1.51) (type "core"))
      (layer "B.Cu" (thickness 0.035) (type "copper"))
      (copper_finish "ENIG")
    )
  )
"""

    # Net declarations
    nets = '  (net 0 "")\n'
    for i in range(1, net_count + 1):
        nets += f'  (net {i} "NET{i}")\n'

    # Net class
    net_class = """  (net_class "Default" (clearance 0.2) (trace_width 0.25)
    (via_diameter 0.6) (via_drill 0.3)
    (add_net "")
"""

    for i in range(1, min(net_count, 10) + 1):
        net_class += f'    (add_net "NET{i}")\n'
    net_class += "  )\n"

    # Segments (traces)
    segments = ""
    for i in range(footprint_count):
        x1 = i * 5.0
        y1 = i * 3.0
        x2 = x1 + 3.0
        y2 = y1 + 2.0
        segments += f"""  (segment (start {x1:.2f} {y1:.2f}) (end {x2:.2f} {y2:.2f})
    (width 0.25) (layer "F.Cu") (net {i % net_count + 1}))
"""

    # Vias
    vias = ""
    for i in range(0, footprint_count, 3):
        x = i * 5.0 + 1.5
        y = i * 3.0 + 1.0
        vias += f"""  (via (at {x:.2f} {y:.2f}) (size 0.6) (drill 0.3)
    (layers "F.Cu" "B.Cu") (net {i % net_count + 1}))
"""

    # Zones (a couple)
    zones = f"""  (zone (net {1}) (net_name "NET1") (layer "F.Cu")
    (uuid "zone-ground-001")
    (priority 0)
    (clearance 0.2)
    (min_thickness 0.25)
    (filled_polygon
      (pts (xy 0 0) (xy 100 0) (xy 100 100) (xy 0 100) (xy 0 0))
    )
  )
"""

    # Footprints
    footprints = ""
    for i in range(footprint_count):
        footprints += _generate_footprint_block(i, pad_count=pad_count)

    # Graphic items
    graphics = """
  (gr_line (start -10 -10) (end 100 -10) (layer "Edge.Cuts") (width 0.1))
  (gr_line (start 100 -10) (end 100 100) (layer "Edge.Cuts") (width 0.1))
  (gr_line (start 100 100) (end -10 100) (layer "Edge.Cuts") (width 0.1))
  (gr_line (start -10 100) (end -10 -10) (layer "Edge.Cuts") (width 0.1))
"""

    return (
        header
        + general
        + layers
        + setup
        + nets
        + net_class
        + segments
        + vias
        + zones
        + graphics
        + footprints
        + ")\n"
    )


# ---------------------------------------------------------------------------
# Part A: Symbol index tests
# ---------------------------------------------------------------------------


class TestSymbolIndex:
    """Tests for _build_symbol_index optimization."""

    def test_index_maps_symbol_names_to_lists(self):
        """_build_symbol_index returns dict[str, list] with correct keys."""
        content = _generate_pcb_content(footprint_count=10)
        from volta.parser.pcb_native_parser import NativeParser as NP

        board = NP.parse_pcb_content(content)
        # Build index from the tree used internally
        import sexpdata
        tree = sexpdata.loads(content)
        index = _build_symbol_index(tree)
        assert isinstance(index, dict)
        assert "footprint" in index
        assert "net" in index
        assert "segment" in index
        assert len(index["footprint"]) == 10

    def test_index_find_symbol_equivalent(self):
        """Index lookups match _find_symbol results for first match."""
        content = _generate_pcb_content(footprint_count=5)
        import sexpdata
        tree = sexpdata.loads(content)
        index = _build_symbol_index(tree)

        root = _find_symbol(tree, "kicad_pcb")
        assert root is not None

        # _find_symbol should return same first element as index
        if "general" in index:
            indexed = index["general"][0]
            found = _find_symbol(root, "general")
            assert found == indexed

    def test_find_all_symbols_equivalent(self):
        """Index contains same elements as _find_all_symbols."""
        content = _generate_pcb_content(footprint_count=5)
        import sexpdata
        tree = sexpdata.loads(content)
        index = _build_symbol_index(tree)

        root = _find_symbol(tree, "kicad_pcb")
        assert root is not None

        # Compare net_class entries
        indexed_classes = index.get("net_class", [])
        found_classes = _find_all_symbols(root, "net_class")
        assert len(indexed_classes) == len(found_classes)

    def test_find_symbol_1000_nodes_fast(self):
        """_find_symbol on a tree with 1000 nodes completes in <1ms."""
        content = _generate_pcb_content(footprint_count=200)
        import sexpdata
        tree = sexpdata.loads(content)

        start = time.perf_counter()
        for _ in range(100):
            _find_symbol(tree, "kicad_pcb")
        elapsed = time.perf_counter() - start

        avg_ms = (elapsed / 100) * 1000
        assert avg_ms < 1.0, f"_find_symbol took {avg_ms:.2f}ms (limit: 1ms)"

    def test_find_all_symbols_1000_nodes_fast(self):
        """_find_all_symbols on a tree with 1000 nodes completes in <10ms."""
        content = _generate_pcb_content(footprint_count=200)
        import sexpdata
        tree = sexpdata.loads(content)

        start = time.perf_counter()
        for _ in range(100):
            _find_all_symbols(tree, "footprint")
        elapsed = time.perf_counter() - start

        avg_ms = (elapsed / 100) * 1000
        assert avg_ms < 10.0, f"_find_all_symbols took {avg_ms:.2f}ms (limit: 10ms)"


# ---------------------------------------------------------------------------
# Part A: Parsing performance tests
# ---------------------------------------------------------------------------


class TestParsingPerformance:
    """Performance regression tests for PCB parsing."""

    def test_parse_1mb_content_under_2_seconds(self):
        """parse_pcb_content with ~1MB content completes in <2 seconds."""
        content = _generate_pcb_content(footprint_count=300)
        size_kb = len(content) / 1024
        assert size_kb > 100, f"Content only {size_kb:.0f}KB, need >100KB"

        start = time.perf_counter()
        board = NativeParser.parse_pcb_content(content)
        elapsed = time.perf_counter() - start

        assert board.footprints, "Should have parsed footprints"
        assert elapsed < 2.0, f"Parsing {size_kb:.0f}KB took {elapsed:.2f}s (limit: 2s)"

    def test_parse_5mb_content_under_10_seconds(self):
        """parse_pcb_content with ~5MB content completes in <10 seconds."""
        content = _generate_pcb_content(footprint_count=1500)
        size_mb = len(content) / (1024 * 1024)
        assert size_mb > 1.0, f"Content only {size_mb:.1f}MB, need >1MB"

        start = time.perf_counter()
        board = NativeParser.parse_pcb_content(content)
        elapsed = time.perf_counter() - start

        assert board.footprints, "Should have parsed footprints"
        assert elapsed < 10.0, f"Parsing {size_mb:.1f}MB took {elapsed:.2f}s (limit: 10s)"

    @pytest.mark.slow
    def test_parse_large_pcb_extracts_all_elements(self):
        """Large PCB parse correctly extracts all element types."""
        footprint_count = 500
        content = _generate_pcb_content(footprint_count=footprint_count, net_count=100)

        board = NativeParser.parse_pcb_content(content)

        assert len(board.footprints) == footprint_count
        assert len(board.nets) == 101  # net 0 + 100 nets
        assert len(board.net_classes) == 1
        assert len(board.segments) == footprint_count
        assert len(board.vias) == footprint_count // 3 + 1  # every 3rd


# ---------------------------------------------------------------------------
# Part B: Depth pre-scan tests
# ---------------------------------------------------------------------------


class TestDepthPreScan:
    """Tests for S-expression depth pre-scan protection."""

    def test_depth_pre_scan_rejects_201(self):
        """parse_raw_sexp depth pre-scan rejects depth=201 content with ValueError."""
        from volta.parser.raw_parser import _pre_scan_depth

        # Generate content with 201 nested parens
        deep = "(" * 201 + "data" + ")" * 201
        with pytest.raises(ValueError, match="nesting depth"):
            _pre_scan_depth(deep)

    def test_depth_pre_scan_accepts_200(self):
        """Depth 200 is accepted (within limit)."""
        from volta.parser.raw_parser import _pre_scan_depth

        deep = "(" * 200 + "data" + ")" * 200
        max_depth = _pre_scan_depth(deep)
        assert max_depth == 200


# ---------------------------------------------------------------------------
# Part C: Stress tests
# ---------------------------------------------------------------------------


class TestParserStress:
    """Stress tests for parser resilience."""

    def test_1000_footprints_no_stack_overflow(self):
        """Parser handles 1000 footprints without stack overflow."""
        content = _generate_pcb_content(footprint_count=1000, net_count=200)
        board = NativeParser.parse_pcb_content(content)
        assert len(board.footprints) == 1000

    def test_empty_content_safe(self):
        """Parser handles empty content safely."""
        board = NativeParser.parse_pcb_content("")
        assert board is not None
        assert board.footprints == ()

    def test_whitespace_only_safe(self):
        """Parser handles whitespace-only content safely."""
        board = NativeParser.parse_pcb_content("   \n\t  \n")
        assert board is not None

    def test_minimal_valid_pcb(self):
        """Parser handles minimal valid PCB content."""
        content = '(kicad_pcb (version 20240108) (generator "test"))'
        board = NativeParser.parse_pcb_content(content)
        assert board is not None
        assert board.version == "20240108"

    def test_fuzz_resilience_random_valid_structure(self):
        """Parser never crashes on fuzz-generated valid S-expression content."""
        import random

        random.seed(42)
        for _ in range(20):
            # Generate random valid S-expression structures
            parts = ["(kicad_pcb"]
            depth = 1
            while depth > 0 and depth < 50:
                action = random.random()
                if action < 0.3 and depth > 1:
                    parts.append(")")
                    depth -= 1
                elif action < 0.6:
                    parts.append(f'(token_{random.randint(1, 100)} "value")')
                else:
                    parts.append(f'(block_{random.randint(1, 50)}')
                    depth += 1
            while depth > 0:
                parts.append(")")
                depth -= 1
            content = " ".join(parts)
            # Should not crash (may return empty board, that's OK)
            board = NativeParser.parse_pcb_content(content)
            assert board is not None


# ---------------------------------------------------------------------------
# Part D: Cache management tests
# ---------------------------------------------------------------------------


class TestCacheManagement:
    """Tests for LocalLLMClient cache management."""

    def test_pre_download_adapter_exists(self):
        """LocalLLMClient.pre_download_adapter() is callable classmethod."""
        from volta.llm.local_client import LocalLLMClient

        assert callable(getattr(LocalLLMClient, "pre_download_adapter", None)), (
            "pre_download_adapter classmethod must exist"
        )

    def test_get_cache_info_exists(self):
        """LocalLLMClient.get_cache_info() is callable classmethod."""
        from volta.llm.local_client import LocalLLMClient

        assert callable(getattr(LocalLLMClient, "get_cache_info", None)), (
            "get_cache_info classmethod must exist"
        )

    def test_pre_download_adapter_triggers_download(self):
        """pre_download_adapter downloads and caches adapter without loading model."""
        import tempfile
        from volta.llm.local_client import LocalLLMClient

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            fake_home = tmp / "home"
            fake_home.mkdir()
            fake_cache = fake_home / ".cache" / "volta" / "adapters"
            fake_cache.mkdir(parents=True)

            # Create fake "downloaded" grpo adapter
            download_tmp = tmp / "downloaded"
            download_tmp.mkdir()
            grpo_downloaded = download_tmp / "grpo"
            grpo_downloaded.mkdir()
            (grpo_downloaded / "adapters.safetensors").write_text("fake-grpo")
            (grpo_downloaded / "adapter_config.json").write_text("{}")

            with patch("pathlib.Path.home", return_value=fake_home):
                # No adapters cached yet -> triggers download
                with patch("huggingface_hub.snapshot_download", return_value=str(download_tmp)):
                    result = LocalLLMClient.pre_download_adapter()

            # Should have copied grpo adapter to cache
            assert result == fake_cache / "grpo"
            assert (fake_cache / "grpo" / "adapters.safetensors").exists()

    def test_get_cache_info_returns_dict(self):
        """get_cache_info returns dict with cache_dir, grpo_cached, sft_cached."""
        import tempfile
        from volta.llm.local_client import LocalLLMClient

        with tempfile.TemporaryDirectory() as tmp_dir:
            fake_home = Path(tmp_dir)
            fake_cache = fake_home / ".cache" / "volta" / "adapters"

            with patch("pathlib.Path.home", return_value=fake_home):
                # Nothing cached
                info = LocalLLMClient.get_cache_info()

            assert isinstance(info, dict)
            assert "cache_dir" in info
            assert "grpo_cached" in info
            assert "sft_cached" in info
            assert "adapter_path" in info
            assert info["cache_dir"] == str(fake_cache)
            assert info["grpo_cached"] is False
            assert info["sft_cached"] is False
            assert info["adapter_path"] is None

    def test_get_cache_info_detects_cached_adapter(self):
        """get_cache_info detects when GRPO adapter is cached."""
        import tempfile
        from volta.llm.local_client import LocalLLMClient

        with tempfile.TemporaryDirectory() as tmp_dir:
            fake_home = Path(tmp_dir)
            fake_cache = fake_home / ".cache" / "volta" / "adapters"
            fake_cache.mkdir(parents=True)
            grpo_dir = fake_cache / "grpo"
            grpo_dir.mkdir()
            (grpo_dir / "adapters.safetensors").write_text("fake")

            with patch("pathlib.Path.home", return_value=fake_home):
                info = LocalLLMClient.get_cache_info()

            assert info["grpo_cached"] is True
            assert info["adapter_path"] == str(grpo_dir)
