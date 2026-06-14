"""Expected artifacts for golden E2E boards (Phase 93).

Each golden board defines its expected manufacturing artifacts.
The test_golden_e2e.py integration tests verify the full gate chain
produces these artifacts for valid boards, and blocks appropriately
for the deliberately broken board.
"""

from __future__ import annotations

# Board definitions with expected artifacts and characteristics
GOLDEN_BOARDS: dict[str, dict] = {
    "led_resistor": {
        "description": "Simple LED + resistor, 2 components, 3 nets",
        "layer_count": 2,
        "component_count": 3,
        "net_count": 3,
        "has_mechanical_constraints": False,
        "expected_artifacts": ["gerbers", "drill", "bom", "cpl"],
        "has_diff_pairs": False,
        "valid": True,
    },
    "buck_regulator": {
        "description": "Switching regulator with inductor, caps, diode",
        "layer_count": 2,
        "component_count": 7,
        "net_count": 8,
        "has_mechanical_constraints": False,
        "expected_artifacts": ["gerbers", "drill", "bom", "cpl"],
        "has_diff_pairs": False,
        "valid": True,
    },
    "mcu_breakout": {
        "description": "MCU with decoupling, crystal, USB, GPIO header",
        "layer_count": 4,
        "component_count": 18,
        "net_count": 20,
        "has_mechanical_constraints": True,
        "expected_artifacts": ["gerbers", "drill", "bom", "cpl", "step"],
        "has_diff_pairs": True,
        "valid": True,
    },
    "opamp_afe": {
        "description": "Dual op-amp analog front end with feedback",
        "layer_count": 2,
        "component_count": 12,
        "net_count": 14,
        "has_mechanical_constraints": False,
        "expected_artifacts": ["gerbers", "drill", "bom", "cpl"],
        "has_diff_pairs": True,
        "valid": True,
    },
    "connector_heavy": {
        "description": "High-density multi-pin connectors + passives",
        "layer_count": 2,
        "component_count": 22,
        "net_count": 30,
        "has_mechanical_constraints": False,
        "expected_artifacts": ["gerbers", "drill", "bom", "cpl"],
        "has_diff_pairs": False,
        "valid": True,
    },
    "controlled_impedance": {
        "description": "4-layer controlled impedance with diff pairs",
        "layer_count": 4,
        "component_count": 8,
        "net_count": 10,
        "has_mechanical_constraints": True,
        "expected_artifacts": ["gerbers", "drill", "bom", "cpl", "step"],
        "has_diff_pairs": True,
        "valid": True,
    },
    "deliberately_broken": {
        "description": "LED board with missing footprint reference (negative test)",
        "layer_count": 2,
        "component_count": 3,
        "net_count": 3,
        "has_mechanical_constraints": False,
        "expected_artifacts": [],
        "has_diff_pairs": False,
        "valid": False,
        "expected_failure_gate": "schematic_intent",
    },
}

VALID_BOARDS = [name for name, cfg in GOLDEN_BOARDS.items() if cfg["valid"]]
ALL_BOARDS = list(GOLDEN_BOARDS.keys())
