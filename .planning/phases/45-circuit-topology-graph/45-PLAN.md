# Phase 45: Circuit Topology Graph

**Status:** PLANNING
**Requirements:** DOMAIN-01, DOMAIN-02
**Depends on:** Phase 39 (net extraction, conflict detection)
**Milestone:** v3.0

## Goal

Build a net-to-component graph with signal flow direction inference on top of the existing SchematicGraph and BoardGraphResult infrastructure. This moves kicad-agent from "which pins are connected" to "which direction does signal flow and why" -- the foundational layer for all domain intelligence.

## Context

The Domain Intelligence dimension is at 2/10. We have connectivity analysis (NetGraph, SchematicGraph, BoardGraphResult) that answers "what is connected to what" but nothing that answers "what does this circuit do" or "which way does signal flow". Every downstream capability -- component function recognition (Phase 46), circuit QA (Phase 42), intelligent repair -- requires understanding signal flow direction and net purpose.

Existing infrastructure to build on:
- `schematic_routing/schematic_graph.py` -- SchematicGraph with BFS wire tracing, pin positions, label resolution
- `training/graph_builder.py` -- BoardGraphResult with networkx node-link-data
- `training/schematic_graph_builder.py` -- SchematicGraphResult with Union-Find net grouping
- `analysis/connectivity.py` -- NetGraph with shortest_path, connectivity components
- `ops/violation_classifier.py` -- Rule-based classification pattern (first-match-wins ordered rules)

The topology graph adds a directed signal flow layer: IC output pins drive nets, input pins receive, passives are bidirectional, power pins are sources. This is enough to trace signal from input to output through a schematic and classify nets by purpose.

## Plans

### Plan 45-01: Topology Graph Construction (DOMAIN-01)

**Goal:** Build a directed networkx graph from SchematicIR or SchematicGraph where nodes are components and edges are signal-carrying nets with flow direction.

**Schema:**
```python
class NetClassification(str, Enum):
    POWER = "POWER"
    GROUND = "GROUND"
    SIGNAL = "SIGNAL"
    CONTROL = "CONTROL"
    FEEDBACK = "FEEDBACK"
    CLOCK = "CLOCK"
    UNKNOWN = "UNKNOWN"

@dataclass(frozen=True)
class TopologyNode:
    ref: str                    # "U1", "R5", "C12"
    lib_id: str                 # "NE5532", "Device:R"
    component_type: str         # "ic", "resistor", "capacitor", "inductor", "diode", "transistor", "connector", "misc"
    pin_count: int
    power_pins: list[str]       # Pin numbers that connect to power/ground nets
    input_pins: list[str]       # Pin numbers classified as signal inputs
    output_pins: list[str]      # Pin numbers classified as signal outputs

@dataclass(frozen=True)
class TopologyEdge:
    net_name: str
    source_ref: str             # Driving component ref (or "" for external inputs)
    source_pin: str             # Pin number on source
    target_ref: str             # Receiving component ref
    target_pin: str             # Pin number on target
    classification: NetClassification
    signal_direction: str       # "forward", "feedback", "bidirectional", "power", "unknown"

@dataclass(frozen=True)
class CircuitTopology:
    nodes: list[TopologyNode]
    edges: list[TopologyEdge]
    input_nets: list[str]       # Nets entering the circuit from connectors/external
    output_nets: list[str]      # Nets leaving the circuit to connectors/external
    power_nets: list[str]       # All power/ground nets
    signal_paths: list[list[str]]  # Ordered list of refs from input to output
    stats: dict                 # component_count, net_count, signal_path_count, etc.
```

**Signal flow inference rules:**
1. IC output pins (based on lib_id + pin_name patterns) drive nets -- edge direction: IC -> net -> downstream
2. IC input pins receive from nets -- edge direction: upstream -> net -> IC
3. Passive components (R, C, L) are bidirectional -- two edges, one in each direction
4. Power pins (VCC, VDD, GND, VSS) are sources -- edges flow OUT from power nets
5. Connector pins that are inputs drive their nets
6. Feedback is detected when a net connects an output-stage component back to an input-stage component

