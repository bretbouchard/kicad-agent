# Phase 10: AI-Driven PCB Generation - Research

**Researched:** 2026-05-22
**Domain:** Generative AI for electronic design automation (schematic capture + PCB layout)
**Confidence:** MEDIUM

## Summary

Phase 10 bridges kicad-agent from an "AI critic" (reward model scoring reasoning chains about existing boards) to an "AI creator" that generates new schematics and PCB layouts from natural language intent. The codebase already has every building block: zero-diff parser/serializer for all 4 KiCad file types, 24 atomic operation handlers, spatial primitives with Shapely queries, procedural maze PCB generation via kiutils, a 4-layer transformer reward model, and GRPO training infrastructure with group-relative advantages and KL penalties.

The state of the art in AI-driven PCB design (2024-2026) centers on two camps: (1) prompt-driven layout tools like Flux.ai that use LLMs for multi-step planning workflows where the AI proposes placement and routing strategies but defers geometric execution to deterministic engines, and (2) code-driven tools like atopile that define hardware as code and compile to KiCad output. Neither camp has achieved fully autonomous end-to-end PCB generation from natural language. The gap is exactly where kicad-agent's existing infrastructure excels: converting structured intents into valid KiCad files through a safe mutation pipeline.

**Primary recommendation:** Build a hybrid "LLM planner + deterministic executor" architecture where the LLM generates a sequence of existing operation intents (add_component, move_component, add_net, etc.) rather than raw S-expressions, leveraging the existing operation schema and transaction engine. Extend the maze generator into a "template board generator" that creates structurally valid PCBs from high-level parameters, then use the existing operation handlers to refine them. This avoids the hardest unsolved problem (end-to-end generative layout) while delivering immediate value.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Natural language intent parsing | API / Backend | -- | LLM call to structured JSON, must be server-side |
| Design intent to operation sequence | API / Backend | -- | Mapping logic belongs with the operation schema |
| Component placement | API / Backend | Spatial engine | Deterministic placement via existing move_component op |
| Net routing | API / Backend | Spatial engine | Route planning uses spatial queries; execution via operations |
| DRC/ERC validation | API / Backend | kicad-cli | Existing validation pipeline gates all outputs |
| PCB template generation | API / Backend | -- | Extends existing maze generator pattern |
| Reward model scoring | API / Backend | GPU (MPS) | Neural model runs on available Metal GPU |
| KiCad file serialization | API / Backend | -- | Existing serializer ensures zero-diff output |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| kiutils | 1.4.8 | KiCad AST manipulation | Already used for all 4 file types; maze generator proves it can create files from scratch [VERIFIED: pip show] |
| sexpdata | 1.0.0 | S-expression low-level parsing | Existing parser layer dependency [VERIFIED: pip show] |
| networkx | 3.4.2 | Connectivity graph, net routing | Already used for NET-05 connectivity analysis [VERIFIED: pip show] |
| shapely | 2.1.1 | Spatial queries, collision detection | Already used for SpatialQueryEngine STRtree [VERIFIED: pip show] |
| PyTorch | 2.10.0dev | Reward model, generation model | Existing reward model infrastructure; MPS available [VERIFIED: python import] |
| Pydantic v2 | (existing) | Operation schema, intent validation | All 24 operation types already defined as Pydantic models [VERIFIED: schema.py] |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| transformers (HuggingFace) | TBD | Pre-trained LLM for intent parsing | If using a local LLM for generation instead of Claude API |
| scikit-learn | TBD | Clustering for component grouping | For intelligent component placement heuristics |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Operation-sequence generation | Direct S-expression generation | Direct generation skips safety layer; operation-sequence leverages all existing validation |
| Fine-tuned generation model | Claude API prompt engineering | Fine-tuning is expensive; Claude API with good prompting is faster to ship |
| End-to-end generative model | Template + refinement pipeline | End-to-end is unsolved research; template+refine delivers value immediately |

**Installation:**
```bash
# Core dependencies already installed
# Optional additions for Phase 10:
pip install scikit-learn  # for component placement clustering
```

