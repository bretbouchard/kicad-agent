"""Parameterized circuit templates for synthetic training data generation.

Each template defines a common analog building block with:
- Component slots with valid library references
- Net connectivity rules (which pins connect to which nets)
- Parameter ranges for component values
- Validity predicates that reject impossible parameter combinations

Templates are instantiated by sampling from parameter ranges with a
deterministic seed, producing a GenerationIntent that can be validated.

Threat model (C-1):
  _eval_predicate uses safe AST walking — no eval(). Only comparison and
  arithmetic operators on named parameters are allowed. No function calls,
  imports, or attribute access. Predicate strings are developer-defined
  constants in this module, never user input.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class ComponentRange(BaseModel):
    """Range definition for a component parameter.

    Attributes:
        param_name: Parameter name (e.g. "Rb", "Rc", "Cb").
        min_value: Minimum value in standard units (ohms, farads, etc.).
        max_value: Maximum value in standard units.
        log_uniform: If True, sample log-uniformly (for wide ranges like 1R-10M).
        standard_values: If set, constrain to E-series values (E12, E24, E96).
    """

    param_name: str = Field(min_length=1, max_length=64)
    min_value: float = Field(gt=0)
    max_value: float = Field(gt=0)
    log_uniform: bool = Field(default=True)
    standard_values: list[float] | None = Field(default=None)

    @field_validator("max_value")
    @classmethod
    def _max_gt_min(cls, v: float, info) -> float:
        if info.data.get("min_value") is not None and v <= info.data["min_value"]:
            raise ValueError(
                f"max_value ({v}) must be > min_value ({info.data['min_value']})"
            )
        return v


class ComponentTemplate(BaseModel):
    """A component slot in a circuit template.

    Attributes:
        library_id: KiCad library reference (e.g. "Device:R_Small_US").
        reference: Reference designator (e.g. "R1").
        value_template: Format string for value, uses {param_name} placeholders.
        position_hint: (x, y) approximate position for layout.
    """

    library_id: str = Field(min_length=1, max_length=256)
    reference: str = Field(min_length=1, max_length=64)
    value_template: str = Field(min_length=1)
    position_hint: tuple[float, float] = Field(default=(0.0, 0.0))


class NetTemplate(BaseModel):
    """A net connection template.

    Attributes:
        name: Net name (may contain {param_name} for derived nets).
        pins: List of "REF.PIN" strings.
    """

    name: str = Field(min_length=1, max_length=64)
    pins: list[str] = Field(min_length=1)


class CircuitTemplate(BaseModel):
    """A parameterized circuit template.

    Attributes:
        name: Human-readable template name.
        category: Circuit category for classification.
        component_templates: Component slots with value templates.
        net_templates: Net connections with pin references.
        parameter_ranges: Parameter ranges for value generation.
        valid_range_predicates: List of callable validity checks.
            Each takes a dict of {param_name: value} and returns bool.
        description: What this circuit does.
    """

    name: str = Field(min_length=1, max_length=128)
    category: str = Field(min_length=1, max_length=64)
    component_templates: list[ComponentTemplate] = Field(min_length=1)
    net_templates: list[NetTemplate] = Field(min_length=1)
    parameter_ranges: list[ComponentRange] = Field(min_length=1)
    valid_range_predicates: list[str] = Field(default_factory=list)
    description: str = Field(default="", max_length=512)

    @field_validator("component_templates")
    @classmethod
    def _non_empty_components(cls, v):
        if not v:
            raise ValueError("Must have at least 1 component template")
        return v

    @field_validator("net_templates")
    @classmethod
    def _non_empty_nets(cls, v):
        if not v:
            raise ValueError("Must have at least 1 net template")
        return v


# ---------------------------------------------------------------------------
# Predicate evaluator — safe AST walker (C-1: replaces eval)
# ---------------------------------------------------------------------------

import ast as _ast
import operator as _operator

_SAFE_COMPARE_OPS: dict[type, _operator] = {
    _ast.Gt: _operator.gt,
    _ast.GtE: _operator.ge,
    _ast.Lt: _operator.lt,
    _ast.LtE: _operator.le,
    _ast.Eq: _operator.eq,
    _ast.NotEq: _operator.ne,
}

_SAFE_BIN_OPS: dict[type, _operator] = {
    _ast.Add: _operator.add,
    _ast.Sub: _operator.sub,
    _ast.Mult: _operator.mul,
    _ast.Div: _operator.truediv,
}


def _eval_node(node: _ast.AST, params: dict[str, float]) -> float | bool:
    """Recursively evaluate a single AST node against named parameters."""
    if isinstance(node, _ast.Constant):
        return node.value
    if isinstance(node, _ast.Name):
        if node.id not in params:
            raise ValueError(f"Unknown parameter: {node.id}")
        return params[node.id]
    if isinstance(node, _ast.Compare):
        left = _eval_node(node.left, params)
        for op, comparator in zip(node.ops, node.comparators):
            right = _eval_node(comparator, params)
            op_func = _SAFE_COMPARE_OPS.get(type(op))
            if op_func is None:
                raise ValueError(f"Unsupported operator: {type(op).__name__}")
            if not op_func(left, right):
                return False
            left = right
        return True
    if isinstance(node, _ast.BoolOp):
        if isinstance(node.op, _ast.And):
            return all(_eval_node(v, params) for v in node.values)
        if isinstance(node.op, _ast.Or):
            return any(_eval_node(v, params) for v in node.values)
    if isinstance(node, _ast.BinOp):
        op_func = _SAFE_BIN_OPS.get(type(node.op))
        if op_func is None:
            raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
        return op_func(_eval_node(node.left, params), _eval_node(node.right, params))
    raise ValueError(f"Unsupported expression: {_ast.dump(node)}")


def _eval_predicate(predicate_str: str, params: dict[str, float]) -> bool:
    """Evaluate a validity predicate string against parameter values.

    Safety: Uses AST walking — no eval(). Only allows comparison and
    arithmetic operators on named parameters. No function calls, no
    imports, no attribute access. Predicate strings are developer-defined
    constants in this module -- never user input.
    """
    tree = _ast.parse(predicate_str, mode="eval")
    return bool(_eval_node(tree.body, params))


# ---------------------------------------------------------------------------
# 10 Parameterized Circuit Templates
# ---------------------------------------------------------------------------


COMMON_EMITTER_AMP = CircuitTemplate(
    name="common_emitter_amplifier",
    category="amplifier",
    description="NPN common-emitter amplifier with bias, collector, and emitter resistors plus bypass capacitor",
    component_templates=[
        ComponentTemplate(
            library_id="Device:Q_NPN_CBE",
            reference="Q1",
            value_template="2N3904",
            position_hint=(25.0, 25.0),
        ),
        ComponentTemplate(
            library_id="Device:R_Small_US",
            reference="Rb",
            value_template="{Rb}",
            position_hint=(15.0, 15.0),
        ),
        ComponentTemplate(
            library_id="Device:R_Small_US",
            reference="Rc",
            value_template="{Rc}",
            position_hint=(35.0, 15.0),
        ),
        ComponentTemplate(
            library_id="Device:R_Small_US",
            reference="Re",
            value_template="{Re}",
            position_hint=(25.0, 40.0),
        ),
        ComponentTemplate(
            library_id="Device:C_Small",
            reference="Cb",
            value_template="{Cb}",
            position_hint=(5.0, 25.0),
        ),
        ComponentTemplate(
            library_id="Device:C_Small",
            reference="Ce",
            value_template="{Ce}",
            position_hint=(25.0, 50.0),
        ),
    ],
    net_templates=[
        NetTemplate(name="VIN", pins=["Cb.1"]),
        NetTemplate(name="VOUT", pins=["Rc.1", "Q1.C"]),
        NetTemplate(name="BASE", pins=["Rb.2", "Cb.2", "Q1.B"]),
        NetTemplate(name="EMITTER", pins=["Q1.E", "Re.1", "Ce.1"]),
        NetTemplate(name="VCC", pins=["Rb.1", "Rc.2"]),
    ],
    parameter_ranges=[
        ComponentRange(param_name="Rb", min_value=1000, max_value=1000000, log_uniform=True),
        ComponentRange(param_name="Rc", min_value=100, max_value=100000, log_uniform=True),
        ComponentRange(param_name="Re", min_value=10, max_value=10000, log_uniform=True),
        ComponentRange(param_name="Cb", min_value=1e-9, max_value=1e-6, log_uniform=True),
        ComponentRange(param_name="Ce", min_value=1e-9, max_value=100e-6, log_uniform=True),
    ],
    valid_range_predicates=[
        "Rc > Re",
        "Rb > Rc",
        "Re > 0",
    ],
)

OPAMP_INVERTING_AMP = CircuitTemplate(
    name="opamp_inverting_amplifier",
    category="amplifier",
    description="Op-amp inverting amplifier with input and feedback resistors",
    component_templates=[
        ComponentTemplate(
            library_id="Amplifier_Operational:LM358",
            reference="U1",
            value_template="LM358",
            position_hint=(25.0, 25.0),
        ),
        ComponentTemplate(
            library_id="Device:R_Small_US",
            reference="Rin",
            value_template="{Rin}",
            position_hint=(10.0, 25.0),
        ),
        ComponentTemplate(
            library_id="Device:R_Small_US",
            reference="Rf",
            value_template="{Rf}",
            position_hint=(30.0, 15.0),
        ),
    ],
    net_templates=[
        NetTemplate(name="VIN", pins=["Rin.1"]),
        NetTemplate(name="VOUT", pins=["U1.1", "Rf.1"]),
        NetTemplate(name="SUMMING", pins=["Rin.2", "Rf.2", "U1.2"]),
        NetTemplate(name="VCC", pins=["U1.8"]),
        NetTemplate(name="VEE", pins=["U1.4"]),
    ],
    parameter_ranges=[
        ComponentRange(param_name="Rin", min_value=100, max_value=1000000, log_uniform=True),
        ComponentRange(param_name="Rf", min_value=100, max_value=10000000, log_uniform=True),
    ],
    valid_range_predicates=[
        "Rin > 0",
        "Rf > 0",
        "Rf / Rin <= 1000",
        "Rf / Rin >= 0.1",
    ],
)

SALLEN_KEY_LPF = CircuitTemplate(
    name="sallen_key_lowpass_filter",
    category="filter",
    description="Sallen-Key 2nd-order low-pass filter with unity gain",
    component_templates=[
        ComponentTemplate(
            library_id="Amplifier_Operational:LM358",
            reference="U1",
            value_template="LM358",
            position_hint=(25.0, 30.0),
        ),
        ComponentTemplate(
            library_id="Device:R_Small_US",
            reference="R1",
            value_template="{R1}",
            position_hint=(10.0, 25.0),
        ),
        ComponentTemplate(
            library_id="Device:R_Small_US",
            reference="R2",
            value_template="{R2}",
            position_hint=(10.0, 40.0),
        ),
        ComponentTemplate(
            library_id="Device:C_Small",
            reference="C1",
            value_template="{C1}",
            position_hint=(30.0, 15.0),
        ),
        ComponentTemplate(
            library_id="Device:C_Small",
            reference="C2",
            value_template="{C2}",
            position_hint=(20.0, 50.0),
        ),
    ],
    net_templates=[
        NetTemplate(name="VIN", pins=["R1.1"]),
        NetTemplate(name="VOUT", pins=["U1.1", "C1.2"]),
        NetTemplate(name="NODE_A", pins=["R1.2", "R2.1", "C1.1"]),
        NetTemplate(name="NODE_B", pins=["R2.2", "C2.1", "U1.3"]),
        NetTemplate(name="VCC", pins=["U1.8"]),
        NetTemplate(name="VEE", pins=["U1.4"]),
    ],
    parameter_ranges=[
        ComponentRange(param_name="R1", min_value=100, max_value=1000000, log_uniform=True),
        ComponentRange(param_name="R2", min_value=100, max_value=1000000, log_uniform=True),
        ComponentRange(param_name="C1", min_value=100e-12, max_value=10e-6, log_uniform=True),
        ComponentRange(param_name="C2", min_value=100e-12, max_value=10e-6, log_uniform=True),
    ],
    valid_range_predicates=[
        "R1 > 0",
        "R2 > 0",
        "C1 > 0",
        "C2 > 0",
        "C1 / C2 <= 10.0",
        "C2 / C1 <= 10.0",
    ],
)

VOLTAGE_FOLLOWER = CircuitTemplate(
    name="voltage_follower",
    category="buffer",
    description="Op-amp voltage follower (unity-gain buffer)",
    component_templates=[
        ComponentTemplate(
            library_id="Amplifier_Operational:LM358",
            reference="U1",
            value_template="LM358",
            position_hint=(25.0, 25.0),
        ),
    ],
    net_templates=[
        NetTemplate(name="VIN", pins=["U1.3"]),
        NetTemplate(name="VOUT", pins=["U1.1", "U1.2"]),
        NetTemplate(name="VCC", pins=["U1.8"]),
        NetTemplate(name="VEE", pins=["U1.4"]),
    ],
    parameter_ranges=[
        ComponentRange(param_name="bw_hz", min_value=1, max_value=1000000, log_uniform=True),
    ],
    valid_range_predicates=["bw_hz > 0"],
)

RC_LPF = CircuitTemplate(
    name="rc_lowpass_filter",
    category="filter",
    description="Passive RC low-pass filter",
    component_templates=[
        ComponentTemplate(
            library_id="Device:R_Small_US",
            reference="R1",
            value_template="{R1}",
            position_hint=(15.0, 25.0),
        ),
        ComponentTemplate(
            library_id="Device:C_Small",
            reference="C1",
            value_template="{C1}",
            position_hint=(30.0, 35.0),
        ),
    ],
    net_templates=[
        NetTemplate(name="VIN", pins=["R1.1"]),
        NetTemplate(name="VOUT", pins=["R1.2", "C1.1"]),
    ],
    parameter_ranges=[
        ComponentRange(param_name="R1", min_value=10, max_value=10000000, log_uniform=True),
        ComponentRange(param_name="C1", min_value=1e-12, max_value=1e-3, log_uniform=True),
    ],
    valid_range_predicates=["R1 > 0", "C1 > 0"],
)

RC_HPF = CircuitTemplate(
    name="rc_highpass_filter",
    category="filter",
    description="Passive RC high-pass filter",
    component_templates=[
        ComponentTemplate(
            library_id="Device:C_Small",
            reference="C1",
            value_template="{C1}",
            position_hint=(15.0, 25.0),
        ),
        ComponentTemplate(
            library_id="Device:R_Small_US",
            reference="R1",
            value_template="{R1}",
            position_hint=(30.0, 35.0),
        ),
    ],
    net_templates=[
        NetTemplate(name="VIN", pins=["C1.1"]),
        NetTemplate(name="VOUT", pins=["C1.2", "R1.1"]),
    ],
    parameter_ranges=[
        ComponentRange(param_name="C1", min_value=1e-12, max_value=1e-3, log_uniform=True),
        ComponentRange(param_name="R1", min_value=10, max_value=10000000, log_uniform=True),
    ],
    valid_range_predicates=["C1 > 0", "R1 > 0"],
)

VOLTAGE_DIVIDER = CircuitTemplate(
    name="voltage_divider",
    category="passive",
    description="Resistive voltage divider",
    component_templates=[
        ComponentTemplate(
            library_id="Device:R_Small_US",
            reference="R1",
            value_template="{R1}",
            position_hint=(20.0, 15.0),
        ),
        ComponentTemplate(
            library_id="Device:R_Small_US",
            reference="R2",
            value_template="{R2}",
            position_hint=(20.0, 35.0),
        ),
    ],
    net_templates=[
        NetTemplate(name="VIN", pins=["R1.1"]),
        NetTemplate(name="VOUT", pins=["R1.2", "R2.1"]),
    ],
    parameter_ranges=[
        ComponentRange(param_name="R1", min_value=10, max_value=10000000, log_uniform=True),
        ComponentRange(param_name="R2", min_value=10, max_value=10000000, log_uniform=True),
    ],
    valid_range_predicates=["R1 > 0", "R2 > 0"],
)

LED_DRIVER = CircuitTemplate(
    name="led_driver",
    category="driver",
    description="LED with current-limiting resistor",
    component_templates=[
        ComponentTemplate(
            library_id="Device:LED",
            reference="D1",
            value_template="LED",
            position_hint=(30.0, 25.0),
        ),
        ComponentTemplate(
            library_id="Device:R_Small_US",
            reference="R1",
            value_template="{R1}",
            position_hint=(15.0, 25.0),
        ),
    ],
    net_templates=[
        NetTemplate(name="VCC", pins=["R1.1"]),
        NetTemplate(name="ANODE", pins=["R1.2", "D1.1"]),
    ],
    parameter_ranges=[
        ComponentRange(param_name="R1", min_value=100, max_value=10000, log_uniform=True),
    ],
    valid_range_predicates=["R1 >= 100"],
)

MOSFET_SWITCH = CircuitTemplate(
    name="mosfet_switch",
    category="switch",
    description="N-channel MOSFET as a low-side switch with gate resistor",
    component_templates=[
        ComponentTemplate(
            library_id="Device:Q_NMOS_GDS",
            reference="Q1",
            value_template="2N7002",
            position_hint=(25.0, 25.0),
        ),
        ComponentTemplate(
            library_id="Device:R_Small_US",
            reference="Rg",
            value_template="{Rg}",
            position_hint=(10.0, 25.0),
        ),
        ComponentTemplate(
            library_id="Device:R_Small_US",
            reference="Rgs",
            value_template="{Rgs}",
            position_hint=(10.0, 40.0),
        ),
    ],
    net_templates=[
        NetTemplate(name="GATE_IN", pins=["Rg.1"]),
        NetTemplate(name="GATE", pins=["Rg.2", "Rgs.1", "Q1.G"]),
        NetTemplate(name="DRAIN_OUT", pins=["Q1.D"]),
        NetTemplate(name="SOURCE", pins=["Q1.S"]),
    ],
    parameter_ranges=[
        ComponentRange(param_name="Rg", min_value=10, max_value=10000, log_uniform=True),
        ComponentRange(param_name="Rgs", min_value=1000, max_value=10000000, log_uniform=True),
    ],
    valid_range_predicates=[
        "Rg > 0",
        "Rgs > Rg",
        "Rgs >= 1000",
    ],
)

SCHMITT_TRIGGER = CircuitTemplate(
    name="schmitt_trigger",
    category="digital",
    description="Two-transistor Schmitt trigger with hysteresis",
    component_templates=[
        ComponentTemplate(
            library_id="Device:Q_NPN_CBE",
            reference="Q1",
            value_template="2N3904",
            position_hint=(20.0, 20.0),
        ),
        ComponentTemplate(
            library_id="Device:Q_NPN_CBE",
            reference="Q2",
            value_template="2N3904",
            position_hint=(35.0, 20.0),
        ),
        ComponentTemplate(
            library_id="Device:R_Small_US",
            reference="R1",
            value_template="{R1}",
            position_hint=(10.0, 10.0),
        ),
        ComponentTemplate(
            library_id="Device:R_Small_US",
            reference="R2",
            value_template="{R2}",
            position_hint=(20.0, 35.0),
        ),
        ComponentTemplate(
            library_id="Device:R_Small_US",
            reference="R3",
            value_template="{R3}",
            position_hint=(35.0, 35.0),
        ),
        ComponentTemplate(
            library_id="Device:R_Small_US",
            reference="R4",
            value_template="{R4}",
            position_hint=(45.0, 10.0),
        ),
    ],
    net_templates=[
        NetTemplate(name="VIN", pins=["R1.1"]),
        NetTemplate(name="VOUT", pins=["Q2.C", "R4.2"]),
        NetTemplate(name="Q1_BASE", pins=["R1.2", "Q1.B"]),
        NetTemplate(name="Q1_COLL", pins=["Q1.C", "R3.1"]),
        NetTemplate(name="Q2_BASE", pins=["R2.1", "R3.2", "Q2.B"]),
        NetTemplate(name="EMITTERS", pins=["Q1.E", "Q2.E", "R2.2"]),
        NetTemplate(name="VCC", pins=["R4.1"]),
    ],
    parameter_ranges=[
        ComponentRange(param_name="R1", min_value=1000, max_value=100000, log_uniform=True),
        ComponentRange(param_name="R2", min_value=100, max_value=10000, log_uniform=True),
        ComponentRange(param_name="R3", min_value=1000, max_value=100000, log_uniform=True),
        ComponentRange(param_name="R4", min_value=1000, max_value=47000, log_uniform=True),
    ],
    valid_range_predicates=[
        "R1 > 0",
        "R2 > 0",
        "R3 > 0",
        "R4 > 0",
        "R1 > R2",
        "R3 > R2",
    ],
)

ALL_TEMPLATES: list[CircuitTemplate] = [
    COMMON_EMITTER_AMP,
    OPAMP_INVERTING_AMP,
    SALLEN_KEY_LPF,
    VOLTAGE_FOLLOWER,
    RC_LPF,
    RC_HPF,
    VOLTAGE_DIVIDER,
    LED_DRIVER,
    MOSFET_SWITCH,
    SCHMITT_TRIGGER,
]


def get_all_templates() -> list[CircuitTemplate]:
    """Return all circuit templates."""
    return list(ALL_TEMPLATES)


def get_template_by_name(name: str) -> CircuitTemplate | None:
    """Look up a template by name."""
    for t in ALL_TEMPLATES:
        if t.name == name:
            return t
    return None


def instantiate_template(
    template: CircuitTemplate,
    seed: int,
) -> dict[str, float]:
    """Sample parameter values from a template's ranges using deterministic seed.

    Args:
        template: Circuit template with parameter ranges.
        seed: Random seed for deterministic sampling.

    Returns:
        Dict mapping parameter names to sampled values.

    Raises:
        ValueError: If no valid parameter set found after 100 attempts.
    """
    import math
    import random

    rng = random.Random(seed)

    for _ in range(100):  # Max 100 attempts to satisfy predicates
        params: dict[str, float] = {}
        for pr in template.parameter_ranges:
            if pr.log_uniform:
                log_min = math.log10(pr.min_value)
                log_max = math.log10(pr.max_value)
                params[pr.param_name] = 10 ** rng.uniform(log_min, log_max)
            else:
                params[pr.param_name] = rng.uniform(pr.min_value, pr.max_value)

        if all(_eval_predicate(p, params) for p in template.valid_range_predicates):
            return params

    raise ValueError(
        f"Could not satisfy validity predicates for template "
        f"'{template.name}' after 100 attempts with seed {seed}"
    )
