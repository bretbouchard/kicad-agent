"""Claude tool definitions derived from existing Pydantic schemas.

Provides INTENT_TOOL and SUGGEST_TOOL as plain dicts suitable for
passing to the Anthropic SDK's ``tools`` parameter. Each tool definition
uses JSON Schema derived from existing Pydantic models.

Security (threat model):
  T-15-06: Tool input_schema derived from Pydantic models with length constraints
           (500 components, 200 nets) to prevent DoS via oversized LLM output.
"""

from __future__ import annotations

from kicad_agent.generation.intent import GenerationIntent

INTENT_TOOL = {
    "name": "create_design_intent",
    "description": (
        "Convert a natural language circuit description into a structured "
        "design intent with board specs, components, nets, and power requirements"
    ),
    "input_schema": GenerationIntent.model_json_schema(),
}

SUGGEST_TOOL = {
    "name": "suggest_components",
    "description": (
        "Given a functional description, suggest KiCad components "
        "with valid library_id values and rationale"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "suggestions": {
                "type": "array",
                "description": "List of suggested KiCad components",
                "items": {
                    "type": "object",
                    "properties": {
                        "library_id": {
                            "type": "string",
                            "description": "KiCad symbol library ID (e.g., Device:R_Small_US)",
                        },
                        "value": {
                            "type": "string",
                            "description": "Component value (e.g., 10k, 100nF)",
                        },
                        "reference_prefix": {
                            "type": "string",
                            "description": "Reference prefix (e.g., R, C, U)",
                        },
                        "rationale": {
                            "type": "string",
                            "description": "Why this component was suggested",
                        },
                    },
                    "required": ["library_id", "value", "reference_prefix"],
                },
            },
        },
        "required": ["suggestions"],
    },
}

COMPONENT_SYSTEM_PROMPT = """You suggest KiCad components. Use these common library IDs:
- Resistors: Device:R_Small_US, Device:R_Small, Device:R
- Capacitors: Device:C_Small, Device:C, Device:C_Polarized
- LEDs: Device:LED, Device:LED_Small
- Diodes: Device:D, Device:D_Schottky, Device:D_Zener
- Inductors: Device:L, Device:L_Small
- Transistors: Device:Q_NPN_BCE, Device:Q_PNP_BCE, Device:Q_NMOS_GDS
- Regulators: Regulator_Linear:AMS1117-3.3, Regulator_Linear:LM7805_TO220
- MCUs: MCU_Microchip:ATtiny202, MCU_ST_STM32:STM32F103C8Tx
- Crystals: Device:Crystal, Device:Crystal_Small
- Switches: Switch:SW_Push
Always use Device: prefix for passive components."""