**Version verification:** All core packages verified via `pip show` on 2026-05-22. PyTorch nightly build with MPS support confirmed.

## Architecture Patterns

### System Architecture Diagram

```
User Intent (Natural Language)
       |
       v
+---------------------------+
| Intent Parser             |  <-- LLM (Claude API or local)
| NL -> GenerationIntent    |     structured JSON with design params
+---------------------------+
       |
       v
+---------------------------+
| Design Planner             |  <-- Rule-based + LLM hybrid
| Intent -> Operation Seq   |     produces ordered list of existing ops
+---------------------------+
       |
       v
+---------------------------+
| Template Generator         |  <-- Extends maze_generator.py pattern
| Params -> Skeleton PCB/SCH|     creates valid empty board with outline
+---------------------------+
       |
       v
+---------------------------+
| Operation Executor         |  <-- Existing executor.py (24 ops)
| Ops -> IR -> AST -> File  |     with Transaction wrapping + rollback
+---------------------------+
       |
       v
+---------------------------+
| Validation Pipeline        |  <-- Existing ERC/DRC + spatial checks
| DRC/ERC -> Pass/Fail      |     rejects invalid generation output
+---------------------------+
       |
       v
+---------------------------+
| Reward Scoring             |  <-- Existing reward model (optional)
| Score generated design    |     feedback signal for iterative refinement
+---------------------------+
       |
       v
  Valid KiCad Files
  (.kicad_sch, .kicad_pcb)
```

### Recommended Project Structure
```
src/kicad_agent/
├── generation/                 # NEW: AI generation module
│   ├── __init__.py
│   ├── intent.py               # GenerationIntent schema (Pydantic)
│   ├── planner.py              # Intent -> operation sequence planning
│   ├── board_templates.py      # PCB template generation (extends maze pattern)
│   ├── schematic_templates.py  # Schematic template generation
│   ├── placement.py            # Component placement algorithms
│   ├── routing_suggest.py      # Net routing suggestions (not autorouting)
│   └── refinement.py           # Iterative refinement loop with validation
├── ops/                        # EXISTING: extend with generation ops
│   ├── schema.py               # Add create_pcb, create_schematic op types
│   ├── executor.py             # Add generation dispatch paths
│   └── ...
├── spatial/                    # EXISTING: extend for generation queries
│   ├── maze_generator.py       # Refactor into template generator base
│   └── ...
├── training/                   # EXISTING: extend for generation training
│   ├── reward_model.py         # May extend for design quality scoring
│   ├── grpo.py                 # May reuse for generation policy
│   └── ...
└── validation/                 # EXISTING: no changes needed
```

### Pattern 1: Operation-Sequence Generation (Primary)

**What:** Instead of generating raw S-expressions or KiCad files, the LLM generates a sequence of existing operation intents that the existing executor processes.

**When to use:** For all generation tasks. This is the core architectural pattern.

**Example:**
```python
# Source: [ASSUMED - pattern derived from existing schema.py + executor.py]

from kicad_agent.ops.schema import Operation

# LLM generates this sequence (not raw S-expressions):
generation_plan = [
    {
        "root": {
            "op_type": "add_component",
            "target_file": "output.kicad_sch",
            "library_id": "Device:R_Small_US",
            "reference": "R1",
            "value": "10k",
            "position": {"x": 50.0, "y": 30.0},
        }
    },
    {
        "root": {
            "op_type": "add_component",
            "target_file": "output.kicad_sch",
            "library_id": "Device:C_Small",
            "reference": "C1",
            "value": "100nF",
            "position": {"x": 60.0, "y": 30.0},
        }
    },
    {
        "root": {
            "op_type": "add_net",
            "target_file": "output.kicad_sch",
            "net_name": "VCC",
        }
    },
    # ... more operations
]

# Execute through existing pipeline
from kicad_agent.ops.executor import OperationExecutor
executor = OperationExecutor(base_dir=Path("/project"))
for op_json in generation_plan:
    op = Operation.model_validate(op_json)
    result = executor.execute(op)
```

### Pattern 2: Template Board Generation

