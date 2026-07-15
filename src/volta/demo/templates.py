"""Built-in circuit templates for the demo pipeline.

Each template wraps a GenerationIntent with metadata for showcase selection.
Difficulty tiers guide users from simple to complex circuits.
"""
from __future__ import annotations

import random
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from volta.generation.intent import (
    BoardSpec,
    ComponentSpec,
    GenerationIntent,
    NetSpec,
    PowerSpec,
)


class DemoTemplate(BaseModel):
    """A circuit template for the demo pipeline.

    Attributes:
        name: Unique template identifier (kebab-case, used as CLI argument).
        description: Human-readable one-line description.
        intent: GenerationIntent defining the circuit.
        difficulty: Difficulty tier for showcase ordering.
        expected_component_count: Approximate components in generated schematic.
        expected_net_count: Approximate nets in generated schematic.
    """

    name: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9\-]*$")
    description: str = Field(min_length=1)
    intent: GenerationIntent
    difficulty: Literal["basic", "intermediate", "advanced"]
    expected_component_count: int = Field(ge=1)
    expected_net_count: int = Field(ge=1)

    @field_validator("name")
    @classmethod
    def _name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Template name must not be empty")
        return v


# --- Built-in templates ---

BUILTIN_TEMPLATES: dict[str, DemoTemplate] = {}


def _register(t: DemoTemplate) -> DemoTemplate:
    """Register a template in the global registry."""
    BUILTIN_TEMPLATES[t.name] = t
    return t


# Basic tier

_register(DemoTemplate(
    name="rc-lowpass",
    description="RC low-pass filter (2 components)",
    difficulty="basic",
    expected_component_count=3,
    expected_net_count=2,
    intent=GenerationIntent(
        name="RC_LowPass",
        board=BoardSpec(width_mm=50, height_mm=40),
        components=[
            ComponentSpec(library_id="Device:R", reference="R1", value="1k"),
            ComponentSpec(library_id="Device:C", reference="C1", value="100n"),
        ],
        nets=[
            NetSpec(name="IN", pins=["R1.1"]),
            NetSpec(name="OUT", pins=["R1.2", "C1.1"]),
        ],
        power=PowerSpec(nets=["GND"]),
    ),
))

_register(DemoTemplate(
    name="opamp-buffer",
    description="Op-amp unity-gain buffer (5 components)",
    difficulty="basic",
    expected_component_count=5,
    expected_net_count=4,
    intent=GenerationIntent(
        name="OpAmp_Buffer",
        board=BoardSpec(width_mm=60, height_mm=50),
        components=[
            ComponentSpec(library_id="Amplifier_Operational:NE5532", reference="U1", value="NE5532"),
            ComponentSpec(library_id="Device:R", reference="R1", value="10k"),
            ComponentSpec(library_id="Device:C", reference="C1", value="100n"),
            ComponentSpec(library_id="Device:C", reference="C2", value="100n"),
        ],
        nets=[
            NetSpec(name="IN", pins=["R1.1"]),
            NetSpec(name="OUT", pins=["U1.1"]),
            NetSpec(name="FB", pins=["U1.1", "U1.2"]),
        ],
        power=PowerSpec(nets=["GND", "+12V", "-12V"]),
    ),
))

# Intermediate tier

_register(DemoTemplate(
    name="common-emitter",
    description="Common-emitter transistor amplifier (8 components)",
    difficulty="intermediate",
    expected_component_count=8,
    expected_net_count=6,
    intent=GenerationIntent(
        name="Common_Emitter",
        board=BoardSpec(width_mm=80, height_mm=60),
        components=[
            ComponentSpec(library_id="Device:Q_NPN_BCE", reference="Q1", value="2N3904"),
            ComponentSpec(library_id="Device:R", reference="R1", value="10k"),
            ComponentSpec(library_id="Device:R", reference="R2", value="2.2k"),
            ComponentSpec(library_id="Device:R", reference="R3", value="100k"),
            ComponentSpec(library_id="Device:R", reference="R4", value="10k"),
            ComponentSpec(library_id="Device:C", reference="C1", value="100n"),
            ComponentSpec(library_id="Device:C", reference="C2", value="10u"),
            ComponentSpec(library_id="Device:C", reference="C3", value="100n"),
        ],
        nets=[
            NetSpec(name="IN", pins=["C1.1"]),
            NetSpec(name="OUT", pins=["C2.2", "Q1.1"]),
            NetSpec(name="BASE", pins=["R3.2", "R1.2", "C1.2", "Q1.2"]),
            NetSpec(name="COLLECTOR", pins=["R4.1", "Q1.1", "C2.1"]),
        ],
        power=PowerSpec(nets=["GND", "+9V"]),
    ),
))

_register(DemoTemplate(
    name="sallen-key",
    description="Sallen-Key 2nd-order low-pass filter (10 components)",
    difficulty="intermediate",
    expected_component_count=10,
    expected_net_count=8,
    intent=GenerationIntent(
        name="Sallen_Key_LPF",
        board=BoardSpec(width_mm=80, height_mm=60),
        components=[
            ComponentSpec(library_id="Amplifier_Operational:NE5532", reference="U1", value="NE5532"),
            ComponentSpec(library_id="Device:R", reference="R1", value="10k"),
            ComponentSpec(library_id="Device:R", reference="R2", value="10k"),
            ComponentSpec(library_id="Device:R", reference="R3", value="10k"),
            ComponentSpec(library_id="Device:C", reference="C1", value="100n"),
            ComponentSpec(library_id="Device:C", reference="C2", value="100n"),
            ComponentSpec(library_id="Device:C", reference="C3", value="100n"),
            ComponentSpec(library_id="Device:C", reference="C4", value="100n"),
        ],
        nets=[
            NetSpec(name="IN", pins=["R1.1"]),
            NetSpec(name="OUT", pins=["U1.1"]),
            NetSpec(name="FB", pins=["U1.1", "R3.2"]),
            NetSpec(name="NODE_A", pins=["R1.2", "C1.1", "R2.1"]),
            NetSpec(name="NODE_B", pins=["R2.2", "C2.1", "U1.2"]),
        ],
        power=PowerSpec(nets=["GND", "+12V", "-12V"]),
    ),
))

