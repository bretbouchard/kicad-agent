"""Schemas for circuit intent inference.

DOMAIN-03: Structured representation of inferred designer intent
from circuit topology analysis.

Security:
  T-47-01: subcircuit_intents capped at 50 (DoS prevention).
  T-47-02: signal_flow_description max 2000 chars.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator


class DesignGoal(str, Enum):
    """High-level design goal categories."""

    AUDIO_PROCESSING = "audio_processing"
    POWER_SUPPLY = "power_supply"
    CONTROL = "control"
    MIXING = "mixing"
    FILTERING = "filtering"
    GENERATION = "generation"
    ROUTING = "routing"
    PROTECTION = "protection"
    UNKNOWN = "unknown"


class SubcircuitIntent(BaseModel):
    """Inferred intent for a single subcircuit.

    Attributes:
        function: Inferred function (e.g. "compressor_vca", "bypass_switch").
        component_refs: Component reference designators in this subcircuit.
        input_nets: Nets that carry signal into this subcircuit.
        output_nets: Nets that carry signal out of this subcircuit.
        control_nets: Nets that control this subcircuit's behavior.
        design_choices: Key design decisions identified (e.g. "class_A_bias", "soft_knee").
        confidence: Inference confidence 0.0-1.0.
    """

    function: str = Field(min_length=1, max_length=128)
    component_refs: tuple[str, ...] = Field(default_factory=tuple, max_length=100)
    input_nets: tuple[str, ...] = Field(default_factory=tuple)
    output_nets: tuple[str, ...] = Field(default_factory=tuple)
    control_nets: tuple[str, ...] = Field(default_factory=tuple)
    design_choices: tuple[str, ...] = Field(default_factory=tuple, max_length=20)
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("function")
    @classmethod
    def _function_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("function must not be empty or whitespace")
        return v


class DesignIntent(BaseModel):
    """Complete inferred design intent for a schematic.

    Attributes:
        overall_type: High-level circuit type (e.g. "compressor", "filter", "mixer").
        subcircuit_intents: Intent analysis for each identified subcircuit.
        signal_flow_description: Human-readable signal flow chain.
        design_goals: Set of high-level design goals this circuit serves.
        confidence: Overall inference confidence 0.0-1.0.
        schematic_path: Path to the source schematic.
    """

    overall_type: str = Field(min_length=1, max_length=128)
    subcircuit_intents: tuple[SubcircuitIntent, ...] = Field(
        default_factory=tuple, max_length=50,
    )
    signal_flow_description: str = Field(
        default="", max_length=2000,
        description="Human-readable signal flow, e.g. 'Input -> Switch -> VCA -> Output'",
    )
    design_goals: tuple[DesignGoal, ...] = Field(default_factory=tuple)
    confidence: float = Field(ge=0.0, le=1.0)
    schematic_path: str = Field(default="")