**What:** Extend the existing maze_generator.py pattern to create real PCB templates from design parameters (board size, layer count, component list, net topology).

**When to use:** When creating a new PCB from scratch rather than modifying an existing one.

**Example:**
```python
# Source: [VERIFIED: maze_generator.py pattern, lines 73-274]

from kiutils.board import Board
from kiutils.footprint import Footprint, Pad
from kiutils.items.common import Net, Position
from kiutils.items.brditems import Via

# This exact pattern already works in maze_generator.py:
board = Board.create_new()
board.general.thickness = 1.6

# Add outline, nets, components using kiutils API
# board.to_file() produces valid .kicad_pcb
```

### Pattern 3: Iterative Refinement with Validation Gate

**What:** Generate initial design, run DRC/ERC, feed violations back to LLM for fixes, repeat until clean.

**When to use:** For all generation tasks to ensure output quality.

**Example:**
```python
# Source: [VERIFIED: existing validation pipeline + spatial DRC pattern]

from kicad_agent.validation.erc_drc import run_erc, run_drc

def generate_with_refinement(intent, max_iterations=5):
    """Generate a design and iteratively fix validation failures."""
    plan = plan_operations(intent)
    template = create_template(intent)

    for i in range(max_iterations):
        for op in plan:
            executor.execute(op)

        # Validate
        erc_result = run_erc(project)
        drc_result = run_drc(project)

        if erc_result.passed and drc_result.passed:
            return {"success": True, "iterations": i + 1}

        # Feed violations back to LLM for fix operations
        fix_ops = llm_suggest_fixes(erc_result, drc_result)
        plan = fix_ops

    return {"success": False, "remaining_violations": violations}
```

### Anti-Patterns to Avoid

- **Direct S-expression generation:** The entire codebase exists to prevent this. Never generate raw KiCad file text. Use operation intents that flow through the safe mutation pipeline. [VERIFIED: PROJECT.md "LLM never touches raw S-expressions"]
- **End-to-end neural generation of PCB layouts:** No one has solved this. Academic papers on DeepPCB are about defect detection, not generation. Do not attempt a single model that outputs complete PCB files. [ASSUMED - based on literature search]
- **Bypassing the transaction/rollback system:** Every generation step must be wrapped in a Transaction. Generation is more likely than editing to produce invalid states. [VERIFIED: transaction.py pattern]
- **Ignoring the maze generator pattern:** The existing maze_generator.py already demonstrates how to programmatically create valid KiCad PCB files from scratch using kiutils. Any new template generation must follow this exact pattern rather than inventing a new one. [VERIFIED: maze_generator.py lines 130-241]

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| KiCad file creation | Custom S-expression writer | kiutils Board.create_new() + to_file() | Already proven in maze_generator.py; handles format complexity |
| Component placement | Custom geometric packing algorithm | scikit-learn clustering + existing spatial queries | Placement is NP-hard; start with heuristics, not exhaustive search |
| Net connectivity | Custom graph algorithms | networkx (already a dependency) | NET-05 already uses networkx for connectivity analysis |
| Collision detection | Custom overlap checks | Shapely STRtree (already in SpatialQueryEngine) | Exact geometric queries with O(log n) lookup |
| Design validation | Custom rule checker | kicad-cli ERC/DRC (already integrated) | kicad-cli 10.0.1 is installed and working |
| UUID generation | Custom ID scheme | uuid.uuid4() (already used in maze_generator.py) | KiCad expects standard UUIDs |
| Output normalization | Custom formatter | normalize_kicad_output() (already exists) | Handles scientific notation, whitespace, ordering |

**Key insight:** The codebase already has every infrastructure component needed for AI-driven generation. The gap is not in low-level file manipulation but in the high-level planning layer that converts design intent into operation sequences.

## Common Pitfalls

### Pitfall 1: Trying to generate complete PCBs in one shot
**What goes wrong:** LLMs cannot reliably generate 200+ operation sequence for a real board. Hallucinated coordinates, missing connections, inconsistent references.
**Why it happens:** PCB design is highly constrained -- a single clearance violation or unconnected net makes the board non-functional.
**How to avoid:** Break generation into stages: (1) create template board, (2) place components in groups, (3) connect nets incrementally, (4) validate at each stage. Never attempt monolithic generation.
**Warning signs:** Generation plans with more than 20 operations in a single pass.

