# Phase 46: Component Function Recognition

**Status:** PLANNING
**Requirements:** DOMAIN-02, DOMAIN-03
**Depends on:** Phase 45 (circuit topology graph, net classification)
**Milestone:** v3.0

## Goal

Classify subcircuits into functional categories -- amplifier, filter, oscillator, power supply, etc. -- using rule-based detection on top of the Phase 45 topology graph. This moves kicad-agent from "which components are connected" to "what does this circuit block do" -- the core of domain intelligence.

## Context

Phase 45 provides the topology graph: a directed networkx DiGraph with signal flow direction, net classification, and pin roles. This plan uses that graph to identify functional subcircuits by clustering components around ICs and classifying each cluster by its component makeup and net topology.

The analog-ecosystem project has concrete subcircuits we must recognize:
- Compressor: THAT4301 VCA + NE5532 buffers + sidechain filter (RC network)
- Gain stage: NE5532 op-amp + feedback resistors + coupling capacitors
- LFO: CD4060 oscillator + RC timing network
- ADSR: RC envelope generator + comparator
- Power supply: Voltage regulators + filter capacitors + protection diodes
- EQ section: Op-amp + capacitors in feedback + inductors/resonators
- Digital control: RP2040 MCU + decoupling caps + crystal + pull-ups

Existing infrastructure to build on:
- `analysis/topology_graph.py` (Phase 45) -- CircuitTopology with directed edges, pin roles, net classification
- `analysis/net_classifier.py` (Phase 45) -- NetClassification, SignalIntegrity, NetImportance
- `ops/violation_classifier.py` -- Rule-based classification pattern

## Plans

### Plan 46-01: Subcircuit Detection (DOMAIN-02)

**Goal:** Identify functional blocks within a schematic by clustering components around ICs using the topology graph from Phase 45.

**Schema:**
```python
class SubcircuitType(str, Enum):
    PREAMP = "PREAMP"
    COMPRESSOR = "COMPRESSOR"
    EQ = "EQ"
    FILTER = "FILTER"
    VCA = "VCA"
    ENVELOPE = "ENVELOPE"
    LFO = "LFO"
    MIXER = "MIXER"
    OUTPUT_STAGE = "OUTPUT_STAGE"
    POWER_SUPPLY = "POWER_SUPPLY"
    OSCILLATOR = "OSCILLATOR"
    DIGITAL_CONTROL = "DIGITAL_CONTROL"
    ANALOG_SWITCH = "ANALOG_SWITCH"
    PROTECTION = "PROTECTION"
    UNKNOWN = "UNKNOWN"

@dataclass(frozen=True)
class Subcircuit:
    subcircuit_id: str                # "SC-001"
    components: tuple[str, ...]       # Refs: ("U1", "R1", "R2", "C1")
    nets: tuple[str, ...]             # Net names within subcircuit
    boundary_nets: tuple[str, ...]    # Nets connecting to other subcircuits
    subcircuit_type: SubcircuitType
    confidence: float                 # 0.0 - 1.0 classification confidence
    center_component: str             # Primary IC ref (e.g., "U1")
    features: dict                    # Extracted features for classification
```

**Detection algorithm:**
1. For each IC in the topology, collect all components within 1-2 hops on signal nets
2. Exclude components already assigned to another subcircuit
3. Classify by IC type + surrounding component makeup
4. Compute boundary: nets shared with other subcircuits or external connectors

**Classification rules (IC-centric, first match wins):**
- IC is THAT4301/THAT2181 + feedback RC -> COMPRESSOR or VCA
- IC is NE5532/TL072/LM358 + capacitors in feedback path -> FILTER
- IC is NE5532/TL072/LM358 + resistive feedback, no capacitors -> PREAMP or OUTPUT_STAGE
- IC is CD4060 + RC timing -> OSCILLATOR or LFO
- IC is LM7805/LM317/LM7812 + filter caps -> POWER_SUPPLY
- IC is RP2040/ATmega + crystal + decoupling -> DIGITAL_CONTROL
- IC is CD4066 + control resistors -> ANALOG_SWITCH

