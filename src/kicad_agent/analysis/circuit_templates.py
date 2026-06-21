"""Circuit template database for reusable subcircuit topologies.

Provides CircuitTemplateDB for storing, querying, and retrieving pre-defined
circuit topologies (voltage dividers, RC filters, op-amp configs, etc.)
that can be used during schematic auto-generation and intent inference.

Templates are in-memory and keyed by function type. They capture the
topology structure (component types, net connectivity pattern) without
specific values, allowing the generation layer to fill in design-specific
parameters.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CircuitTemplate:
    """A reusable circuit topology template.

    Attributes:
        name: Human-readable template name (e.g., "resistive_voltage_divider").
        function: Functional category (e.g., "filtering", "power_supply").
        description: What this circuit does.
        component_types: Tuple of expected component type prefixes (e.g., ("R", "R")).
        net_pattern: Description of the connectivity pattern between components.
        min_components: Minimum number of components for this topology.
    """

    name: str
    function: str
    description: str
    component_types: tuple[str, ...] = ()
    net_pattern: str = ""
    min_components: int = 1


# Built-in circuit templates covering common analog subcircuits.
_BUILTIN_TEMPLATES: tuple[CircuitTemplate, ...] = (
    CircuitTemplate(
        name="resistive_voltage_divider",
        function="filtering",
        description="Two-resistor voltage divider for signal attenuation or bias",
        component_types=("R", "R"),
        net_pattern="series: VIN -> R1 -> VOUT -> R2 -> GND",
        min_components=2,
    ),
    CircuitTemplate(
        name="rc_low_pass_filter",
        function="filtering",
        description="Resistor-capacitor low-pass filter for signal conditioning",
        component_types=("R", "C"),
        net_pattern="series: VIN -> R -> VOUT, parallel: VOUT -> C -> GND",
        min_components=2,
    ),
    CircuitTemplate(
        name="rc_high_pass_filter",
        function="filtering",
        description="Resistor-capacitor high-pass filter for AC coupling",
        component_types=("C", "R"),
        net_pattern="series: VIN -> C -> VOUT, parallel: VOUT -> R -> GND",
        min_components=2,
    ),
    CircuitTemplate(
        name="lc_low_pass_filter",
        function="filtering",
        description="Inductor-capacitor low-pass filter for EMI suppression",
        component_types=("L", "C"),
        net_pattern="series: VIN -> L -> VOUT, parallel: VOUT -> C -> GND",
        min_components=2,
    ),
    CircuitTemplate(
        name="non_inverting_amplifier",
        function="amplification",
        description="Op-amp non-inverting amplifier with gain set by feedback resistor ratio",
        component_types=("R", "R", "U"),
        net_pattern="VIN -> U+ ; U- divider: R1(GND), R2(Uout->U-)",
        min_components=3,
    ),
    CircuitTemplate(
        name="inverting_amplifier",
        function="amplification",
        description="Op-amp inverting amplifier with gain set by feedback/input resistor ratio",
        component_types=("R", "R", "U"),
        net_pattern="VIN -> Rin -> U- ; Rf: Uout -> U- ; U+ -> GND",
        min_components=3,
    ),
    CircuitTemplate(
        name="pull_up_resistor",
        function="interfacing",
        description="Resistor pull-up to VCC for open-drain/open-collector signals",
        component_types=("R",),
        net_pattern="signal -> R -> VCC",
        min_components=1,
    ),
    CircuitTemplate(
        name="pull_down_resistor",
        function="interfacing",
        description="Resistor pull-down to GND for floating signal prevention",
        component_types=("R",),
        net_pattern="signal -> R -> GND",
        min_components=1,
    ),
    CircuitTemplate(
        name="decoupling_capacitor",
        function="protection",
        description="Power supply decoupling capacitor placed near IC power pins",
        component_types=("C",),
        net_pattern="VCC -> C -> GND",
        min_components=1,
    ),
    CircuitTemplate(
        name="led_with_resistor",
        function="indication",
        description="LED with current-limiting series resistor",
        component_types=("R", "D"),
        net_pattern="VIN -> R -> LED -> GND",
        min_components=2,
    ),
    CircuitTemplate(
        name="transistor_switch",
        function="control",
        description="NPN or N-channel MOSFET low-side switch",
        component_types=("R", "Q"),
        net_pattern="VIN -> R -> Q(base/gate) ; load: VCC -> load -> Q(collector/drain) ; Q(emitter/source) -> GND",
        min_components=2,
    ),
    CircuitTemplate(
        name="diode_protection",
        function="protection",
        description="Reverse polarity protection diode in series with power input",
        component_types=("D",),
        net_pattern="VIN -> D(anode->cathode) -> VOUT",
        min_components=1,
    ),
    CircuitTemplate(
        name="buck_converter_basic",
        function="power_supply",
        description="Basic buck converter topology with inductor, diode, and capacitor",
        component_types=("L", "D", "C", "Q"),
        net_pattern="VIN -> Q -> L -> VOUT ; D: Q-node -> GND ; C: VOUT -> GND",
        min_components=4,
    ),
    CircuitTemplate(
        name="voltage_regulator",
        function="power_supply",
        description="Linear voltage regulator with input/output decoupling capacitors",
        component_types=("U", "C", "C"),
        net_pattern="VIN -> C_in -> GND ; VIN -> U(IN) ; U(OUT) -> C_out -> GND",
        min_components=3,
    ),
)


class CircuitTemplateDB:
    """In-memory database of circuit topology templates.

    Provides lookup by name, function, or component signature.
    Initialized with built-in templates; additional templates can be added.
    """

    def __init__(self) -> None:
        self._templates: dict[str, CircuitTemplate] = {
            t.name: t for t in _BUILTIN_TEMPLATES
        }
        self._custom_templates: dict[str, CircuitTemplate] = {}

    @property
    def templates(self) -> tuple[CircuitTemplate, ...]:
        """All templates (built-in + custom)."""
        return (*self._templates.values(), *self._custom_templates.values())

    def get(self, name: str) -> CircuitTemplate | None:
        """Look up a template by exact name."""
        return self._templates.get(name) or self._custom_templates.get(name)

    def add(self, template: CircuitTemplate) -> None:
        """Register a custom template. Overwrites if name exists."""
        self._custom_templates[template.name] = template

    def remove(self, name: str) -> bool:
        """Remove a custom template by name. Returns True if removed."""
        if name in self._custom_templates:
            del self._custom_templates[name]
            return True
        return False

    def search_by_function(self, function: str) -> tuple[CircuitTemplate, ...]:
        """Find all templates matching a function category."""
        return tuple(
            t for t in self.templates if t.function == function
        )

    def search_by_components(
        self, component_types: tuple[str, ...],
    ) -> tuple[CircuitTemplate, ...]:
        """Find templates whose component_types match exactly."""
        return tuple(
            t for t in self.templates if t.component_types == component_types
        )

    def suggest(
        self, component_prefixes: tuple[str, ...], min_matches: int = 1,
    ) -> tuple[CircuitTemplate, ...]:
        """Suggest templates that could match a set of component prefixes.

        A template matches if all its component_types are present in the
        provided prefixes (order-independent).
        """
        prefix_set = set(component_prefixes)
        results: list[CircuitTemplate] = []
        for t in self.templates:
            if not t.component_types:
                continue
            if set(t.component_types).issubset(prefix_set):
                results.append(t)
        return tuple(results)