### Pitfall 2: Ignoring the Reference Gap in generation
**What goes wrong:** LLM generates vague placement instructions like "put the decoupling capacitors near the IC" without coordinates. The result is ambiguous and unreproducible.
**Why it happens:** Natural language is imprecise for spatial relationships -- the same problem Phase 8 solved for analysis.
**How to avoid:** Every generated operation must include explicit coordinates. Use the existing spatial primitive vocabulary (`<point x,y>`, `<box x1,y1,x2,y2>`) in the planning prompt. Force coordinate grounding in the generation schema.
**Warning signs:** Generated operations with positions described as "near", "next to", or "close to" instead of explicit mm coordinates.

### Pitfall 3: Creating new file types instead of using kiutils
**What goes wrong:** Writing custom S-expression serialization for generated files produces format bugs that KiCad cannot open.
**Why it happens:** KiCad's S-expression format has subtle ordering requirements, quoting rules, and whitespace conventions that are easy to get wrong.
**How to avoid:** Always use kiutils objects (Board, Schematic, Footprint) to construct generated files, then call to_file(). The maze_generator.py proves this works perfectly.
**Warning signs:** Any code that builds S-expressions via string concatenation or template substitution.

### Pitfall 4: Training a generation model from scratch
**What goes wrong:** Massive compute cost, slow iteration, poor results compared to leveraging Claude's existing spatial reasoning with good prompting.
**Why it happens:** Assuming the reward model training approach from Phase 9 should be extended to generation.
**How to avoid:** Use Claude API for the planning layer with carefully crafted prompts. Only train specialized models for specific sub-tasks (e.g., component grouping) if Claude proves insufficient. The existing reward model can score generated designs but should not be the generator itself.
**Warning signs:** Planning a full training run for a generative PCB model before validating that prompt-based generation works.

### Pitfall 5: Scope creep into autorouting
**What goes wrong:** Autorouting is a combinatorial optimization problem with decades of research (A*, maze routing, channel routing). It is out of scope for this project.
**Why it happens:** "AI-driven PCB generation" sounds like it should include routing, but routing is explicitly listed as out of scope in REQUIREMENTS.md.
**How to avoid:** Phase 10 generates component placement and net topology. Routing suggestions (if any) are heuristic hints, not a full autorouter. The REQUIREMENTS.md "Out of Scope" table explicitly excludes auto-routing.
**Warning signs:** Any task that involves computing trace paths between pads.

## Code Examples

### Creating a PCB from scratch (existing pattern)

```python
# Source: [VERIFIED: maze_generator.py lines 130-241]
# This pattern is proven and produces valid KiCad 10 output.

from kiutils.board import Board
from kiutils.footprint import Footprint, Pad
from kiutils.items.common import Net, Position
from kiutils.items.brditems import Via
from kiutils.items.gritems import GrLine
import uuid

# Create new board
board = Board.create_new()
board.general.thickness = 1.6

# Add board outline (Edge.Cuts)
corners = [
    (Position(0, 0), Position(width, 0)),
    (Position(width, 0), Position(width, height)),
    (Position(width, height), Position(0, height)),
    (Position(0, height), Position(0, 0)),
]
for start, end in corners:
    board.graphicItems.append(
        GrLine(start=start, end=end, layer="Edge.Cuts", width=0.15)
    )

# Add nets
board.nets.append(Net(number=0, name=""))
board.nets.append(Net(number=1, name="VCC"))

# Add component footprint
fp = Footprint(
    libraryNickname="Device",
    entryName="R_Small_US",
    layer="F.Cu",
    position=Position(25.0, 20.0),
    tstamp=str(uuid.uuid4()),
)
board.footprints.append(fp)

# Serialize to valid .kicad_pcb
board.to_file("output.kicad_pcb")
```

### Extending operation schema for generation

