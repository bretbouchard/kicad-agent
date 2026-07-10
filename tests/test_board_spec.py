"""Tests for BoardSpec model + sidecar JSON persistence (META-04, META-05)."""
from pathlib import Path

from kicad_agent.manufacturing.board_spec import (
    BoardSpec,
    ImpedanceRequirement,
    SurfaceFinish,
    SoldermaskColor,
    SilkscreenColor,
    load_board_spec,
    save_board_spec,
)


def test_default_construction():
    """BoardSpec() has sensible defaults for prototype boards."""
    spec = BoardSpec()
    assert spec.schema_version == 1
    assert spec.surface_finish == SurfaceFinish.HASL
    assert spec.copper_weight_outer_oz == 1.0
    assert spec.copper_weight_inner_oz == 0.5
    assert spec.soldermask_color == SoldermaskColor.GREEN
    assert spec.silkscreen_color == SilkscreenColor.WHITE
    assert spec.impedance_requirements == ()


def test_json_round_trip():
    """model_dump_json -> model_validate_json reproduces BoardSpec exactly."""
    spec = BoardSpec(
        surface_finish=SurfaceFinish.ENIG,
        impedance_requirements=(
            ImpedanceRequirement(net_name="USB_DM", target_ohms=90.0, reference_layer="GND"),
            ImpedanceRequirement(net_name="USB_DP", target_ohms=90.0, reference_layer="GND"),
        ),
    )
    restored = BoardSpec.model_validate_json(spec.model_dump_json(indent=2))
    assert restored == spec


def test_impedance_requirements_round_trip():
    """tuple[ImpedanceRequirement, ...] serializes as JSON array and round-trips."""
    spec = BoardSpec(impedance_requirements=(
        ImpedanceRequirement(net_name="CLK", target_ohms=100.0, reference_layer="L02"),
    ))
    restored = BoardSpec.model_validate_json(spec.model_dump_json(indent=2))
    assert len(restored.impedance_requirements) == 1
    assert restored.impedance_requirements[0].net_name == "CLK"
    assert restored.impedance_requirements[0].target_ohms == 100.0


def test_sidecar_load_save(tmp_path):
    """save_board_spec writes sidecar; load_board_spec restores it."""
    pcb = tmp_path / "board.kicad_pcb"
    pcb.write_text("(kicad_pcb)", encoding="utf-8")
    spec = BoardSpec(surface_finish=SurfaceFinish.ENIG, soldermask_color=SoldermaskColor.BLUE)
    sidecar = save_board_spec(pcb, spec)
    assert sidecar == tmp_path / "board.kicad_build_spec.json"
    assert sidecar.is_file()
    loaded = load_board_spec(pcb)
    assert loaded == spec


def test_sidecar_missing_returns_none(tmp_path):
    """load_board_spec returns None when no sidecar exists."""
    pcb = tmp_path / "board.kicad_pcb"
    pcb.write_text("(kicad_pcb)", encoding="utf-8")
    assert load_board_spec(pcb) is None


def test_str_enum_serializes_as_name():
    """str, Enum serializes as the enum NAME (e.g., 'ENIG'), not the value."""
    spec = BoardSpec(surface_finish=SurfaceFinish.ENIG)
    import json
    data = json.loads(spec.model_dump_json())
    assert data["surface_finish"] == "ENIG"
