"""Phase 98 R-2: Strategy prompt builder with few-shot JSON schema.

Produces deterministic, schema-grounded prompts for the Gemma 4 12B V2 vision
adapter. The adapter was trained on 6696 samples of FREE-TEXT PCB analysis
(zero contained routing strategy JSON), so the prompt MUST:

1. Show the exact JSON schema the model should emit
2. Include 2+ concrete few-shot exemplars in ```json fences
3. Surface every net name so the model references real names, not hallucinated
4. State board bounds so coordinate suggestions stay in range

This is the bridge between training distribution (natural language) and
inference target (structured JSON). Per RESEARCH.md Pitfall 1 + Q1, prompts
are image-primary with netlist metadata rendered as compact text.

IN-01 (Council): net names are sanitized before interpolation so special
characters (backslashes, double-quotes, newlines) cannot degrade prompt
structure. KiCad net names are restricted in character set in practice,
but this is defensive.
"""

from __future__ import annotations

from volta.routing.strategy import BoardState, Pin


def _sanitize_net_name(name: str) -> str:
    """Sanitize a net name for safe interpolation into a JSON prompt.

    IN-01 (Council): collapses backslashes and double-quotes so a hostile
    or malformed net name cannot break out of the quoted JSON string context.
    Also strips newlines. Returns the sanitized name (without surrounding quotes).
    """
    return (
        str(name)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", " ")
        .replace("\r", " ")
        .strip()
    )


def build_strategy_prompt(
    board_state: BoardState,
    netlist: dict[str, list[Pin]],
) -> str:
    """Build a few-shot prompt for routing strategy JSON.

    Args:
        board_state: Immutable board snapshot (bounds, zones, net classes).
        netlist: Dict mapping net names to pin lists.

    Returns:
        Prompt string containing system instruction, JSON schema, 2 few-shot
        exemplars, live board context (net names + bounds), and a closing
        directive.
    """
    min_x, min_y, max_x, max_y = board_state.board_bounds
    net_lines = "\n".join(
        f"  - \"{_sanitize_net_name(name)}\" ({len(pins)} pins)"
        for name, pins in netlist.items()
    )
    net_names_list = ", ".join(f'"{_sanitize_net_name(n)}"' for n in netlist.keys())

    return f"""You are a PCB routing strategy advisor. Output ONLY a JSON object matching this schema. No prose.

SCHEMA:
```json
{{
  "net_priorities": ["GND", "VCC", "net1"],
  "layer_hints": {{"net_name": "F.Cu"}},
  "keepouts": [{{"x1": 0.0, "y1": 0.0, "x2": 10.0, "y2": 10.0, "layer": "F.Cu", "reason": "RF exclusion"}}],
  "router_assignment": {{"GND": "astar", "VCC": "freerouting"}},
  "routing_notes": "Brief rationale."
}}
```

Valid `router_assignment` values: "astar", "freerouting".

EXAMPLE A (2-layer board, power+signal mix):
```json
{{
  "net_priorities": ["GND", "VCC", "SDA", "SCL"],
  "layer_hints": {{"GND": "B.Cu"}},
  "keepouts": [],
  "router_assignment": {{"GND": "astar", "VCC": "freerouting", "SDA": "astar", "SCL": "astar"}},
  "routing_notes": "GND on B.Cu for plane continuity. Diff pair SDA/SCL length-matched via A*."
}}
```

EXAMPLE B (4-layer board, diff pair present):
```json
{{
  "net_priorities": ["3V3", "GND", "USB_P", "USB_N", "LED1"],
  "layer_hints": {{"USB_P": "In1.Cu", "USB_N": "In1.Cu"}},
  "keepouts": [{{"x1": 20.0, "y1": 20.0, "x2": 30.0, "y2": 30.0, "layer": "F.Cu", "reason": "Crystal keepout"}}],
  "router_assignment": {{"3V3": "freerouting", "GND": "astar", "USB_P": "astar", "USB_N": "astar", "LED1": "freerouting"}},
  "routing_notes": "USB diff pair on In1.Cu for impedance control. Power via Freerouting for density."
}}
```

LIVE BOARD CONTEXT:
- Board bounds: x=[{min_x}, {max_x}], y=[{min_y}, {max_y}] (mm)
- Zones present: {board_state.has_zones}
- Net classes: {", ".join(board_state.net_classes) if board_state.net_classes else "(none)"}
- Total nets: {board_state.total_nets}
- Nets in netlist: [{net_names_list}]
- Per-net pin counts:
{net_lines}

Output the JSON now. Do not include explanations outside the JSON."""