**Implementation:**
1. Create `src/kicad_agent/analysis/subcircuit_detector.py` -- SubcircuitDetector class
2. Create `src/kicad_agent/analysis/circuit_classifier.py` -- CircuitClassifier with rules
3. Create `tests/test_subcircuit_detection.py` -- TDD tests with mock topologies

**Tests:**
- SubcircuitDetector identifies op-amp + feedback resistors as amplifier subcircuit
- SubcircuitDetector identifies THAT4301 + sidechain RC as compressor subcircuit
- SubcircuitDetector identifies voltage regulator + filter caps as power supply
- SubcircuitDetector identifies RP2040 + crystal + decoupling as digital control
- SubcircuitDetector correctly assigns boundary nets between adjacent subcircuits
- CircuitClassifier returns confidence > 0.8 for well-known patterns
- CircuitClassifier returns SubcircuitType.UNKNOWN for unrecognized patterns
- Overlapping subcircuits are resolved by assigning each component to one subcircuit
- Passive-only groups (no IC) are classified separately or grouped with nearest IC subcircuit
- Empty topology produces empty subcircuit list

---

### Plan 46-02: Circuit Type Classifier with ML-Ready Features (DOMAIN-03)

**Goal:** Extend the classifier with feature vector extraction, confidence scoring, and preparation for future ML-based classification.

**Adds to 46-01:**
- Feature vector extraction for each subcircuit (component counts, net topology, power connections)
- Feature schema compatible with sklearn/pytorch input format
- Confidence calibration: high confidence for rule matches, low for heuristic matches
- Unknown/ambiguous handling with feature logging for future ML training data

**Feature vector schema:**
```python
@dataclass(frozen=True)
class SubcircuitFeatures:
    subcircuit_id: str
    ic_count: int
    resistor_count: int
    capacitor_count: int
    inductor_count: int
    diode_count: int
    transistor_count: int
    total_component_count: int
    has_feedback_loop: bool
    has_power_connection: bool
    feedback_capacitor_count: int      # Caps in feedback path
    feedback_resistor_count: int       # Resistors in feedback path
    input_net_count: int
    output_net_count: int
    power_net_count: int
    ground_net_count: int
    control_net_count: int
    feedback_net_count: int
    ic_lib_ids: tuple[str, ...]        # All IC lib_ids in subcircuit
    primary_ic_type: str               # "opamp", "vca", "mcu", "regulator", "switch", "oscillator", "unknown"
    max_signal_path_length: int
    net_count: int
    boundary_net_count: int
    component_density: float           # components / unique_nets ratio
```

**Tests:**
- Feature vector has correct counts for each component type
- Feature vector identifies feedback loops and power connections
- Feature vector compatible with JSON serialization for ML pipeline input
- Confidence > 0.8 for exact rule matches (THAT4301 -> COMPRESSOR)
- Confidence 0.5-0.8 for heuristic matches (unknown IC + op-amp pattern)
- Confidence < 0.5 for ambiguous patterns logged for future ML training
- Feature extraction is deterministic
- Feature extraction handles subcircuits with 0 ICs gracefully
- Batch feature extraction for all subcircuits in a topology

---

## Success Criteria

1. SubcircuitDetector identifies functional blocks in any CircuitTopology from Phase 45
2. CircuitClassifier correctly classifies: amplifier, filter, oscillator, power supply, digital control, compressor, VCA, mixer
3. Boundary nets between subcircuits correctly identified
4. Confidence scoring accurate: >0.8 for known patterns, <0.5 for unknowns
5. Feature vectors extractable and JSON-serializable for ML pipeline
6. 20+ tests with mock topologies covering all subcircuit types
7. No regression in existing topology analysis