**IC pin classification heuristics:**
- Op-amps (NE5532, TL072, LM358): IN+, IN- = input; OUT = output; V+, V- = power
- VCAs (THAT4301, THAT2181): INPUT, EC+ = input; OUTPUT = output; V+, V- = power
- Switches (CD4066BE): all signal pins bidirectional; VDD, VSS, IN (control) classified
- MCUs (RP2040, ATmega): GPIO bidirectional; power pins classified; SPI/I2C by pin name
- Regulators (LM7805, LM317): IN = input; OUT = output; GND/ADJ = power/control
- Default for unknown ICs: pins named IN/INPUT = input; OUT/OUTPUT = output; VCC/VDD/V+/VSS/GND/V- = power

**Implementation:**
1. Create `src/kicad_agent/analysis/topology_graph.py` -- TopologyBuilder class
2. Create `src/kicad_agent/analysis/net_classifier.py` -- NetClassifier with rule-based classification
3. Create `tests/test_topology_graph.py` -- TDD tests with mock schematics

**Tests:**
- TopologyBuilder.from_schematic_graph produces directed graph with correct edge directions
- Op-amp subcircuit: output pin drives net, input pins receive from nets
- Power nets classified as POWER/GROUND, not SIGNAL
- Feedback loop detected when output connects back to input stage
- Resistor between two ICs creates bidirectional edges
- Signal path traces from input connector to output connector
- Empty schematic produces empty topology
- Single-component schematic produces node with no edges
- NetClassifier correctly identifies VCC/VDD/+12V/+5V as POWER
- NetClassifier correctly identifies GND/VSS/AGND/PGND as GROUND

---

### Plan 45-02: Net Classification and Signal Integrity (DOMAIN-02)

**Goal:** Extend topology graph with heuristic net classification using naming patterns + topology analysis, signal integrity classification, and importance ranking.

**Adds to 45-01:**
- Heuristic net classifier combining naming patterns with topology context
- Signal integrity classification: high-speed (clocks, fast edges) vs low-frequency (audio, DC)
- Net importance ranking: critical (power, clock, feedback) > signal > unknown
- Net stats: fanout count, stub detection, longest path from input to output

**Classification rules (naming patterns):**
```python
POWER_PATTERNS = ["VCC", "VDD", "V+", "+3V3", "+5V", "+9V", "+12V", "-9V", "-12V", "VAA", "VCC_AUDIO"]
GROUND_PATTERNS = ["GND", "VSS", "AGND", "PGND", "DGND", "CHASSIS", "EARTH", "GNDA"]
CLOCK_PATTERNS = ["CLK", "MCLK", "BCLK", "LRCLK", "SCK", "XTAL", "OSC"]
CONTROL_PATTERNS = ["EN", "CS", "RST", "RESET", "WR", "RD", "SEL", "MUX", "SDA", "SCL", "TX", "RX"]
```

**Topology-based overrides:**
- If net connects only to power pins on all components -> POWER (regardless of name)
- If net connects to a feedback path -> FEEDBACK
- If net has a clock source component -> CLOCK
- If net is driven by a control pin (CS, EN, RST) -> CONTROL
- Everything else -> SIGNAL

**Tests:**
- Named power nets classified as POWER
- Unnamed net connecting only to power pins classified as POWER by topology
- Clock net from oscillator component classified as CLOCK
- Feedback net detected and classified as FEEDBACK
- Signal integrity: audio nets (20Hz-20kHz context) classified as low-frequency
- Signal integrity: SPI/I2C nets classified as high-speed digital
- Importance ranking: power > clock > feedback > signal > unknown
- Fanout count correct for multi-drop nets
- Stub detection for nets with dead-end branches

---

## Success Criteria

1. CircuitTopology produced from any SchematicGraph with correct signal flow direction
2. NetClassification correctly labels POWER, GROUND, SIGNAL, CONTROL, FEEDBACK, CLOCK nets
3. Signal paths trace from input to output through op-amps, VCAs, and passives
4. Feedback loops identified in amplifier circuits
5. 20+ tests with mock schematics covering all classification rules
6. No regression in existing connectivity analysis