# Advanced tier

_register(DemoTemplate(
    name="that4301-compressor",
    description="THAT4301 VCA compressor stage (15 components)",
    difficulty="advanced",
    expected_component_count=15,
    expected_net_count=12,
    intent=GenerationIntent(
        name="THAT4301_Compressor",
        board=BoardSpec(width_mm=100, height_mm=80),
        components=[
            ComponentSpec(library_id="THAT:THAT4301", reference="U1", value="THAT4301"),
            ComponentSpec(library_id="Device:R", reference="R1", value="10k"),
            ComponentSpec(library_id="Device:R", reference="R2", value="10k"),
            ComponentSpec(library_id="Device:R", reference="R3", value="100k"),
            ComponentSpec(library_id="Device:R", reference="R4", value="10k"),
            ComponentSpec(library_id="Device:R", reference="R5", value="2.2k"),
            ComponentSpec(library_id="Device:C", reference="C1", value="100n"),
            ComponentSpec(library_id="Device:C", reference="C2", value="10u"),
            ComponentSpec(library_id="Device:C", reference="C3", value="100n"),
            ComponentSpec(library_id="Device:C", reference="C4", value="100n"),
            ComponentSpec(library_id="Device:C", reference="C5", value="10u"),
            ComponentSpec(library_id="Amplifier_Operational:NE5532", reference="U2", value="NE5532"),
        ],
        nets=[
            NetSpec(name="IN", pins=["C1.1"]),
            NetSpec(name="OUT", pins=["U2.1"]),
            NetSpec(name="VCA_OUT", pins=["U1.8", "R4.1"]),
            NetSpec(name="CONTROL", pins=["R3.2", "U1.1"]),
        ],
        power=PowerSpec(nets=["GND", "+12V", "-12V", "+5V"]),
    ),
))

_register(DemoTemplate(
    name="ne5532-dual-stage",
    description="NE5532 dual op-amp gain stage (12 components)",
    difficulty="advanced",
    expected_component_count=12,
    expected_net_count=10,
    intent=GenerationIntent(
        name="NE5532_Dual_Stage",
        board=BoardSpec(width_mm=90, height_mm=70),
        components=[
            ComponentSpec(library_id="Amplifier_Operational:NE5532", reference="U1", value="NE5532"),
            ComponentSpec(library_id="Device:R", reference="R1", value="10k"),
            ComponentSpec(library_id="Device:R", reference="R2", value="100k"),
            ComponentSpec(library_id="Device:R", reference="R3", value="10k"),
            ComponentSpec(library_id="Device:R", reference="R4", value="100k"),
            ComponentSpec(library_id="Device:R", reference="R5", value="1k"),
            ComponentSpec(library_id="Device:C", reference="C1", value="100n"),
            ComponentSpec(library_id="Device:C", reference="C2", value="100n"),
            ComponentSpec(library_id="Device:C", reference="C3", value="100n"),
            ComponentSpec(library_id="Device:C", reference="C4", value="10u"),
        ],
        nets=[
            NetSpec(name="IN", pins=["C1.1"]),
            NetSpec(name="STAGE1_OUT", pins=["U1.1", "R2.1", "R3.1"]),
            NetSpec(name="STAGE2_OUT", pins=["U1.7", "R4.1", "R5.1"]),
            NetSpec(name="OUT", pins=["R5.2"]),
            NetSpec(name="FB1", pins=["U1.2", "R1.2", "R2.2"]),
            NetSpec(name="FB2", pins=["U1.6", "R3.2", "R4.2"]),
        ],
        power=PowerSpec(nets=["GND", "+12V", "-12V"]),
    ),
))


def get_template(name: str) -> DemoTemplate:
    """Look up a template by name.

    Args:
        name: Template identifier (kebab-case).

    Returns:
        The matching DemoTemplate.

    Raises:
        KeyError: If name not found, with available names in message.
    """
    if name in BUILTIN_TEMPLATES:
        return BUILTIN_TEMPLATES[name]
    available = ", ".join(sorted(BUILTIN_TEMPLATES.keys()))
    raise KeyError(f"Template {name!r} not found. Available: {available}")


def list_templates() -> list[tuple[str, str, str]]:
    """List all available templates.

    Returns:
        List of (name, description, difficulty) tuples sorted by difficulty tier.
    """
    tier_order = {"basic": 0, "intermediate": 1, "advanced": 2}
    templates = [(t.name, t.description, t.difficulty) for t in BUILTIN_TEMPLATES.values()]
    return sorted(templates, key=lambda x: (tier_order.get(x[2], 99), x[0]))


def get_random_template() -> DemoTemplate:
    """Select a random template from the registry.

    Returns:
        Random DemoTemplate.

    Raises:
        RuntimeError: If no templates are registered.
    """
    if not BUILTIN_TEMPLATES:
        raise RuntimeError("No templates registered")
    return random.choice(list(BUILTIN_TEMPLATES.values()))