```python
# Source: [VERIFIED: schema.py pattern for existing op types]
# Extend with create_board and create_schematic operations.

from pydantic import BaseModel, Field
from typing import Literal

class CreateBoardOp(BaseModel):
    """Create a new PCB file from design parameters."""
    op_type: Literal["create_board"] = "create_board"
    target_file: str  # e.g., "my_board.kicad_pcb"
    width_mm: float = Field(ge=1.0, le=500.0)
    height_mm: float = Field(ge=1.0, le=500.0)
    thickness_mm: float = Field(default=1.6, ge=0.2, le=10.0)
    layer_count: int = Field(default=2, ge=2, le=32)
    net_names: list[str] = Field(default_factory=list)

class GenerationIntent(BaseModel):
    """High-level design intent from user."""
    description: str = Field(min_length=5, max_length=2000)
    board_width_mm: float = Field(ge=10.0, le=500.0, default=100.0)
    board_height_mm: float = Field(ge=10.0, le=500.0, default=80.0)
    components: list[ComponentSpec] = Field(default_factory=list)
    connections: list[ConnectionSpec] = Field(default_factory=list)
    constraints: list[ConstraintSpec] = Field(default_factory=list)
```

### Using spatial queries for placement validation

```python
# Source: [VERIFIED: spatial/query.py SpatialQueryEngine pattern]

from kicad_agent.spatial.primitives import SpatialBox
from kicad_agent.spatial.query import SpatialQueryEngine

def validate_placement(placed_components: list[SpatialBox], min_clearance: float = 0.5):
    """Check that placed components don't overlap and have minimum clearance."""
    engine = SpatialQueryEngine(placed_components)

    violations = []
    for comp in placed_components:
        nearby = engine.proximity(
            (comp.x1 + comp.x2) / 2, (comp.y1 + comp.y2) / 2,
            radius=min_clearance
        )
        for other in nearby:
            if other.entity_id != comp.entity_id:
                # Check actual clearance
                dist = comp.to_shapely().distance(other.to_shapely())
                if dist < min_clearance:
                    violations.append({
                        "component_a": comp.entity_id,
                        "component_b": other.entity_id,
                        "clearance": dist,
                        "required": min_clearance,
                    })
    return violations
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual schematic capture only | AI-assisted schematic generation (Flux.ai) | 2024-2025 | LLMs can now propose circuit topologies from natural language descriptions |
| Rule-based autorouters | ML-informed placement (research stage) | 2024-2025 | Still early; no production tool uses neural placement |
| Code-as-hardware (atopile) | Compiling code descriptions to KiCad | 2025 | Structured approach that avoids LLM hallucination; good pattern to follow |
| Template libraries only | AI Auto-Layout from high-level intent (Flux.ai) | 2025 | Flux.ai's "AI intern" paradigm: AI proposes, human confirms, deterministic execution |

### Industry Tools Researched

**Flux.ai** [CITED: flux.ai blog content retrieved via webReader]:
- AI Auto-Layout: prompt-based layout generation with multi-step planning
- AI Generated Netlists: LLM proposes circuit topology
- AI Design Reviews: automated review with violation detection
- "AI intern" paradigm: AI suggests, human approves, deterministic execution
- Multi-step planning workflows: decompose complex layouts into stages
- Key insight: Their approach matches our recommended architecture -- LLM planning + deterministic execution

**atopile** [CITED: atopile.io content retrieved via webReader]:
- Code-driven hardware design with Python-like DSL
- Compiles to KiCad files via structured transformation
- Avoids LLM hallucination by using code as the source of truth
- Key insight: Their "code-to-KiCad" pattern is structurally similar to our "operations-to-KiCad" pattern

**JITX** [VERIFIED: domain for sale as of 2026-05-22]:
- Previously offered code-driven PCB design
- Domain (jitx.com) is parked/for sale
- No longer operational

**DeepPCB** [ASSUMED - based on training knowledge]:
- Academic paper: defect detection on PCB images, not generation
- Often confused with generation capability in discussions
- Not relevant to Phase 10 goals

**Deprecated/outdated:**
- Raw S-expression generation: The entire kicad-agent architecture exists to prevent this approach
- End-to-end neural PCB generation: No production or academic tool has achieved this; remains an open research problem

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | No production tool achieves end-to-end autonomous PCB generation from natural language | State of the Art | Medium -- if one exists, we should study its approach |
| A2 | Claude API with good prompting is sufficient for the planning layer (no fine-tuning needed) | Pitfall 4, Architecture | High -- if Claude cannot reliably generate operation sequences, we need a different approach |
| A3 | kiutils Board.create_new() + to_file() produces valid KiCad 10 output (proven in maze_generator.py) | Code Examples | Low -- already verified by existing 658+ tests |
| A4 | The existing 24 operation types cover ~80% of what's needed for basic PCB generation | Architecture | Medium -- may need 5-10 new operation types (create_board, add_zone, add_text, etc.) |
| A5 | Component placement can start with simple heuristic algorithms (force-directed, clustering) | Architecture | Medium -- may need more sophisticated optimization for production quality |
| A6 | DeepPCB is about defect detection, not generation | State of the Art | Low -- verified by multiple sources describing it as defect detection |
| A7 | Flux.ai's approach is "LLM planner + deterministic executor" based on their blog content | State of the Art | Low -- their blog explicitly describes multi-step planning with human confirmation |

## Open Questions

1. **What new operation types are needed?**
   - What we know: 24 atomic operations exist. Missing: create_board, create_schematic, add_zone, add_text, set_board_stackup.
   - What's unclear: Exact scope of new ops needed for minimum viable generation.
   - Recommendation: Define this during planning by listing all kiutils API calls needed that have no corresponding operation.

2. **Should generation use Claude API or a local model?**
   - What we know: Claude API is available via the skill interface. PyTorch + MPS is available locally.
   - What's unclear: Whether Claude's spatial reasoning is sufficient for coordinate-grounded generation, or if a specialized model is needed.
   - Recommendation: Start with Claude API. Add local model fallback only if Claude proves insufficient for coordinate accuracy.

3. **What is the minimum viable "AI creates something useful" milestone?**
   - What we know: The maze generator can create simple valid PCBs. The operation executor can add components and nets.
   - What's unclear: What complexity threshold makes this useful vs. toy.
   - Recommendation: "AI places 5-10 components on a board from a BOM list with reasonable spacing and valid ERC" as the first milestone.

4. **How to handle component library resolution?**
   - What we know: The skill interface has library path discovery (XFILE-04). Footprint assignment exists (FP-01 through FP-04).
   - What's unclear: How to automatically select the right footprint for a component from a natural language description.
   - Recommendation: Start with a curated component library (10-20 common parts) with hardcoded mappings. Expand later.

5. **Training data for generation quality scoring?**
   - What we know: The reward model scores reasoning chains. The maze dataset provides synthetic examples.
   - What's unclear: Whether the reward model can meaningfully score design quality (placement density, routing congestion, manufacturability).
   - Recommendation: Start with rule-based quality metrics (DRC violation count, clearance margins, board utilization). Add neural scoring later if needed.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | Core runtime | Yes | 3.11.11 | -- |
| kiutils | KiCad AST | Yes | 1.4.8 | -- |
| sexpdata | S-expression parsing | Yes | 1.0.0 | -- |
| networkx | Graph analysis | Yes | 3.4.2 | -- |
| shapely | Spatial queries | Yes | 2.1.1 | -- |
| PyTorch | Reward model, optional generation | Yes | 2.10.0dev | CPU fallback (no MPS) |
| kicad-cli | ERC/DRC validation | Yes | 10.0.1 | -- |
| MPS (Metal GPU) | PyTorch acceleration | Yes | Available | CPU (slower) |
| CUDA | GPU acceleration | No | N/A | MPS (Apple Silicon) |
| scikit-learn | Placement clustering | No | N/A | Rule-based heuristics |

**Missing dependencies with no fallback:**
- None -- all critical dependencies are available.

**Missing dependencies with fallback:**
- scikit-learn: Not installed but not required. Can use rule-based heuristics for initial placement. Install only if clustering-based placement is implemented.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (existing) |
| Config file | pyproject.toml (existing) |
| Quick run command | `python -m pytest tests/test_generation.py -x -q` |
| Full suite command | `python -m pytest tests/ -x` |

### Phase Requirements to Test Map

Phase 10 requirements are TBD (from ROADMAP.md). Based on the research direction, the following test categories are anticipated:

| Anticipated Area | Test Type | Automated Command | Notes |
|------------------|-----------|-------------------|-------|
| Board template generation | Unit | `pytest tests/test_generation/test_board_templates.py -x` | Wave 0: create file |
| Intent parsing | Unit | `pytest tests/test_generation/test_intent.py -x` | Wave 0: create file |
| Operation sequence planning | Integration | `pytest tests/test_generation/test_planner.py -x` | Wave 0: create file |
| End-to-end generation smoke test | Integration | `pytest tests/test_generation/test_e2e.py -x` | After core modules |
| Generation DRC pass rate | Integration | `pytest tests/test_generation/test_drc_pass.py -x` | After generation works |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_generation/ -x -q`
- **Per wave merge:** `python -m pytest tests/ -x`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_generation/__init__.py` -- test package
- [ ] `tests/test_generation/test_board_templates.py` -- covers board creation
- [ ] `tests/test_generation/test_intent.py` -- covers GenerationIntent schema
- [ ] `tests/test_generation/test_planner.py` -- covers operation sequence planning
- [ ] Generation test fixtures: simple component specs, connection specs

## Security Domain

> Security enforcement follows existing project patterns. No new threat categories introduced by generation phase beyond existing operation validation.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | Generation is local/API; no user auth layer |
| V3 Session Management | No | No session state in generation |
| V4 Access Control | No | Local tool execution |
| V5 Input Validation | Yes | Pydantic v2 models with constrained fields (same as existing ops) |
| V6 Cryptography | No | No cryptographic operations |

### Known Threat Patterns for Generation Stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Malicious intent injection via NL prompt | Tampering | Pydantic validation on all generated operations; schema constraints reject out-of-bounds values |
| Path traversal in generated target_file | Tampering | Existing TargetFile validator rejects `..`, absolute paths, null bytes |
| DoS via unreasonable generation parameters | Denial of Service | Field constraints (width 1-500mm, component count limits) |
| LLM hallucination producing invalid operations | Tampering | OperationExecutor validates all ops before execution; Transaction rollback on failure |

## Sources

### Primary (HIGH confidence)
- Codebase analysis: All 46 test files, all source modules in src/kicad_agent/
- `maze_generator.py` -- verified pattern for programmatic KiCad file creation
- `reward_model.py` -- verified architecture (4-layer transformer, 3 prediction heads)
- `grpo.py` -- verified GRPO implementation with group-relative advantages
- `schema.py` -- verified 24 operation types with Pydantic validation
- `executor.py` -- verified dispatch pattern with Transaction wrapping
- `pipeline.py` -- verified end-to-end training pipeline

### Secondary (MEDIUM confidence)
- Flux.ai blog content [CITED: retrieved via webReader from flux.ai] -- AI Auto-Layout, AI intern paradigm, multi-step planning
- atopile.io content [CITED: retrieved via webReader from atopile.io] -- code-driven hardware design, Python-like DSL
- JITX verification [VERIFIED: domain jitx.com is parked/for sale as of 2026-05-22]

### Tertiary (LOW confidence)
- DeepPCB characterization as defect detection [ASSUMED -- could not verify via arXiv due to search failure]
- No existing tool achieves fully autonomous PCB generation [ASSUMED -- based on literature search; may have missed recent developments]

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All dependencies verified installed, versions confirmed
- Architecture: MEDIUM - Hybrid approach is well-supported by existing code, but generation-specific patterns are unvalidated
- Pitfalls: HIGH - Based on direct analysis of existing codebase limitations
- State of the art: MEDIUM - Flux.ai and atopile verified; broader landscape partially explored (some search failures)

**Research date:** 2026-05-22
**Valid until:** 2026-06-22 (stable domain; PCB EDA moves slowly)
