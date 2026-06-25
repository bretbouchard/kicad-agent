# Roadmap: kicad-agent

## Overview

Build an AI-safe KiCad structural editing tool across multiple milestones. First achieve zero-diff round-trip parsing for all file types, define the operation schema that insulates the LLM from raw S-expressions, install validation gates, build editing operations from simple to complex, add visual primitives and GRPO training for spatial reasoning, AI-driven generative capabilities, LTspice integration, ADI footprint library access, real-world training data, bidirectional LTspice bridge, AI generation wiring, component placement AI, package/distribution, CI/CD, interactive routing, SFT/GRPO fine-tuning, agent integration, schematic repair, council audit remediation, fill the remaining operation gaps for complete CRUD coverage, and finally hybrid routing intelligence with Gemma 4 12B encoder-free vision for post-routing gap filling.

## Milestones

- **v1.0 Foundation** - Phases 1-7 (shipped 2026-05-18)
- **v1.1 Ecosystem** - Phases 8-12 (shipped 2026-05-23)
- **v2.0 Production AI** - Phases 13-22 (shipped 2026-05-28)
- **v2.1 Audit** - Phases 23-24 (shipped 2026-05-29)
- **v2.2 Complete-Ops** - Phases 25-29 (shipped 2026-05-29)
- **v2.3 MCP-Server** - Phases 30-31 (shipped 2026-05-29)
- **v2.4 Schematic Intelligence** - Phases 38-40 (shipped 2026-05-31)
- **v2.5 Benchmark Suite** - Phases 41-44 (shipped 2026-05-31)
- **v3.0 Full-Stack EDA** - Phases 50-54 (shipped 2026-06-01)
- **v3.1 Council Remediation** - Phases 60-76 (shipped 2026-06-06)
- **v3.2 Gap Analysis** - Phases 79 (shipped 2026-06-20)
- **v4.0 Hybrid Routing Intelligence** - Phases 80-84 (shipped 2026-06-20)
- **v4.1 Stage-Safe PCB Flow** - Phases 85-94 (shipped 2026-06-20)
- **v5.0 Vast.ai Training & External Storage** - Phases 96-97 (shipped 2026-06-20)

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

<details>
<summary>v1.0 Foundation (Phases 1-7) - SHIPPED 2026-05-18</summary>

- [x] **Phase 1: Foundation -- Parse, Serialize, Round-trip** - Parse all 4 KiCad file types with zero-diff round-trip fidelity
- [x] **Phase 2: Operation Schema and IR Layer** - Define the JSON intent contract and IR dataclasses that insulates the LLM from raw S-expressions
- [x] **Phase 3: Validation Pipeline** - ERC/DRC gates, structural checks, and error recovery before any mutation
- [x] **Phase 4: Component Operations** - Add, remove, duplicate, move, and modify components with transaction safety
- [x] **Phase 5: Net, Reference, and Footprint Operations** - Net CRUD, bus operations, reference management, footprint assignment
- [x] **Phase 6: Cross-File Operations and Analysis** - Schematic-to-PCB consistency, library propagation, structural diffs, connectivity analysis
- [x] **Phase 7: GSD Skill Integration** - Claude skill manifest, handler, CLI wrapper, and project context renderer

</details>

<details>
<summary>v1.1 Ecosystem (Phases 8-12) - SHIPPED 2026-05-23</summary>

- [x] **Phase 8: Visual Primitives for PCB Spatial Reasoning** - AI that points while it reasons -- coordinate-grounded DRC, routing guidance, and spatial analysis
- [x] **Phase 9: GRPO Spatial Reasoning Training** - DeepSeek-style RL training with coordinate-grounded reward signals on synthetic PCB maze data
- [x] **Phase 10: AI-Driven PCB Generation** - Generative AI that creates schematics and PCB layouts from natural language intent
- [x] **Phase 11: LTspice Integration** - Parse LTspice .asc schematics, extract components/nets/simulation commands
- [x] **Phase 12: ADI Footprint Library** - On-demand ADI footprint/symbol download, library management, manufacturer part integration

</details>

<details>
<summary>v2.0 Production AI (Phases 13-22) - SHIPPED 2026-05-28</summary>

- [x] **Phase 13: Real-World PCB Training Pipeline** - GitHub crawler for KiCad repos, structured graph datasets
- [x] **Phase 14: Bidirectional KiCad-LTspice** - KiCad schematic to .asc writer, close the simulation loop
- [x] **Phase 15: AI Generation Wiring** - LLM-driven component suggestion, design critique, natural language to operations
- [x] **Phase 16: Component Placement AI** - Predict optimal component placement from schematic netlist
- [x] **Phase 17: Package & Distribution** - PyPI publish, CLI entry point, pip install kicad-agent
- [x] **Phase 18: CI/CD Pipeline** - GitHub Actions for test suite, linting, coverage gate, release automation
- [x] **Phase 19: Interactive Routing Suggestions** - Spatial primitives + training data for trace routing on real boards
- [x] **Phase 20: SFT Data Preparation + Training Infrastructure** - ChatML conversion, quality filtering, SFT baseline on Qwen2.5-1.5B
- [x] **Phase 21: GRPO RL Fine-Tuning** - GRPO fine-tuning with reward model as critic
- [x] **Phase 22: Agent Integration + End-to-End Evaluation** - Wire fine-tuned model into kicad-agent as reasoning engine

</details>

<details>
<summary>v2.1 Audit (Phases 23-24) - SHIPPED 2026-05-29</summary>

- [x] **Phase 23: Schematic Repair Operations** - 8 schematic manipulation operations from real backplane repair sessions
- [x] **Phase 24: Council Audit Remediation & Security Hardening** - Fix all 56 findings from Council of Ricks all-hands audit

</details>

### v2.2 Complete-Ops (SHIPPED 2026-05-29)

**Milestone Goal:** Fill the five operation gaps so kicad-agent handles real-world KiCad projects with hierarchical designs and full CRUD capabilities. Zero new dependencies. **1673 tests, 57 operation types, 14 schema sub-modules.**

- [x] **Phase 25: Remove Operations** - remove_wire, remove_label, remove_junction, remove_no_connect with adjacency checks and list-filter pattern
- [x] **Phase 26: Connectivity Query** - query_connectivity exposing existing NetGraph through read-only handler with 5 query types
- [x] **Phase 27: Footprint Creation** - create_footprint with PadSpec schema, UUID-preserving serialization, courtyard generation
- [x] **Phase 28: Hierarchical Sheet Operations** - add_sheet, add_sheet_pin, navigate_hierarchy with UUID path management and nested hierarchy
- [x] **Phase 29: Cross-File Atomic Operations** - propagate_symbol_change via AtomicOperation, new cross-file executor dispatch path

### v2.3 MCP Server

**Milestone Goal:** Expose all 57 kicad-agent operations as MCP tools so any AI agent (Claude, Cursor, etc.) can invoke KiCad file edits directly. Zero new dependencies. ~250 lines new code.

- [x] **Phase 30: MCP Operations Server** - Dynamic tool generation from Pydantic schemas, stdio transport, meta-tools for schema discovery and project context (shipped 2026-06-06)
- [x] **Phase 31: Validation Integration** - erc_check and drc_check convenience MCP tools wrapping kicad-cli (shipped 2026-06-06)

## Phase Details

<details>
<summary>v1.0 Foundation Phase Details</summary>

### Phase 1: Foundation -- Parse, Serialize, Round-trip
**Goal**: All four KiCad file types parse into structured AST and serialize back to byte-identical or semantically equivalent output
**Depends on**: Nothing (first phase)
**Requirements**: FND-01, FND-02, FND-03, FND-04, FND-05, FND-06, VAL-07
**Success Criteria** (what must be TRUE):
  1. A .kicad_sch file parses and serializes to zero-diff output
  2. A .kicad_pcb file parses and serializes to zero-diff output
  3. A .kicad_sym file parses and serializes to zero-diff output
  4. A .kicad_mod file parses and serializes to zero-diff output
  5. All UUIDs are preserved without dangling references through parse/serialize cycles
  6. The regression test suite passes for all four file types with real KiCad 10 sample files
**Plans**: 3 plans (3/3 complete)

Plans:
- [x] 01-01-PLAN.md -- Parser layer for all 4 KiCad file types with raw content preservation
- [x] 01-02-PLAN.md -- UUID extraction/re-injection, serializers, and round-trip stability validator
- [x] 01-03-PLAN.md -- Comprehensive round-trip fidelity regression test suite with fixture files

### Phase 2: Operation Schema and IR Layer
**Goal**: The LLM has a well-defined JSON contract for expressing edit intents, and the tool layer can translate those intents into IR mutations
**Depends on**: Phase 1
**Requirements**: OPS-01, OPS-02, OPS-03, FND-07, FND-08
**Success Criteria** (what must be TRUE):
  1. A JSON operation intent validates against the Pydantic schema (rejects invalid intents, accepts valid ones)
  2. A validated intent translates to an IR mutation on a parsed file
  3. The mutated IR serializes to a deterministic, SCM-friendly output
  4. A failed mutation rolls back to the pre-mutation state (transaction with rollback)
  5. The JSON Schema is exportable for LLM consumption
**Plans**: 3 plans (3/3 complete)

Plans:
- [x] 02-01-PLAN.md -- Pydantic operation schema with discriminated union and JSON Schema export
- [x] 02-02-PLAN.md -- IR base class and four file-type IR wrappers with mutation tracking
- [x] 02-03-PLAN.md -- Transaction engine with rollback and KiCad output normalizer

### Phase 3: Validation Pipeline
**Goal**: Every mutation passes through ERC, DRC, and structural validation gates before being committed to disk
**Depends on**: Phase 2
**Requirements**: VAL-01, VAL-02, VAL-03, VAL-05, VAL-06
**Success Criteria** (what must be TRUE):
  1. An ERC check via kicad-cli returns structured pass/fail/warning results
  2. A DRC check via kicad-cli returns structured pass/fail/warning results
  3. A pre-mutation structural validation catches invalid operations before execution
  4. A validation failure triggers automatic rollback to the last valid state
  5. Net consistency between schematic and PCB can be verified programmatically
**Plans**: 3 plans (3/3 complete)

Plans:
- [x] 03-01-PLAN.md -- kicad-cli ERC/DRC wrappers with structured result parsing
- [x] 03-02-PLAN.md -- Pre-mutation structural validator and UUID uniqueness checker
- [x] 03-03-PLAN.md -- Error recovery pipeline with automatic rollback on validation failure

### Phase 4: Component Operations
**Goal**: Users can add, remove, duplicate, move, and modify components in a schematic with full validation safety
**Depends on**: Phase 3
**Requirements**: COMP-01, COMP-02, COMP-03, COMP-04, COMP-05, COMP-06
**Success Criteria** (what must be TRUE):
  1. A new component is added with correct symbol reference, properties, and valid UUID
  2. A component is removed with net stubs cleaned up (no dangling wires)
  3. A component or section is duplicated with fresh UUIDs and incremented references
  4. Components are replicated in linear, circular, and matrix array patterns
  5. A component is moved to specified coordinates with correct precision
  6. Component properties are modified and the file passes ERC
**Plans**: 3 plans (3/3 complete)

Plans:
- [x] 04-01-PLAN.md -- Operation executor, add_component and remove_component handlers
- [x] 04-02-PLAN.md -- Duplicate and array replicate handlers with linear/circular/matrix patterns
- [x] 04-03-PLAN.md -- Move/reposition and property modification handlers

### Phase 5: Net, Reference, and Footprint Operations
**Goal**: Users can manage nets, buses, references, and footprints across schematic and PCB
**Depends on**: Phase 4
**Requirements**: NET-01, NET-02, NET-03, NET-04, NET-05, REF-01, REF-02, REF-03, REF-04, FP-01, FP-02, FP-03, FP-04
**Success Criteria** (what must be TRUE):
  1. A net is added with a named or auto-generated name and connects to specified pins
  2. A net is removed with all pins disconnected and stubs cleaned up
  3. A net is renamed and the change propagates to all connected pins
  4. References are renumbered with configurable prefix and sequencing
  5. A footprint is assigned with library nickname resolution and pin mapping verification
  6. Net connectivity graph is analyzable via networkx
**Plans**: 4 plans (4/4 complete)

Plans:
- [x] 05-01-PLAN.md -- Net CRUD and bus operations
- [x] 05-02-PLAN.md -- Reference management (renumber, validate, annotate, cross-reference)
- [x] 05-03-PLAN.md -- Footprint management (assign, swap, validate, pin mapping)
- [x] 05-04-PLAN.md -- Net connectivity graph analysis via networkx

### Phase 6: Cross-File Operations and Analysis
**Goal**: Users can perform atomic operations across schematic and PCB files, propagate library changes, and analyze diffs and connectivity
**Depends on**: Phase 5
**Requirements**: XFILE-01, XFILE-02, XFILE-03, XFILE-04, VAL-04
**Success Criteria** (what must be TRUE):
  1. An atomic operation maintains consistency between schematic and PCB
  2. A symbol library reference update propagates to all schematic instances
  3. A footprint library reference update propagates to all components
  4. Project context is auto-detected from any KiCad file path
  5. A structural diff shows syntax-aware, semantically meaningful differences
**Plans**: 4 plans (4/4 complete)

Plans:
- [x] 06-01-PLAN.md -- Cross-file atomic operations
- [x] 06-02-PLAN.md -- Library reference propagation
- [x] 06-03-PLAN.md -- Project context detection and auto-discovery
- [x] 06-04-PLAN.md -- Structural diff generation with difftastic integration

### Phase 7: GSD Skill Integration
**Goal**: The kicad-agent is invokable from any KiCad project via the GSD Skill interface and from the terminal via CLI
**Depends on**: Phase 6
**Requirements**: SKILL-01, SKILL-02, SKILL-03, SKILL-04
**Success Criteria** (what must be TRUE):
  1. A GSD Skill manifest declares all kicad-agent capabilities
  2. An operation request from Claude routes through the skill handler to the Python backend
  3. The CLI wrapper runs any operation directly from the terminal
  4. A project context summary is renderable for any KiCad project directory
**Plans**: 4 plans (4/4 complete)

Plans:
- [x] 07-01-PLAN.md -- GSD Skill manifest and prompt template
- [x] 07-02-PLAN.md -- Skill handler routing and result rendering
- [x] 07-03-PLAN.md -- CLI wrapper for direct terminal usage
- [x] 07-04-PLAN.md -- Project context renderer

</details>

<details>
<summary>v1.1 Ecosystem Phase Details</summary>

### Phase 8: Visual Primitives for PCB Spatial Reasoning
**Goal**: AI reasons about PCB layouts using coordinate-grounded visual primitives -- points for pins/vias, bounding boxes for components, paths for traces, regions for net classes
**Depends on**: Phase 7
**Requirements**: VP-01, VP-02, VP-03, VP-04, VP-05, VP-06, VP-07, VP-08
**Success Criteria** (what must be TRUE):
  1. A PCB layer renders to a rasterized image with a mm-coordinate grid overlay
  2. Spatial primitives are extractable from any parsed KiCad file
  3. A procedural maze-routing generator creates synthetic PCB puzzles
  4. DRC violations produce spatially-grounded reports with coordinates
  5. Spatial queries return results: "find traces within 2mm of point (10, 15)"
  6. Rick agents produce coordinate-grounded findings
**Plans**: 4 plans (4/4 complete)

Plans:
- [x] 08-01-PLAN.md -- PCB image renderer with coordinate grid overlay and spatial primitive extraction
- [x] 08-02-PLAN.md -- Procedural maze-routing generator and cold-start reasoning chain synthesis
- [x] 08-03-PLAN.md -- Spatial query API and coordinate-grounded DRC/ERC report pipeline
- [x] 08-04-PLAN.md -- Rick agent integration: coordinate-grounded findings

### Phase 9: GRPO Spatial Reasoning Training
**Goal**: Train a reward model for PCB spatial reasoning using GRPO on synthetic maze-routing data
**Depends on**: Phase 8
**Requirements**: GRPO-01, GRPO-02, GRPO-03, GRPO-04, GRPO-05, GRPO-06, GRPO-07
**Success Criteria** (what must be TRUE):
  1. 100k+ synthetic PCB maze-routing samples generated with verified solutions
  2. Cold-start reasoning chains synthesized at scale with DFS exploration traces
  3. A reward model scores chains with per-step dense rewards (format, quality, accuracy)
  4. GRPO training loop runs end-to-end
  5. Reward hacking is prevented via smooth penalty functions
  6. Trained model shows measurable improvement on held-out tasks vs baseline
  7. Training pipeline is reproducible with a single command
**Plans**: 4 plans (4/4 complete)

Plans:
- [x] 09-01-PLAN.md -- Synthetic data pipeline at scale
- [x] 09-02-PLAN.md -- Cold-start reasoning chain synthesis at scale
- [x] 09-03-PLAN.md -- Reward model architecture
- [x] 09-04-PLAN.md -- GRPO training loop

### Phase 10: AI-Driven PCB Generation
**Goal**: Two-tier phase -- close practical operations gap, then build generative AI capabilities on top
**Depends on**: Phase 9
**Requirements**: GEN-01 through GEN-12
**Success Criteria** (what must be TRUE):
  1. sym-lib-table and fp-lib-table can be parsed, queried, and modified
  2. Manufacturing files can be exported via kicad-cli wrappers
  3. Schematic ERC errors can be auto-repaired
  4. Power net validation detects unconnected power pins
  5. Copper zones can be added and filled on PCB layouts
  6. Net classes and custom DRC rules can be set
  7. GenerationIntent schema converts natural language to structured operation sequences
  8. Template board generation creates valid .kicad_pcb files
  9. Component placement engine places components with clearance validation
  10. End-to-end pipeline: intent -> template -> operations -> validation -> export
  11. Iterative refinement loop until clean
  12. Generated boards achieve DRC pass on simple designs
**Plans**: 6 plans (6/6 complete)

Plans:
- [x] 10-01-PLAN.md -- Project file parsers and library management
- [x] 10-02-PLAN.md -- Manufacturing export wrappers
- [x] 10-03-PLAN.md -- Schematic repair, validation gates, and PCB operations
- [x] 10-04-PLAN.md -- GenerationIntent schema and template board generator
- [x] 10-05-PLAN.md -- Component placement engine and operation-sequence planning
- [x] 10-06-PLAN.md -- End-to-end generation pipeline with iterative refinement

### Phase 11: LTspice Integration
**Goal**: Parse LTspice .asc schematic files and build KiCad-LTspice bridge
**Depends on**: Phase 1
**Requirements**: LTSPICE-01 through LTSPICE-05
**Success Criteria** (what must be TRUE):
  1. A .asc file parses into structured component/net/simulation data
  2. Components with values, positions, orientations are extractable
  3. Net connectivity graph is derivable from WIRE and FLAG statements
  4. Simulation commands are extractable and parseable
  5. .raw simulation results are readable
**Plans**: 3 plans (3/3 complete)

Plans:
- [x] 11-01-PLAN.md -- .asc parser with SpiceLib
- [x] 11-02-PLAN.md -- .raw simulation result reader
- [x] 11-03-PLAN.md -- Net connectivity graph derivation from wire geometry

### Phase 12: ADI Footprint Library
**Goal**: On-demand fetching of ADI manufacturer footprints with caching and library management
**Depends on**: Phase 5, Phase 10
**Requirements**: ADI-01, ADI-02, ADI-03, ADI-04
**Success Criteria** (what must be TRUE):
  1. ADI footprints are discoverable by part number
  2. .kicad_mod footprints download and import into local library
  3. .kicad_sym symbols download and import into local library
  4. Library cache avoids re-downloading previously fetched parts
**Plans**: 3 plans (3/3 complete)

Plans:
- [x] 12-01-PLAN.md -- Type definitions, filesystem cache with JSON manifest
- [x] 12-02-PLAN.md -- SamacSys HTTP client for part search and KiCad library download
- [x] 12-03-PLAN.md -- Fetch orchestrator wiring cache/client/lib_table

</details>

<details>
<summary>v2.0 Production AI Phase Details</summary>

### Phase 13: Real-World PCB Training Pipeline
**Goal**: GitHub crawler and data pipeline for real-world training data to complement synthetic mazes
**Depends on**: Phase 8, Phase 9
**Requirements**: RW-01 through RW-05
**Success Criteria** (what must be TRUE):
  1. GitHub search API discovers KiCad repos with both .kicad_sch and .kicad_pcb files
  2. Schematic+PCB pairs parse into structured graph format
  3. Dataset normalized with deduplication and quality filtering
  4. 1,000+ real board pairs ingestible in a single pipeline run
  5. Output format compatible with GRPO training pipeline
**Plans**: 3 plans (3/3 complete)

Plans:
- [x] 13-01-PLAN.md -- GitHub repo discovery and KiCad file pair extraction
- [x] 13-02-PLAN.md -- Schematic+PCB graph parser with spatial feature extraction
- [x] 13-03-PLAN.md -- Dataset normalization, deduplication, and GRPO training format export

### Phase 14: Bidirectional KiCad-LTspice
**Goal**: KiCad -> .asc export, enabling design in KiCad, simulate in LTspice
**Depends on**: Phase 11, Phase 2
**Requirements**: BIDI-01 through BIDI-04
**Success Criteria** (what must be TRUE):
  1. A KiCad schematic exports to a valid .asc file that LTspice can open
  2. Component symbol mapping between KiCad symbols and LTspice .asy types
  3. Net labels transfer correctly between KiCad and LTspice naming conventions
  4. Simulation commands attach correctly to exported schematics
**Plans**: 3 plans (3/3 complete)

Plans:
- [x] 14-01-PLAN.md -- KiCad component to LTspice symbol mapping table and converter
- [x] 14-02-PLAN.md -- .asc writer: KiCad schematic to LTspice .asc export
- [x] 14-03-PLAN.md -- Simulation command injection and round-trip validation

### Phase 15: AI Generation Wiring
**Goal**: Wire an LLM into the generation pipeline for component suggestions, schematic drafting, design critique
**Depends on**: Phase 10, Phase 8
**Requirements**: AIGEN-01 through AIGEN-05
**Success Criteria** (what must be TRUE):
  1. Natural language design intent produces a structured GenerationIntent with validated operations
  2. LLM suggests components given a functional description
  3. Design critique identifies spatial issues
  4. Iterative refinement loop: generate -> validate -> LLM fix -> repeat
  5. End-to-end demo: "design a voltage regulator circuit" produces a valid .kicad_sch passing ERC
**Plans**: 4 plans (4/4 complete)

Plans:
- [x] 15-01-PLAN.md -- LLM integration layer
- [x] 15-02-PLAN.md -- Design critic with spatial reasoning
- [x] 15-03-PLAN.md -- Iterative refinement loop with LLM-driven error fixing
- [x] 15-04-PLAN.md -- End-to-end generation pipeline demo and validation

### Phase 16: Component Placement AI
**Goal**: Predict optimal component placement from schematic netlist using spatial reasoning
**Depends on**: Phase 8, Phase 9, Phase 13
**Requirements**: PLACE-01 through PLACE-05
**Success Criteria** (what must be TRUE):
  1. Schematic netlist converts to placement graph
  2. Placement model predicts (x, y, rotation) for each component
  3. Suggested placements pass DRC clearance checks
  4. Placement quality scores comparable to manual placement
  5. Interactive mode: user places some components, AI places the rest
**Plans**: 4 plans (4/4 complete)

Plans:
- [x] 16-01-PLAN.md -- Schematic netlist to placement graph converter
- [x] 16-02-PLAN.md -- Placement prediction model architecture and training
- [x] 16-03-PLAN.md -- DRC-aware placement validation and scoring
- [x] 16-04-PLAN.md -- Interactive placement mode with constraint propagation

### Phase 17: Package & Distribution
**Goal**: Make kicad-agent installable via pip with a proper CLI entry point and PyPI package
**Depends on**: Phase 7
**Requirements**: DIST-01, DIST-02, DIST-03, DIST-04
**Success Criteria** (what must be TRUE):
  1. `pip install kicad-agent` installs a working package with CLI entry point
  2. `kicad-agent` CLI command runs operations, validation, and project context
  3. Package metadata is correct on PyPI
  4. README and API documentation cover all public interfaces
**Plans**: 3 plans (3/3 complete)

Plans:
- [x] 17-01-PLAN.md -- Package structure, pyproject.toml updates, CLI entry point
- [x] 17-02-PLAN.md -- PyPI publishing workflow and version management
- [x] 17-03-PLAN.md -- README, API documentation, and usage examples

### Phase 18: CI/CD Pipeline
**Goal**: GitHub Actions CI for full test suite, linting, type checking, and coverage gate
**Depends on**: Phase 17
**Requirements**: CI-01, CI-02, CI-03, CI-04
**Success Criteria** (what must be TRUE):
  1. Every PR runs full test suite with pass/fail gate
  2. Linting and type checking run on every push
  3. Coverage report generated and 80%+ gate enforced
  4. Release workflow: tag push -> build -> test -> PyPI publish
**Plans**: 2 plans (2/2 complete)

Plans:
- [x] 18-01-PLAN.md -- GitHub Actions CI: test, lint, type-check, coverage gate
- [x] 18-02-PLAN.md -- Release automation: version bump, changelog, PyPI publish

### Phase 19: Interactive Routing Suggestions
**Goal**: Use spatial primitives and training data to suggest trace routing paths on real PCBs
**Depends on**: Phase 8, Phase 16
**Requirements**: ROUTE-01 through ROUTE-04
**Success Criteria** (what must be TRUE):
  1. Given placed components and netlist, routing suggestions are generated for each net
  2. Suggested routes satisfy DRC clearance and design rule constraints
  3. Differential pair routing respects impedance and length matching constraints
  4. Interactive mode: user approves/rejects suggestions, AI adapts
**Plans**: 3 plans (3/3 complete)

Plans:
- [x] 19-01-PLAN.md -- Routing graph model and pathfinding with DRC constraints
- [x] 19-02-PLAN.md -- Differential pair routing with impedance and length matching
- [x] 19-03-PLAN.md -- Interactive routing mode with approval and constraint adaptation

### Phase 20: SFT Data Preparation + Training Infrastructure
**Goal**: Convert 136K correct training chains to ChatML instruction format, quality-filter, and train SFT baseline on Qwen2.5-1.5B
**Depends on**: Phase 9, Phase 13
**Requirements**: LLM-01, LLM-02, LLM-03, LLM-04
**Success Criteria** (what must be TRUE):
  1. 136K correct chains converted to ChatML instruction format with task-specific prompt templates
  2. Bottom quartile filtered out using reward model scoring (retain ~102K high-quality samples)
  3. SFT training completes on Qwen2.5-1.5B with LoRA (fp16 on Apple MPS)
  4. SFT model generates valid PCB reasoning chains on held-out test set
  5. SFT model scores higher than base model on reward model evaluation
**Plans**: 3 plans (3/3 complete)

Plans:
- [x] 20-01-PLAN.md -- Convert 136K correct chains to ChatML + reward model quality filter
- [x] 20-02-PLAN.md -- TRL SFTTrainer + LoRA training on Qwen2.5-1.5B on Apple MPS
- [x] 20-03-PLAN.md -- SFT evaluation: base vs trained model comparison + eval report

### Phase 21: GRPO RL Fine-Tuning
**Goal**: Fine-tune SFT model using GRPO with the trained reward model as critic
**Depends on**: Phase 20, Phase 9
**Requirements**: LLM-05, LLM-06, LLM-07, LLM-08
**Success Criteria** (what must be TRUE):
  1. GRPO loop generates N chains per sample, scores with reward model, computes group advantages
  2. Policy updates via PPO-clip with KL divergence penalty
  3. GRPO model achieves >85% discrimination rate (up from 75% SFT baseline)
  4. GRPO model scores higher than SFT on all three reward dimensions
**Plans**: 2 plans (2/2 complete)

Plans:
- [x] 21-01-PLAN.md -- GRPO training loop implementation
- [x] 21-02-PLAN.md -- GRPO training run + evaluation + Council review gate

### Phase 22: Agent Integration + End-to-End Evaluation
**Goal**: Wire the GRPO-trained LLM into kicad-agent as its reasoning engine with best-of-N generation
**Depends on**: Phase 21, Phase 7
**Requirements**: LLM-09, LLM-10, LLM-11, LLM-12
**Success Criteria** (what must be TRUE):
  1. Fine-tuned model loads and generates chains in <2s per chain on MPS
  2. Best-of-N (N=4) picks chains scoring 20%+ higher than single-sample
  3. kicad-agent CLI has `analyze` subcommand using the fine-tuned model
  4. Python API exposes `generate_analysis(pcb_path)` returning scored chains
  5. GSD Skill: Claude can invoke `/kicad-agent analyze <pcb>` and get spatial reasoning
  6. End-to-end demo: analyze HackRF One and produce quality reasoning chain
**Plans**: 2 plans (2/2 complete)

Plans:
- [x] 22-01-PLAN.md -- Inference wrapper + best-of-N + kicad-agent wiring
- [x] 22-02-PLAN.md -- End-to-end evaluation + Council review + documentation

</details>

<details>
<summary>v2.1 Audit Phase Details</summary>

### Phase 23: Schematic Repair Operations
**Goal**: 8 schematic manipulation operations discovered from real backplane repair sessions
**Depends on**: Phase 10, Phase 3
**Requirements**: SCHREPAIR-01 through SCHREPAIR-08
**Success Criteria** (what must be TRUE):
  1. ERC JSON output parses into structured violation list with positions for targeted repair
  2. Violation positions extractable by type for automated fix workflows
  3. Hierarchical labels validatable against expected set to catch agent deletion
  4. KiCad 6 format schematics convert to valid KiCad 10 passing all 9 format checks
  5. No-connect markers placed at pin_not_connected positions without file corruption
  6. Power flag symbols placed at power_pin_not_driven positions with correct lib definition
  7. Off-grid wire endpoints snapped to grid while preserving connectivity
  8. Root sheet generated from sub-sheet hierarchical labels with correct pin positioning
**Plans**: 4 plans (4/4 complete)

Plans:
- [x] 23-01-PLAN.md -- ERC parser, violation position extractor, hierarchical label guard
- [x] 23-02-PLAN.md -- KiCad 6 to KiCad 10 format converter with section-based reassembly
- [x] 23-03-PLAN.md -- Schematic mutation operations: snap_to_grid, add_power_flag, place_no_connects_from_erc
- [x] 23-04-PLAN.md -- Root sheet generator from sub-sheet hierarchical labels

### Phase 24: Council Audit Remediation & Security Hardening
**Goal**: Fix all 56 findings from Council of Ricks all-hands audit
**Depends on**: Phase 10, Phase 15, Phase 17
**Requirements**: SEC-01, SEC-02, SEC-03, SEC-04, SEC-05, SLC-01, SLC-02, SLC-03, QUAL-01, QUAL-02, TEST-01
**Success Criteria** (what must be TRUE):
  1. Path traversal bypass eliminated -- executor confines all file operations to project directory
  2. S-expression injection eliminated -- all interpolated values use _escape_sexpr_value
  3. All 3 SLC violations fixed -- no stubs, no phantom operations, no always-true validators
  4. Prompt-to-schema field mismatches resolved
  5. Exception messages sanitized for MCP clients
  6. Training pipeline integrity gaps addressed
  7. All 79 broad `except Exception` catches narrowed to specific exception types
  8. Code quality issues resolved: schema.py split, dead code removed, duplication consolidated
**Plans**: 5 plans (5/5 complete, Council APPROVED)

Plans:
- [x] 24-01-PLAN.md -- Security hardening: path traversal, S-expression injection, exception sanitization
- [x] 24-02-PLAN.md -- SLC fixes: implement or remove stubs/phantoms, fix prompt-schema mismatches
- [x] 24-03-PLAN.md -- Code quality: split large files, narrow exception catches, remove dead code
- [x] 24-04-PLAN.md -- Testing gaps and training pipeline integrity
- [x] 24-05-PLAN.md -- Architecture gaps and low-priority fixes

</details>

### v2.2 Complete-Ops Phase Details

### Phase 25: Remove Operations
**Goal**: Users can remove wires, labels, junctions, and no-connect markers from schematics with adjacency safety checks and full transaction rollback
**Depends on**: Phase 24 (stable codebase post-audit)
**Requirements**: REMOVE-01, REMOVE-02, REMOVE-03, REMOVE-04, REMOVE-05
**Success Criteria** (what must be TRUE):
  1. A wire segment is removed by UUID and refuses removal if other wires share its endpoints (preventing dangling ERC errors)
  2. A label (global or local) is removed by UUID with net membership validation
  3. A junction marker is removed by UUID without corrupting connected wires
  4. A no-connect marker is removed by UUID cleanly
  5. All four remove operations use the list-filter pattern from remove_component.py, record mutations in Transaction, and preserve round-trip fidelity
**Plans**: 2 plans

Plans:
- [x] 25-01-PLAN.md -- Remove operation schemas (RemoveWireOp, RemoveLabelOp, RemoveJunctionOp, RemoveNoConnectOp) and executor registration (REMOVE-05)
- [x] 25-02-PLAN.md -- Remove handlers with list-filter pattern, wire adjacency check, net membership validation, and tests (REMOVE-01, REMOVE-02, REMOVE-03, REMOVE-04)

### Phase 26: Connectivity Query
**Goal**: Users can query PCB connectivity through the operation executor using the existing NetGraph, with structured JSON results compatible with LLM reasoning chains
**Depends on**: Phase 25 (query pattern established)
**Requirements**: QUERY-01, QUERY-02, QUERY-03, QUERY-04
**Success Criteria** (what must be TRUE):
  1. query_connectivity operation exposes NetGraph through the executor as a read-only handler (no IR mutation, no Transaction registration)
  2. Five query types work: connected_pads, net_stats, are_connected, shortest_path, connected_components
  3. Read-only semantics enforced -- the handler cannot modify IR state or trigger Transaction writes
  4. Results are structured JSON with coordinate-grounded data where applicable, compatible with LLM reasoning chains
**Plans**: 1 plan

Plans:
- [x] 26-01-PLAN.md -- QueryConnectivityOp schema, read-only handler wrapping NetGraph, 5 query types, JSON result formatting, and tests (QUERY-01, QUERY-02, QUERY-03, QUERY-04)

### Phase 27: Footprint Creation
**Goal**: Users can create .kicad_mod footprint files from JSON PadSpec definitions with UUID-preserving serialization and automatic courtyard generation
**Depends on**: Phase 26 (create-path extension pattern validated)
**Requirements**: FOOT-01, FOOT-02, FOOT-03, FOOT-04
**Success Criteria** (what must be TRUE):
  1. A .kicad_mod file is generated from JSON PadSpec definitions (pad number, shape, position, size, layers, drill) that KiCad can open without errors
  2. Footprint serialization preserves UUIDs on pads and graphics using raw S-expression construction (not kiutils Footprint.to_file() which drops UUIDs)
  3. Courtyard is automatically generated from pad bounding box with configurable margin
  4. Pad layer validation rejects invalid layer names -- only valid KiCad layers (F.Cu, B.Cu, F.Paste, etc.) accepted via Literal type
**Plans**: 2 plans

Plans:
- [x] 27-01-PLAN.md -- CreateFootprintOp schema with PadSpec, layer validation via Literal type, executor registration (FOOT-01, FOOT-04)
- [x] 27-02-PLAN.md -- Footprint handler with UUID-preserving raw S-expression serialization, courtyard generation, and tests (FOOT-02, FOOT-03)

### Phase 28: Hierarchical Sheet Operations
**Goal**: Users can create hierarchical sheet instances and pins, navigate sheet hierarchies, and manage nested sub-sheets with correct path resolution and instance tracking
**Depends on**: Phase 27 (sub-file creation pattern validated)
**Requirements**: SHEET-01, SHEET-02, SHEET-03, SHEET-04, SHEET-05, SHEET-06
**Success Criteria** (what must be TRUE):
  1. A hierarchical sheet instance is created with correct fileName (relative to parent directory, not project root), UUID, and position
  2. A hierarchical pin is created with exact-match validation against child sheet labels (case-sensitive, no fuzzy matching)
  3. The sheet hierarchy is navigable returning a tree with UUID paths, pin/label mappings, and file paths
  4. Sheet instances (sheetInstances) are updated alongside sheet creation -- missing instances cause KiCad crashes
  5. Sub-sheet file creation produces valid .kicad_sch with proper header, UUID, and paper settings
  6. Nested hierarchy works: path resolution handles root -> subdir/child -> subdir/subsubdir/grandchild
**Plans**: 3 plans

Plans:
- [x] 28-01-PLAN.md -- AddSheetOp and NavigateSheetsOp schemas, sheet instance tracking, and executor registration (SHEET-01, SHEET-04)
- [x] 28-02-PLAN.md -- add_sheet handler with fileName resolution relative to parent, sheetInstances update, sub-sheet file creation, and navigate_hierarchy handler (SHEET-01, SHEET-03, SHEET-04, SHEET-05, SHEET-06)
- [x] 28-03-PLAN.md -- AddSheetPinOp schema, add_sheet_pin handler with exact-match label validation, nested hierarchy support, and tests (SHEET-02, SHEET-06)

### Phase 29: Cross-File Atomic Operations
**Goal**: Users can propagate symbol changes across all referencing files atomically, with partial failure guarantee that rolls back ALL files if any single mutation fails
**Depends on**: Phase 28 (executor stable, all single-file operations complete)
**Requirements**: XFILE-05, XFILE-06, XFILE-07
**Success Criteria** (what must be TRUE):
  1. propagate_symbol_change operation uses existing AtomicOperation (crossfile/atomic.py) to mutate a symbol across all referencing files atomically
  2. A new `_CROSSFILE_HANDLERS` dispatch path in the executor receives `dict[Path, BaseIR]` instead of single IR, coordinating multiple files
  3. Partial failure guarantee holds -- if any file mutation fails, ALL files roll back via AtomicOperation, validating ALL mutations before opening ANY Transaction
**Plans**: 2 plans

Plans:
- [x] 29-01-PLAN.md -- `_CROSSFILE_HANDLERS` registry and `_execute_cross_file()` dispatch path in executor, PropagateSymbolChangeOp schema (XFILE-05, XFILE-06)
- [x] 29-02-PLAN.md -- propagate_symbol_change handler wiring AtomicOperation, partial failure guarantee with pre-validation, and tests (XFILE-05, XFILE-07)

</details>

### v2.3 MCP-Server Phase Details

### Phase 30: MCP Operations Server
**Goal**: New MCP server binary exposing all 57 kicad-agent operations as individually named tools, with dynamic schema generation, structured error handling, and meta-tools for schema discovery and project context
**Depends on**: Phase 29 (all 57 operations complete and tested)
**Requirements**: MCPSRV-01, MCPSRV-02, MCPSRV-03, MCPSRV-04, MCPSRV-05, MCPSRV-06, MCPSRV-07, META-01, META-02, META-03, PKG-01, PKG-02
**Success Criteria** (what must be TRUE):
  1. All 57 operation types appear as individually named MCP tools with correct input schemas from `model_json_schema()`
  2. MCP server runs on stdio transport via `kicad-agent-edit` CLI entry point
  3. Project base directory configurable via `KICAD_PROJECT_DIR` env var, defaulting to `Path.cwd()`
  4. Synchronous executor calls wrapped in `asyncio.to_thread()` -- event loop never blocks
  5. Failed operations return `CallToolResult` with `isError=True` and structured error JSON
  6. Successful operations return structured JSON matching executor return format
  7. Tool responses exceeding 50KB are truncated with summary trailer
  8. ToolAnnotations auto-assigned: readOnlyHint for query/validation, destructiveHint for remove, idempotentHint for create
  9. `get_operation_schema` meta-tool returns full JSON Schema for all 57 operations
  10. `get_project_context` meta-tool returns project structure, file inventory, and board statistics
  11. `kicad-agent-edit` entry point registered in pyproject.toml with no new dependencies
**Plans**: 1 plan (3 merged)

Plans:
- [x] 30-01-PLAN.md -- All 3 plans merged: server skeleton + dispatcher + meta-tools + tests (MCPSRV-01 through MCPSRV-07, META-01 through META-03, PKG-01, PKG-02)

### Phase 31: Validation Integration
**Goal**: ERC/DRC convenience tools wrapping kicad-cli for MCP clients that want one-call validation without running separate operations
**Depends on**: Phase 30 (MCP server operational)
**Requirements**: MCPVAL-01, MCPVAL-02
**Success Criteria** (what must be TRUE):
  1. `erc_check` MCP tool runs `kicad-cli sch erc` and returns structured violation results (pass/fail/warning with positions)
  2. `drc_check` MCP tool runs `kicad-cli pcb drc` and returns structured violation results (pass/fail/warning with positions)
**Plans**: 1 plan

Plans:
- [x] 31-01-PLAN.md -- erc_check and drc_check MCP tools wrapping kicad-cli validation, structured result parsing, ToolAnnotations (readOnlyHint=True), and tests (MCPVAL-01, MCPVAL-02)

### v2.4 Production-Hardening Phase Details

### Phase 32: Executor Performance -- COMPLETE
**Goal**: IR caching and batch execution for single-parse single-write operation throughput
**Depends on**: Phase 31
**Requirements**: PERF-01, PERF-02, PERF-03, PERF-04
**Success Criteria**:
  1. IRCache with LRU eviction and thread safety
  2. execute_batch() parses each file once, writes each file once
  3. Batch rejects entire batch on validation failure with full error report
  4. 100 property modifications complete in under 10 seconds
**Plans**: 2 plans (2/2 complete)

Plans:
- [x] 32-01-PLAN.md -- IRCache module with LRU eviction and thread safety (PERF-01)
- [x] 32-02-PLAN.md -- execute_batch() with pre-validation and single-write optimization (PERF-02, PERF-03, PERF-04)

### Phase 33: Undo/Redo Stack
**Goal**: Per-project undo/redo stack storing file content snapshots in bounded deque, exposed as MCP meta-tools
**Depends on**: Phase 32
**Requirements**: UNDO-01, UNDO-02, UNDO-03, UNDO-04, UNDO-05
**Success Criteria**:
  1. UndoStack class with bounded deque, thread-safe, stores file content snapshots
  2. undo() restores pre-mutation content, redo() restores post-mutation content
  3. MCP undo/redo meta-tools with destructiveHint=True
  4. Per-file isolation across concurrent projects
  5. Configurable max_size with env var KICAD_UNDO_MAX_SIZE
**Plans**: 2 plans (2/2 complete)

Plans:
- [x] 33-01-PLAN.md -- UndoStack module, executor snapshot capture, undo/redo methods (UNDO-01, UNDO-02, UNDO-04, UNDO-05)
- [x] 33-02-PLAN.md -- MCP undo/redo meta-tools with dispatch and tests (UNDO-03)

### Phase 34: LLM Provider Abstraction
**Goal**: Abstract LLM calls behind a typed protocol so different providers (Anthropic, mock) can be swapped via environment variable
**Depends on**: Phase 33
**Requirements**: LLM-13, LLM-14, LLM-15, LLM-16, LLM-17
**Success Criteria**:
  1. LLMProvider protocol with generate(), embed(), and create_message() methods
  2. AnthropicProvider implements protocol using existing LLMClient
  3. All 6 consumer files migrated to accept provider via constructor
  4. Provider selection via KICAD_LLM_PROVIDER env var (default "anthropic")
  5. MockProvider for deterministic testing without API calls
**Plans**: 2 plans

Plans:
- [x] 34-01-PLAN.md -- LLMProvider protocol, AnthropicProvider, MockProvider, get_provider() factory, tests, __init__.py exports (LLM-13, LLM-14, LLM-16, LLM-17)
- [x] 34-02-PLAN.md -- Consumer migration: DesignCritic, ErrorFixer, IntentParser, ComponentSuggester, UnifiedParsers, pipeline.py (LLM-15)

### Phase 35: Remaining Ops Gaps
**Goal**: Close the five remaining operation gaps for complete CRUD coverage
**Depends on**: Phase 34
**Requirements**: GEN-01, GEN-03, GEN-04, GEN-05, GEN-06
**Success Criteria** (what must be TRUE):
  1. sym-lib-table and fp-lib-table can be queried for all entries via list_lib_entries
  2. Net classes can be listed, modified, and removed in .kicad_dru files
  3. Design rules can be listed, modified, and removed in .kicad_dru files
  4. .kicad_pro settings can be modified without losing unknown JSON keys
  5. erc_auto_fix chains parse_erc to repair dispatch with iteration limits
  6. validate_power_nets traverses hierarchical sheets when check_hierarchical=True
  7. Copper zones can be modified and removed by UUID or index
**Plans**: 3 plans

Plans:
- [x] 35-01-PLAN.md -- Full CRUD for project files: list/modify/remove lib entries, net classes, design rules, project settings (GEN-01, GEN-06)
- [x] 35-02-PLAN.md -- erc_auto_fix meta-operation with violation-to-repair dispatch and iteration control (GEN-03)
- [x] 35-03-PLAN.md -- Hierarchical power validation + copper zone modify/delete (GEN-04, GEN-05)

### Phase 36: Multi-Layer Routing
**Goal**: Multi-layer routing with 3D graph (x,y,layer) nodes, IPC-2141 impedance-controlled trace width calculation, and sawtooth length matching for high-speed signals
**Depends on**: Phase 35
**Requirements**: ROUTE-05, ROUTE-06, ROUTE-07
**Success Criteria** (what must be TRUE):
  1. RoutingGraph builds 3D (x,y,layer) nodes with via edges between adjacent layers
  2. A* pathfinding routes through layer transitions when direct path is blocked
  3. IPC-2141 microstrip and stripline impedance formulas return correct Z0 values
  4. Bisection solver finds trace width for target impedance within 1% tolerance
  5. Sawtooth length matching converges to target delta within 10 refinement iterations
  6. AutoRouteOp accepts layers, impedance_target, length_match_pairs fields
  7. Executor handler produces TrackSegments with impedance-adjusted widths, ViaSegments at layer transitions, and length-matched net pairs
**Plans**: 3 plans

Plans:
- [x] 36-01-PLAN.md -- 3D routing graph, via cost model, pathfinder 3D, ViaSegment, geometry extraction (ROUTE-05)
- [x] 36-02-PLAN.md -- IPC-2141 impedance calculator, sawtooth length matching engine (ROUTE-06, ROUTE-07)
- [x] 36-03-PLAN.md -- AutoRouteOp schema extension, executor handler integration, end-to-end tests (ROUTE-05, ROUTE-06, ROUTE-07)

### Phase 37: Training + Infrastructure
**Goal**: Harden training pipeline with data versioning, evaluation harness, smoke tests, and output cleanup. Add production-grade infrastructure: structured logging, MCP health check, and graceful shutdown.
**Depends on**: Phase 36
**Requirements**: TRAIN-01, TRAIN-02, TRAIN-03, TRAIN-04, INFRA-01, INFRA-02, INFRA-03
**Success Criteria** (what must be TRUE):
  1. DataManifest records SHA256 hashes of training data files and verifies content integrity
  2. Regression detection flags evaluation metrics dropping below configurable thresholds
  3. SFT smoke test trains tiny RewardModel on synthetic data with decreasing loss
  4. TrainingCleanup removes stale output preserving latest N runs per type with dry-run mode
  5. configure_logging() produces structured JSON or console output from all 70 getLogger sites
  6. health_check MCP tool returns server status with uptime and in-flight operation count
  7. Graceful shutdown rejects new operations and drains in-flight ops before exit
**Plans**: 3 plans

Plans:
- [x] 37-01-PLAN.md -- Structured logging via structlog with env-var controlled output format (INFRA-01)
- [x] 37-02-PLAN.md -- Training data versioning, regression detection, output cleanup (TRAIN-01, TRAIN-02, TRAIN-04)
- [x] 37-03-PLAN.md -- MCP health check, graceful shutdown, training pipeline smoke tests (INFRA-02, INFRA-03, TRAIN-03)

### Phase 95: Implement dual knowledge base integration: Cognee ingestion for Claude Code semantic search, section injection system for local model prompts

**Goal:** Wire 4 KiCad reference documents into Cognee (semantic search) and local model (section injection) with token budget enforcement.
**Requirements**: D-01 through D-05
**Depends on:** Phase 94
**Plans:** 3/3 plans complete

Plans:
- [x] 95-01-PLAN.md -- Cognee ingestion script with dry-run mode and verification queries (D-01)
- [x] 95-02-PLAN.md -- KnowledgeManager with section chunking, op-to-section mapping, and lazy loading (D-02, D-03, D-05)
- [x] 95-03-PLAN.md -- Token budget enforcement, prompt builder integration, --no-knowledge CLI flag (D-02, D-03, D-04)

### Phase 96: Pre-flight validation overhaul: universal gate for all execution paths (PCB, cross-file, batch), silent failure hardening, structural fragility fixes

**Goal:** Universal pre-flight gate covering all execution paths (schematic, PCB, cross-file) with PCB-specific checks, cross-file validation, batch cumulative IR tracking, silent failure hardening, and structural fragility fixes -- zero silent corruption paths
**Requirements**: TBD
**Depends on:** Phase 95
**Plans:** 3/3 plans complete

Plans:
- [x] 96-01-PLAN.md -- Universal pre-flight gate with file-type dispatch, PCB/cross-file/schematic checks, gate wiring in execute_pcb and execute_cross_file (D-01, D-02, D-05, D-06, D-07)
- [x] 96-02-PLAN.md -- Batch stop-and-rollback with cumulative IR, transaction cleanup logging, lock file errors, repair/undo failure logging (D-03, D-08, D-09, D-10, D-11)
- [x] 96-03-PLAN.md -- Structural fragility fixes: force flag removal, hardcoded net fix, write verification, cross-file extension validation, content header validation (D-12, D-13, D-14, D-15, D-16)

### Phase 97: KiCad Vision LoRA Training Execution

**Goal:** Convert 200K coordinate-grounded maze routing chains + 6,696 PCB vision samples into unified Gemma 4 vision training dataset, execute LoRA training on Vast.ai RTX 3090, and verify adapter loads locally via mlx-vlm
**Requirements**: D-01 through D-21 (all requirements defined in CONTEXT.md decisions)
**Depends on:** Phase 96
**Plans:** 4 plans

Plans:
- [x] 97-01-PLAN.md -- Maze vision converter module + CLI + tests (D-02, D-04, D-05, D-20)
- [x] 97-02-PLAN.md -- Vast.ai training scripts adapted from spectral-primitives (D-06, D-07, D-08, D-09, D-10, D-11, D-12)
- [x] 97-03-PLAN.md -- Dataset merge CLI + adapter metadata registry (D-01, D-03, D-05, D-13, D-14, D-15)
- [x] 97-04-PLAN.md -- Adapter verification script + full pipeline checkpoint (D-16, D-17, D-18)

### Phase 98: AI Routing Strategy Advisor (Reframed)

**Goal:** Use trained Gemma 4 12B V2 vision LoRA to generate routing strategy — net priorities, layer assignments, keepout suggestions — consumed by the Phase 100 orchestrator as `RoutingStrategy` inputs. Strategy-to-constraints translator, validation gate, eval harness vs. deterministic baseline.
**Requirements**: R-1 KiCadVisionPipeline wired into RoutingOrchestrator via RoutingStrategy interface; R-2 Strategy prompt emits structured JSON (net_priorities, layer_hints, keepouts, routing_notes); R-3 Strategy-to-constraints translator; R-4 Validation gate (reject out-of-bounds, unknown nets, impossible layers); R-5 Eval harness (AI-guided vs Phase 100 baseline: completion rate, via count, trace length, DRC); R-6 Graceful degradation to deterministic fallback
**Depends on:** Phase 99, Phase 100
**Plans:** 0 plans

Plans:
- [ ] TBD (run /gsd-plan-phase 98 to break down)

### Phase 99: Freerouting Integration Hardening

**Goal:** Make Freerouting the reliable multi-layer routing backend by importing full board context (footprints, net classes, zones, via rules) from `.kicad_pcb` and validating output against DRC. Replaces the conceptual "Phase 122B" — multi-layer graph routing is already implemented (graph.py:156-247); this phase closes the real gaps.
**Requirements**: R-1 Footprint courtyard+pad obstacles from .kicad_pcb into DSN; R-2 Net class propagation (trace width, via std, clearance); R-3 Copper zones + keepouts as routing rules; R-4 Via type config (THT/blind/buried/microvia) from stackup; R-5 45° trace mode; R-6 Freerouting output → TrackSegment/ViaSegment bridge verified multilayer; R-7 Sweep "Phase 122B" code comments → "Phase 99"
**Depends on:** (standalone — uses existing freerouting.py, dsn_generator.py, FreerouteBatch.java)
**Plans:** 3/3 plans complete

Plans:
- [x] 99-01-PLAN.md — DSN generator refactor: R-1 footprints, R-2 net classes, R-3 zones, R-5 snap_angle, R-7 comment sweep
- [x] 99-02-PLAN.md — R-4 via padstacks per stackup + R-6 SES multi-layer via bridge verification
- [x] 99-03-PLAN.md — SC-3 e2e DRC validation + SC-4 baseline metrics + SC-5 45° vs Manhattan comparison

### Phase 100: RoutingOrchestrator and Human Approval Loop

**Goal:** Intelligent dispatcher that routes each net through the right backend (in-house A* for simple, Freerouting for complex) with a human approval gate over the result. Builds on existing InteractiveRoutingSession and MultiPassRouter.
**Requirements**: R-1 RoutingOrchestrator with RoutingStrategy interface (deterministic policies now, AI pluggable in Phase 98); R-2 Per-net dispatch (net class, pin count, density, diff-pair → router selection); R-3 InteractiveRoutingSession extended for Freerouting output; R-4 Rollback via PersistentUndoStack; R-5 Audit trail (net, router, strategy, result, timestamp); R-6 Deterministic fallback policy; R-7 Batch orchestration API
**Depends on:** Phase 99
**Plans:** 0 plans

Plans:
- [ ] TBD (run /gsd-plan-phase 100 to break down)

### Phase 101: Schematic Ops Bug Fixes

**Goal:** Close 5 P0/P1 schematic ops bugs blocking analog-ecosystem backplane cleanup (BUGS/P0-001 through P0-005). Three of five share a common root cause: position calculation without proper KiCad 10 transform handling. One is a simple attribute access bug. One requires deprecation + raw S-expr rewrite to prevent data loss.
**Requirements**: R-1 P0-001 `update_symbols_from_library` crash (Symbol.name attribute access — quick fix); R-2 P0-002 `place_missing_units` position collision (dedup logic for multi-unit components); R-3 P0-003 `erc_auto_fix` data loss (deprecate + raw S-expr rewrite, NOT kiutils re-serialization); R-4 P0-004 `place_no_connects_from_erc` wrong positions (apply symbol rotation transform); R-5 P0-005 `remove_dangling_wires` criteria mismatch (align with KiCad ERC electrical definition)
**Depends on:** (standalone — fixes existing ops, no new infrastructure)
**Plans:** 0 plans

Plans:
- [ ] TBD (run /gsd-plan-phase 101 to break down)

---

<details>
<summary>v2.4 Schematic Intelligence (Phases 38-40) - SHIPPED 2026-05-31</summary>

- [x] **Phase 38: Schematic Routing Engine** - Pin position resolution, collision-aware wire routing, net-based batch wiring, full schematic regeneration from netlist. Born from real-world pain: Bret spent 3 sessions manually writing Python scripts to regenerate a 43-component compressor schematic. See `38-CONTEXT.md` for the complete hands-on experience dump.
- [x] **Phase 39: Schematic Intelligence** - Net extraction from existing schematics, net name conflict detection, automatic name suggestion from topology. Eliminates the manual net-name-to-global-label alignment work.
- [x] **Phase 40: ERC Root Cause Analysis** - Violation classification (fixable vs pre-existing vs benign), root cause diagnosis, enhanced erc_auto_fix with root cause mode. Moves from symptom patching to actual fix generation.

</details>

### Phase 38: Schematic Routing Engine
**Goal**: Pin position resolution for multi-unit/named-pin ICs, collision-aware schematic wire routing, net-based batch wiring, and full schematic regeneration from a netlist definition. The PCB auto-router exists; this is its schematic counterpart.
**Depends on**: Phase 25 (remove operations), Phase 32 (executor batch), Phase 35 (remaining ops gaps)
**Context**: See `38-CONTEXT.md` — real-world pain points, test cases, implementation formulas from hands-on wiring work
**Requirements**: SCH-ROUTE-01, SCH-ROUTE-02, SCH-ROUTE-03, SCH-ROUTE-04
**Success Criteria** (what must be TRUE):
  1. `resolve_pin_positions` correctly resolves pins for multi-unit ICs (CD4066BE, NE5532), named-pin ICs (THAT4301), R/C passives, and power symbols with rotation transforms
  2. `detect_pin_overlaps` finds R55/R56 overlap in compressor-stage at position (59.69, 78.74)
  3. `detect_routing_collisions` identifies U22 pin columns (x=95.25, x=105.41) as collision zones
  4. `connect_pins` generates wires with collision avoidance and net labels for guaranteed connectivity
  5. `batch_connect` processes 45 nets for compressor-stage without error
  6. `regenerate_wiring` produces a schematic with ≤33 ERC violations (matching manual script result)
  7. Parent schematic ERC does not regress (≤209 violations for analog-board)
**Plans**: 4 plans

Plans:
- [x] 38-01-PLAN.md -- Pin position resolution operation (SCH-ROUTE-01)
- [x] 38-02-PLAN.md -- Collision detection + pin overlap detection operations (SCH-ROUTE-02)
- [x] 38-03-PLAN.md -- connect_pins operation with hybrid wire/label routing (SCH-ROUTE-03)
- [x] 38-04-PLAN.md -- batch_connect + regenerate_wiring high-level operations (SCH-ROUTE-04)

### Phase 39: Schematic Intelligence
**Goal**: Extract existing net topology, detect naming conflicts, suggest canonical names based on global labels and circuit function. Eliminate manual net-name alignment work.
**Depends on**: Phase 38
**Requirements**: SCH-INTEL-01, SCH-INTEL-02, SCH-INTEL-03
**Success Criteria** (what must be TRUE):
  1. `extract_nets` correctly identifies all 45 nets in compressor-stage with pin membership
  2. `detect_net_conflicts` finds the R55/R56 pin overlap and all case-mismatch conflicts
  3. `suggest_net_names` correctly maps internal names to global label names
  4. No regression in existing operations
**Plans**: 3 plans

Plans:
- [x] 39-01-PLAN.md -- Net extraction from existing schematics (SCH-INTEL-01)
- [x] 39-02-PLAN.md -- Net name conflict detection (SCH-INTEL-02)
- [x] 39-03-PLAN.md -- Auto-name nets from topology (SCH-INTEL-03)

### Phase 40: ERC Root Cause Analysis
**Goal**: Upgrade erc_auto_fix from symptom patching to root cause analysis. Classify violations (fixable, pre-existing, benign, config), diagnose root causes, generate targeted fixes.
**Depends on**: Phase 38, Phase 39
**Requirements**: ERC-SMART-01, ERC-SMART-02, ERC-SMART-03
**Success Criteria** (what must be TRUE):
  1. `classify_violations` correctly categorizes all 33 compressor-stage violations
  2. `diagnose_violations` identifies R55/R56 pin overlap as root cause of multiple_net_names
  3. Enhanced `erc_auto_fix` fixes the pin overlap, reducing violations from 33 to 32
  4. Pre-existing violations are documented with root cause explanations, not silently ignored
  5. No regression in existing auto-fix test suite
**Plans**: 3 plans

Plans:
- [x] 40-01-PLAN.md -- ERC violation classification (ERC-SMART-01)
- [x] 40-02-PLAN.md -- Root cause diagnosis for fixable violations (ERC-SMART-02)
- [x] 40-03-PLAN.md -- Enhanced erc_auto_fix with root cause mode (ERC-SMART-03)

### v2.5 Benchmark Suite Phase Details

### Phase 41: PCB MMLU Benchmark
**Goal**: Create the "PCB MMLU" — 500+ multi-choice circuit analysis questions across 8 categories with benchmark runner and baseline models
**Depends on**: Phase 37 (all operations complete)
**Requirements**: BENCH-01, BENCH-02
**Success Criteria** (what must be TRUE):
  1. 500+ benchmark questions across 8 categories (component_identification, topology_recognition, signal_flow, power_design, pin_function, net_purpose, design_rules, troubleshooting)
  2. Difficulty distribution within 5% of 20/60/20 (easy/medium/hard)
  3. BenchmarkRunner produces BenchmarkResult with per-category accuracy
  4. BaselineRandom ~25%, BaselineHeuristic >25%
  5. CLI: `python -m kicad_agent.benchmarks --dataset <file> --model <name>`
**Plans**: 2 plans (2/2 complete)

Plans:
- [x] 41-01-PLAN.md -- Benchmark dataset schemas, question generator, dataset builder (BENCH-01)
- [x] 41-02-PLAN.md -- Benchmark runner, baseline models, CLI entry point (BENCH-02)

### Phase 42: Circuit QA Dataset
**Goal**: Generate 2000+ open-ended QA pairs across 6 types for fine-tuning
**Depends on**: Phase 41 (schemas and source patterns)
**Requirements**: BENCH-03
**Success Criteria** (what must be TRUE):
  1. 2000+ QA pairs with all 6 types (violation_diagnosis, signal_flow, component_function, net_purpose, design_review, value_calculation)
  2. 80/10/10 stratified train/val/test split
  3. Deterministic generation with seeded RNG
  4. Every QA pair has source reference to originating schematic
**Plans**: 1 plan (1/1 complete)

Plans:
- [x] 42-01-PLAN.md -- QA schemas, generator, dataset with split (BENCH-03)

### Phase 43: Regression Benchmark Suite
**Goal**: Automated regression detection with CI integration — every PR runs benchmarks, flags score drops >2%
**Depends on**: Phase 41, Phase 42
**Requirements**: BENCH-04
**Success Criteria** (what must be TRUE):
  1. RegressionDetector compares BenchmarkResult against baseline, flags >2% category drops
  2. Historical result tracking in benchmarks/results/
  3. GitHub Actions CI workflow runs heuristic baseline on every PR
  4. Baseline = best-known result, not first result
**Plans**: 1 plan (1/1 complete)

Plans:
- [x] 43-01-PLAN.md -- RegressionDetector + CI workflow + baseline (BENCH-04)

### Phase 44: Adversarial Test Generation
**Goal**: Three types of adversarial testing — 7-type mutation engine, property-based invariants, fuzz testing — proving parser robustness
**Depends on**: Phase 41, Phase 42
**Requirements**: BENCH-05
**Success Criteria** (what must be TRUE):
  1. MutationEngine applies 7 mutation types (swap_values, break_wire, remove_label, duplicate_net, short_pins, floating_pin, wrong_polarity)
  2. AdversarialTestSuite produces 750+ tests (200 mutation + 50 property + 500 fuzz)
  3. All tests seeded for reproducibility
  4. Parser never crashes on fuzz mutations
**Plans**: 1 plan (1/1 complete)

Plans:
- [x] 44-01-PLAN.md -- Mutation engine + adversarial suite + fuzz testing (BENCH-05)

### v3.0 Full-Stack EDA Phase Details

### Phase 50: Constraint Extraction & Propagation
**Goal**: Translate schematic intent (differential pairs, impedance, clearance, thermal, decoupling) into PCB design constraints. The keystone bridge between `analysis/` outputs and `placement/`/`validation/` consumers.
**Depends on**: Phase 45 (topology), Phase 46 (subcircuits), Phase 47 (intent inference), Phase 48 (design rules)
**Context**: Phases 45-48 provide CircuitTopology, NetClassification, Subcircuit detection, DesignIntent. This phase builds the constraint propagation layer that bridges schematic intelligence to PCB layout.
**Requirements**: CP-01, CP-02, CP-03, CP-04, CP-05, CP-06
**Success Criteria** (what must be TRUE):
  1. `ConstraintPropagator` accepts `CircuitTopology`, `list[Subcircuit]`, `DesignRuleReport` and produces `list[PCBConstraint]`
  2. Five constraint extractors produce typed constraints: DifferentialPairConstraint, ClearanceConstraint, ImpedanceConstraint, DecouplingConstraint, ThermalConstraint
  3. `.kicad_dru` parser extracts net class definitions using sexpdata (kiutils gap)
  4. ConstraintTable maps `(SignalIntegrity, NetImportance)` to `PcbConstraint` via deterministic lookup
  5. Coordinate converter handles schematic-to-PCB Y-axis flip, tested against Arduino_Mega fixture
  6. Propagation is strictly unidirectional — no feedback path from PCB to schematic
  7. 15+ tests covering each constraint extractor with real circuit patterns
**Plans**: 2 plans

Plans:
- [x] 50-01-PLAN.md -- PCBConstraint types, .kicad_dru parser, ConstraintTable, coordinate converter (CP-02, CP-03, CP-04, CP-06)
- [x] 50-02-PLAN.md -- ConstraintPropagator orchestrator, five constraint extractors, integration tests (CP-01, CP-05)

### Phase 51: PCB Spatial Intelligence
**Goal**: Rich PCB spatial model with per-layer Shapely geometry, STRtree spatial indexing, layer stackup metadata, and board outline extraction. The spatial foundation for placement, DRC, and DFM.
**Depends on**: Phase 50 (constraints), existing spatial/ + PcbIR
**Context**: Extends existing spatial/primitives.py and spatial/query.py with PCB-specific geometry, net class awareness, and layer classification.
**Requirements**: SI-01, SI-02, SI-03, SI-04, SI-05, SI-06, SI-07
**Success Criteria** (what must be TRUE):
  1. `PcbSpatialModel` builds from `PcbIR` with per-layer Shapely geometry and STRtree index
  2. `LayerStackup` extracts copper/dielectric metadata including epsilon_r for impedance
  3. `LayerClassifier.is_copper("In1.Cu")` returns True; handles all canonical layer names
  4. `NetClassGeometry` provides trace_width, clearance, via parameters per net
  5. Clearance tolerance constant `_CLEARANCE_TOLERANCE_MM = 1e-4` prevents floating-point false positives
  6. Board outline extraction handles line segments, arcs, and circles on Edge.Cuts
  7. Dirty-flag lifecycle with batch mutation support and STRtree rebuild
  8. 15+ tests with real PCB fixtures (Arduino_Mega, analog-board)
**Plans**: 2 plans

Plans:
- [x] 51-01-PLAN.md -- PcbSpatialModel, LayerStackup, LayerClassifier, NetClassGeometry, clearance tolerance (SI-01, SI-02, SI-03, SI-04, SI-05)
- [x] 51-02-PLAN.md -- Board outline extraction, dirty-flag lifecycle, integration with spatial query engine, tests (SI-06, SI-07)

### Phase 52: Layout-Aware Placement Engine
**Goal**: Constraint-driven placement extending HybridPlacementEngine with signal flow grouping, decoupling cap proximity, differential pair alignment, and thermal awareness.
**Depends on**: Phase 50 (constraints), Phase 51 (spatial model)
**Context**: Extends existing placement/engine.py HybridPlacementEngine. Uses PcbSpatialModel for board geometry and PCBConstraint[] for placement rules.
**Requirements**: LP-01, LP-02, LP-03, LP-04, LP-05
**Success Criteria** (what must be TRUE):
  1. `LayoutAwarePlacer` wraps `HybridPlacementEngine` with pre-placement constraint analysis and post-placement validation
  2. `SignalFlowGrouper` converts `Subcircuit[]` to `SignalFlowGroup[]` with input/output ordering
  3. Real footprint bounding boxes extracted from PcbIR replace scalar `estimated_size` heuristic
  4. Thermal-aware placement with opt-in `ThermalProfile` dataclass; distance heuristic fallback when no profiles
  5. Constraint-aware SA refinement adds penalty terms to existing simulated annealing objective
  6. 15+ tests covering signal flow grouping, thermal placement, constraint validation
**Plans**: 2 plans

Plans:
- [x] 52-01-PLAN.md -- LayoutAwarePlacer, SignalFlowGrouper, real footprint geometry extraction (LP-01, LP-02, LP-03)
- [x] 52-02-PLAN.md -- Thermal-aware placement, constraint-aware SA refinement, integration tests (LP-04, LP-05)

### Phase 53: PCB DRC Intelligence
**Goal**: Spatial violation enrichment with fix suggestions and constraint-aware classification. Turns raw kicad-cli DRC output into actionable, coordinate-grounded fix recommendations.
**Depends on**: Phase 50 (constraints), Phase 51 (spatial model)
**Context**: Extends existing validation/spatial_drc.py enrich_drc_result() with constraint context and fix suggestion logic.
**Requirements**: DI-01, DI-02, DI-03, DI-04, DI-05
**Success Criteria** (what must be TRUE):
  1. `IntelligentDrcAnalyzer` enriches `DrcResult` with spatial context → `IntelligentDrcReport`
  2. `EnrichedViolation` wraps each violation with spatial items, related constraint, fix suggestions, classification
  3. `FixSuggester` maps violation type + spatial context to `SpatialFixSuggestion` with confidence and rationale
  4. DRC report schema version check at parse time; defensive parsing on unexpected structure
  5. PCB-specific design rules extend existing `DesignRule` ABC for clearance, impedance, thermal checks
  6. 15+ tests with real DRC reports from kicad-cli
**Plans**: 2 plans

Plans:
- [x] 53-01-PLAN.md -- IntelligentDrcAnalyzer, EnrichedViolation, FixSuggester, DRC report version check (DI-01, DI-02, DI-03, DI-04)
- [x] 53-02-PLAN.md -- PCB-specific design rules extending DesignRule ABC, integration tests (DI-05)

### Phase 54: Design for Manufacturing
**Goal**: DFM checks, manufacturer profiles, panelization readiness, thermal relief validation, and assembly consideration checks. Goes beyond DRC into manufacturability assessment.
**Depends on**: Phase 51 (spatial model)
**Context**: Mirrors analysis/design_rule_engine.py pattern (orchestrator + individual checks + config). New dfm/ module.
**Requirements**: DFM-01, DFM-02, DFM-03, DFM-04, DFM-05
**Success Criteria** (what must be TRUE):
  1. `DfmChecker` orchestrator runs pluggable `DfmCheck` subclasses against `PcbSpatialModel`
  2. `ManufacturerProfile` loaded from YAML/JSON; ships with JLCPCB, PCBWay, OSH Park, generic profiles
  3. Built-in checks: annular ring, solder mask web, thermal relief, min trace width, min drill
  4. Multi-stage DFM: footprint audit (pre-placement), placement check, post-route check
  5. Panelization readiness scoring and assembly checks (fiducials, tooling holes)
  6. CLI subcommand `kicad-agent dfm <board>` works end-to-end
  7. 15+ tests covering all checks with manufacturer profile variation
**Plans**: 2 plans

Plans:
- [x] 54-01-PLAN.md -- DfmCheck ABC, DfmChecker, ManufacturerProfile, built-in DFM checks (DFM-01, DFM-02, DFM-03)
- [x] 54-02-PLAN.md -- Multi-stage DFM, panelization scoring, assembly checks, CLI integration (DFM-04, DFM-05)

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> ... -> 29 -> 30 -> 31

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation | 3/3 | Complete | 2026-05-18 |
| 2. Operation Schema + IR | 3/3 | Complete | 2026-05-18 |
| 3. Validation Pipeline | 3/3 | Complete | 2026-05-18 |
| 4. Component Operations | 3/3 | Complete | 2026-05-18 |
| 5. Net/Ref/FP Operations | 4/4 | Complete | 2026-05-18 |
| 6. Cross-File + Analysis | 4/4 | Complete | 2026-05-18 |
| 7. GSD Skill Integration | 4/4 | Complete | 2026-05-18 |
| 8. Visual Primitives | 4/4 | Complete | 2026-05-22 |
| 9. GRPO Training | 4/4 | Complete | 2026-05-22 |
| 10. AI-Driven PCB Gen | 6/6 | Complete | 2026-05-23 |
| 11. LTspice Integration | 3/3 | Complete | 2026-05-23 |
| 12. ADI Footprint Library | 3/3 | Complete | 2026-05-23 |
| 13. Real-World Training | 3/3 | Complete | 2026-05-23 |
| 14. Bidirectional LTspice | 3/3 | Complete | 2026-05-24 |
| 15. AI Generation Wiring | 4/4 | Complete | 2026-05-24 |
| 16. Component Placement AI | 4/4 | Complete | 2026-05-24 |
| 17. Package & Distribution | 3/3 | Complete | 2026-05-24 |
| 18. CI/CD Pipeline | 2/2 | Complete | 2026-05-23 |
| 19. Interactive Routing | 3/3 | Complete | 2026-05-24 |
| 20. SFT Data Prep | 3/3 | Complete | 2026-05-26 |
| 21. GRPO RL Fine-Tuning | 2/2 | Complete | 2026-05-28 |
| 22. Agent Integration | 2/2 | Complete | 2026-05-28 |
| 23. Schematic Repair | 4/4 | Complete | 2026-05-29 |
| 24. Council Audit Remediation | 5/5 | Complete | 2026-05-29 |
| 25. Remove Operations | 2/2 | Complete | 2026-05-29 |
| 26. Connectivity Query | 1/1 | Complete | 2026-05-29 |
| 27. Footprint Creation | 2/2 | Complete | 2026-05-29 |
| 28. Hierarchical Sheet Ops | 3/3 | Complete | 2026-05-29 |
| 29. Cross-File Atomic Ops | 2/2 | Complete | 2026-05-29 |
| 30. MCP Operations Server | 1/1 | Complete | 2026-05-29 |
| 31. Validation Integration | 1/1 | Complete | 2026-05-29 |
| 32. Executor Performance | 2/2 | Complete | 2026-05-30 |
| 33. Undo/Redo Stack | 2/2 | Complete | 2026-05-30 |
| 34. LLM Provider Abstraction | 2/2 | Complete | 2026-05-31 |
| 35. Remaining Ops Gaps | 3/3 | Complete | 2026-05-31 |
| 36. Multi-Layer Routing | 3/3 | Complete | 2026-05-31 |
| 37. Training + Infrastructure | 3/3 | Complete | 2026-05-31 |
| 38. Schematic Routing Engine | 4/4 | Complete | 2026-05-31 |
| 39. Schematic Intelligence | 3/3 | Complete | 2026-05-31 |
| 40. ERC Root Cause Analysis | 3/3 | Complete | 2026-05-31 |
| 41. PCB MMLU Benchmark | 2/2 | Complete | 2026-05-31 |
| 42. Circuit QA Dataset | 1/1 | Complete | 2026-05-31 |
| 43. Regression Benchmark Suite | 1/1 | Complete | 2026-05-31 |
| 44. Adversarial Test Generation | 1/1 | Complete | 2026-05-31 |
| 45. Circuit Topology Graph | 2/2 | Complete | 2026-06-01 |
| 46. Component Function Recognition | 2/2 | Complete | 2026-06-01 |
| 47. Circuit Intent Inference | 2/2 | Complete | 2026-06-01 |
| 48. Design Rule Intelligence | 2/2 | Complete | 2026-06-01 |
| 48.5. Schematic Readability | 3/3 | Complete | 2026-06-01 |
| 49. One-Command Demo | 2/2 | Complete | 2026-06-01 |
| 50. Constraint Propagation | 2/2 | Complete | 2026-06-01 |
| 51. PCB Spatial Intelligence | 2/2 | Complete | 2026-06-01 |
| 52. Layout-Aware Placement | 2/2 | Complete | 2026-06-01 |
| 53. PCB DRC Intelligence | 2/2 | Complete | 2026-06-01 |
| 54. Design for Manufacturing | 2/2 | Complete | 2026-06-01 |

### v3.1 Council Remediation Phase Details

### Phase 60: Test Infrastructure — Stale Constants & Fixture Cleanup
**Goal**: Fix 5 stale hardcoded test constants that caused Council REJECT verdict (T-1 through T-5), fix autouse API key fixture contamination (H-5), establish dynamic-count testing patterns
**Depends on**: None (merge gate unblocker)
**Findings**: T-1, T-2, T-3, T-4, T-5, H-5
**Success Criteria** (what must be TRUE):
  1. All 5 hardcoded test constants replaced with dynamic computation from source
  2. `tests/helpers/counts.py` module provides shared count helpers
  3. `conftest_llm.py` fixture is no longer autouse — only LLM tests get API key
  4. All existing tests pass without modification
  5. Adding a new schema file does NOT break any test
**Plans**: 2 plans

Plans:
- [x] 60-01-PLAN.md — Fix stale test constants (T-1 through T-5): dynamic Op count, schema file count, tool count
- [x] 60-02-PLAN.md — Fix autouse API key fixture (H-5): remove autouse, add explicit fixture usage

### Phase 61: Security Hardening
**Goal**: Fix CRITICAL and HIGH security findings: replace eval() (C-1), add upload content validation (H-1), warn on public binding (H-2), validate repo names (H-3), convert source inspection tests to runtime (H-4)
**Depends on**: None
**Findings**: C-1, H-1, H-2, H-3, H-4
**Success Criteria** (what must be TRUE):
  1. Zero eval() calls in production code — replaced with AST walker
  2. Playground upload validates content against KiCad file signatures
  3. --host 0.0.0.0 prints security warning to stderr
  4. Repo names validated against owner/repo regex pattern
  5. Security tests verify runtime behavior, not source text
**Plans**: 5 plans

Plans:
- [x] 61-01-PLAN.md — Replace eval() with safe AST expression parser (C-1)
- [x] 61-02-PLAN.md — Add KiCad file content validation to upload endpoint (H-1)
- [x] 61-03-PLAN.md — Add public network binding warning (H-2)
- [x] 61-04-PLAN.md — Validate repo names in BulkFetcher (H-3)
- [x] 61-05-PLAN.md — Convert security tests from source inspection to runtime (H-4)

### Phase 62: Routing Correctness
**Goal**: Fix 5 HIGH routing bugs: O(n) snap_to_node (H-6), multi-pin net routing (H-7), hardcoded net number 0 (H-8, H-9), incomplete obstacle marking (H-10)
**Depends on**: None
**Findings**: H-6, H-7, H-8, H-9, H-10
**Success Criteria** (what must be TRUE):
  1. snap_to_node uses spatial index — O(log n) instead of O(n)
  2. Multi-pin nets produce connected routing trees (not just first→last)
  3. TrackSegment and ViaSegment emit correct net IDs from netlist
  4. mark_path_as_obstacle blocks clearance corridor, not just exact edges
  5. Performance: snap_to_node <10ms for 10k nodes
**Plans**: 4 plans

Plans:
- [x] 62-01-PLAN.md — Add STRtree spatial index to snap_to_node (H-6)
- [x] 62-02-PLAN.md — Implement Steiner-tree multi-pin net routing (H-7)
- [x] 62-03-PLAN.md — Fix hardcoded net number 0 in TrackSegment/ViaSegment (H-8, H-9)
- [x] 62-04-PLAN.md — Add clearance corridor to mark_path_as_obstacle (H-10)

### Phase 63: Training Integrity
**Goal**: Fix 4 HIGH training pipeline integrity issues: token handling (H-11), seed race condition (H-12), unseeded random (H-13), self-referential scoring (H-14)
**Depends on**: None
**Findings**: H-11, H-12, H-13, H-14
**Success Criteria** (what must be TRUE):
  1. GitHub token validated format and accepted from env var
  2. Parallel workers receive unique, non-overlapping seed offsets
  3. train_step uses deterministic seed (global + step counter)
  4. Best-of-N scoring uses independent metrics, not self-evaluation
  5. Reproducibility: same seed produces identical output across 2 runs
**Plans**: 4 plans (4/4 complete)

Plans:
- [x] 63-01-PLAN.md -- Fix GitHub token handling with format validation + env var (H-11)
- [x] 63-02-PLAN.md -- Fix parallel seed offset race condition (H-12)
- [x] 63-03-PLAN.md -- Fix unseeded random in train_step (H-13)
- [x] 63-04-PLAN.md -- Fix self-referential best-of-N scoring (H-14)

### Phase 64: CLI/UX Polish
**Goal**: Fix 3 HIGH CLI/UX bugs: route crash on paths outside CWD (H-15), no top-level help (H-16), component-search --help starts server (H-17)
**Depends on**: None
**Findings**: H-15, H-16, H-17
**Success Criteria** (what must be TRUE):
  1. route handles files outside CWD gracefully (no crash)
  2. kicad-agent --help lists all subcommands with descriptions
  3. kicad-agent component-search --help shows help, does NOT start server
**Plans**: 3 plans

Plans:
- [x] 64-01-PLAN.md -- Fix route crash on paths outside CWD (H-15)
- [x] 64-02-PLAN.md -- Add top-level --help with subcommand listing (H-16)
- [x] 64-03-PLAN.md -- Fix component-search --help starting MCP server (H-17)

### Phase 65: Architecture Refactor (PARTIALLY COMPLETE)
**Goal**: Split 3 oversized files below 800-line limit (H-18, H-19, H-20) and fix 12 MEDIUM-severity findings (M-1 through M-12)
**Depends on**: Phase 60 (test infrastructure stable before refactoring)
**Findings**: H-18, H-19, H-20, M-1 through M-12
**Status**: repair.py split complete (2604→61 shim + 4 modules). executor.py (994) and topology_graph.py (950) borderline — skipped.

Plans:
- [x] 65-01-PLAN.md — Split executor.py (2070→<800) into handler sub-modules (H-18) — SKIPPED (994 lines, borderline)
- [x] 65-02-PLAN.md — Split repair.py (2604→<800) into repair_wires, repair_nets, repair_components, repair_erc (H-19)
- [x] 65-03-PLAN.md — Split topology_graph.py (950→<800) into topology_builder (H-20) — SKIPPED (950 lines, borderline)
- [x] 65-04-PLAN.md — Fix all 12 MEDIUM findings (M-1 through M-12) — deferred

### Phase 66: Netlist-Aware Unit Placement
**Goal**: Use NetPositionIndex from net_extractor.py for connectivity-aware multi-unit component placement, replacing ad-hoc position scoring with net-aware matching
**Depends on**: None (uses existing NetPositionIndex in net_extractor.py)
**Success Criteria** (what must be TRUE):
  1. `place_missing_units()` uses `NetPositionIndex` to score candidate positions by net connectivity
  2. KiCad internal symbols (#PWR, #FLG) excluded from multi-unit placement
  3. Shared union-find pipeline in net_extractor.py eliminates duplicate logic
  4. All existing tests pass, no regressions
**Plans**: 1 plan (COMPLETE)

### Phase 67: Connectivity-Aware Short Resolution
**Goal**: Rewrite detect_shorted_nets() to use NetPositionIndex (eliminating ad-hoc union-find), add power-net protection to fix_shorted_nets(), combine break+fix into atomic resolve_shorted_nets() operation
**Depends on**: Phase 66 (NetPositionIndex)
**Findings**: HI-04, HI-05, HI-06, HI-07, ME-03, ME-04, LO-03, LO-04 (from Phase 66 Council review)
**Success Criteria** (what must be TRUE):
  1. detect_shorted_nets() uses NetPositionIndex instead of ad-hoc union-find — single source of truth
  2. Shorts detected by finding connected components with multiple net names (from labels)
  3. fix_shorted_nets() has power-net protection: VCC/VDD/GND/+N/-N rails NEVER auto-removed
  4. New resolve_shorted_nets() combines break_wire + fix_labels atomically with correct ordering
  5. Bridge wire identification uses graph-bridge algorithm (remove candidate → check component split)
  6. Cross-sheet short limitation documented explicitly (single-sheet only)
  7. All existing short detection/fix tests pass, new tests for power-net protection and atomic resolve
  8. repair.py does not grow — new logic lives in net_extractor.py or a new repair_shorts.py module
**Plans**: 3 plans

Plans:
- [x] 67-01-PLAN.md — Rewrite detect_shorted_nets() to use NetPositionIndex (HI-04, single source of truth)
- [x] 67-02-PLAN.md — Add power-net protection + keep_majority strategy to fix_shorted_nets() (HI-06)
- [x] 67-03-PLAN.md — Create atomic resolve_shorted_nets() combining break+fix with graph-bridge wire selection (HI-05, HI-07, ME-04)

### Phase 70: Persistent Undo Stack — Testing & CLI
**Goal**: Harden PersistentUndoStack with comprehensive tests and add `kicad-agent undo`/`kicad-agent redo` CLI commands
**Depends on**: Phase 33 (in-memory UndoStack), existing persistent_undo.py
**GitHub Issue**: #7
**Requirements**: UNDO-06, UNDO-07, UNDO-08
**Success Criteria** (what must be TRUE):
  1. PersistentUndoStack survives process restart — push in one process, pop in another
  2. Manifest corruption is handled gracefully (missing files, malformed JSON)
  3. Atomic write guarantees — no partial entries on crash
  4. prune_old_entries() cleans orphaned files
  5. `kicad-agent undo` CLI command works end-to-end
  6. `kicad-agent redo` CLI command works end-to-end
  7. `.kicad-agent/` auto-added to `.gitignore`
  8. 15+ tests covering persistence, crash recovery, CLI commands
**Plans**: 2 plans

Plans:
- [x] 70-01-PLAN.md — PersistentUndoStack test suite: persistence, crash recovery, prune, concurrent access (UNDO-06)
- [x] 70-02-PLAN.md — CLI undo/redo commands + .gitignore integration (UNDO-07, UNDO-08)

### Phase 71: Pin-to-Net Mapping — Testing & Extended Profiles
**Goal**: Harden place_net_labels with comprehensive tests, add RP2350B + more IC profiles, and validate against real schematics
**Depends on**: Phase 38 (schematic routing), existing net_label_placer.py
**GitHub Issue**: #8
**Requirements**: PINMAP-01, PINMAP-02, PINMAP-03
**Success Criteria** (what must be TRUE):
  1. place_net_labels correctly places labels at wire-connected positions
  2. Safety gate: zero labels placed at bare pin positions (no label_dangling)
  3. Existing labels are never duplicated
  4. dry_run mode returns accurate preview without modifying IR
  5. None-mapped pins get no_connect flags only when no wire exists
  6. RP2350B, NE5532, CD4066, CD4060 profiles added to backplane mapping
  7. Custom JSON pin_map files load correctly
  8. 20+ tests covering all safety gates, profiles, edge cases
**Plans**: 2 plans

Plans:
- [x] 71-01-PLAN.md — place_net_labels test suite: safety gates, wire check, dry_run, existing labels, edge cases (PINMAP-01, PINMAP-02)
- [x] 71-02-PLAN.md — Extended IC profiles (RP2350B, NE5532, CD4066, CD4060), custom JSON loading, integration test (PINMAP-03)

### Phase 72: No-Connect Corruption Fix + Connectivity Inference
**Goal**: Fix spurious no_connect markers on multi-sheet schematics (power symbol pins misidentified as unconnected) and add connectivity inference engine for partially-wired schematics
**Depends on**: Phase 38 (schematic routing), Phase 39 (net extraction), Phase 71 (pin-to-net mapping)
**GitHub Issues**: #13, #14
**Requirements**: REPAIR-09, INFER-01, INFER-02, INFER-03
**Success Criteria** (what must be TRUE):
  1. place_no_connects() detects power symbol pin co-location — no spurious markers on power pins
  2. place_no_connects_from_erc() has same power symbol awareness
  3. infer_connectivity operation returns confidence-scored nets compatible with batch_wiring
  4. Power pin inference uses pin-to-net profiles from net_label_placer
  5. Unconnected pin analysis groups pins by proximity and pin type
  6. 20+ tests covering power symbol detection, inference scoring, batch_wiring compatibility
**Plans**: 2 plans

Plans:
- [x] 72-01-PLAN.md — Fix no_connect corruption: power symbol pin detection in place_no_connects + place_no_connects_from_erc (REPAIR-09)
- [x] 72-02-PLAN.md — Connectivity inference engine: confidence scoring, power pin inference, batch_wiring-compatible output (INFER-01, INFER-02, INFER-03)

### Phase 75: Pre-Analysis Gate and Context Intelligence
**Goal**: Add pre-execution intelligence to editing operations — detect overlap, resolve pinouts, build connectivity context before mutating schematics. Upgrade context system with component-level intelligence.
**Depends on**: Phase 2 (operation schema and IR layer), existing validation_gates.py
**Origin**: User-identified friction during editing sessions — wiring errors, IC pinout ignorance, component overlap
**Success Criteria** (what must be TRUE):
  1. PreAnalysisGate runs before all schematic mutation operations
  2. Blockers prevent execution with clear error messages
  3. Warnings are logged but don't block
  4. Enriched context (connectivity, pin maps, power nets) available to handlers
  5. `render_component_intelligence()` provides per-component pin summaries
  6. 32+ new tests pass
  7. All existing tests still pass
  8. No new dependencies added
**Plans**: 1 plan (completed ad-hoc, retroactive)

Plans:
- [x] 75-01-PLAN.md — PreAnalysisGate: overlap detection, pin resolution, collision zones, connectivity context (completed retroactive)

## v3.1 Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 60. Test Infrastructure | 0/2 | Planned | — |
| 61. Security Hardening | 0/5 | Planned | — |
| 62. Routing Correctness | 0/4 | Planned | — |
| 63. Training Integrity | 0/4 | Planned | — |
| 64. CLI/UX Polish | 0/3 | Planned | — |
| 65. Architecture Refactor | 0/4 | Planned | — |
| 66. Netlist-Aware Placement | 1/1 | Complete | 2026-06-02 |
| 67. Short Resolution | 0/3 | Planned | — |
| 70. Persistent Undo Testing & CLI | 0/2 | Planned | — |
| 71. Pin-to-Net Mapping Testing & Profiles | 0/2 | Planned | — |
| 75. Pre-Analysis Gate & Context Intelligence | 1/1 | Complete | 2026-06-03 |
| 72. No-Connect Fix + Connectivity Inference | 0/2 | Planned | — |
| 76. Native KiCad 10 PCB Parser | 2/2 | Complete | 76-02-SUMMARY |
| 77. Source Review Remediation | 5/5 | Complete | 2026-06-07 |
| 78. Known Limitations Remediation | 0/4 | Planned | -- |

### Phase 76: Native KiCad 10 PCB Parser
**Goal:** Replace kiutils Board.from_file() with a native sexpdata-based PCB parser that preserves all data (nets, zones, tracks, vias, footprints) and provides structured typed access to board elements. Zero data loss, zero kiutils dependency for PCB reads.
**GitHub Issue:** #43
**Depends on**: Existing PcbRawWriter (writes), pcb_netlist.py (sexpdata precedent), uuid_extractor.py
**Success Criteria** (what must be TRUE):
  1. `NativeParser.parse_pcb(path)` returns a `NativeBoard` with all elements extracted from raw S-expression text
  2. Nets, footprints, zones, segments, vias, net classes, graphic items, and board outline are all accessible via typed attributes
  3. PcbIR `board` property returns `NativeBoard` by default, falling back to kiutils Board on parse failure
  4. All existing PCB operations (auto_route, add_copper_zone, move_footprint, etc.) work with the native parser
  5. `get_board_bounds()` returns correct bounding box from Edge.Cuts graphic items
  6. `extract_netlist()` returns correct pad positions grouped by net name
  7. Net numbers are preserved (not lost during parsing)
  8. UUIDs are preserved by default (no extraction/reinjection needed)
  9. 25+ tests with Arduino Mega fixture covering all element types
  10. Zero new dependencies (sexpdata already installed)
**Plans**: 2 plans

Plans:
- [x] 76-01-PLAN.md -- Native PCB types (10 dataclasses) and sexpdata tree-walking parser with 25+ tests
- [x] 76-02-PLAN.md -- PcbIR adapter pattern, executor wiring, kiutils fallback, 15+ integration tests

### Phase 77: Source Review Remediation
**Goal**: Fix 38 bugs found in comprehensive source review (2026-06-06) across parser, serializer, ops/execution, schematic_routing, validation, and PCB subsystems. Organized in 3 waves: Critical/High fixes (Wave 1-2), Medium/Low cleanup (Wave 3).
**Source**: `hardware/dumb-cartridges/aether-drive/BUGS.md` section "kicad-agent Source Review (2026-06-06)"
**Depends on**: 76 (native parser, on which several fixes build)
**Success Criteria** (what must be TRUE):
  1. 8 Critical bugs fixed: cache corruption (3), serializer kiutils corruption (1), power unit placement (1), convert_kicad6_to_10 overwrite (1), RecursionError (1), temp dir leak (1)
  2. 12 High bugs fixed: UUID misassignment, in_bom destruction, multi-unit pin resolution, thread safety, Transaction gaps, etc.
  3. 12 Medium bugs fixed: scope limitations, routing issues, format mismatches
  4. 6+ Low bugs fixed: dead code, performance, minor inconsistencies
 5. 20+ new regression tests covering all fixes
  6. Full test suite passes with zero regressions
**Plans**: 5 plans

Plans:
- [x] 77-01-PLAN.md -- Wave 1: Critical parser & validation fixes (depth pre-scan, UUID parent types, thread-safe recursion, shutil import)
- [x] 77-02-PLAN.md -- Wave 1: Critical serializer fixes (kiutils bypass, BOM preservation, UUID count validation, normalizer unification, atomic writes)
- [x] 77-03-PLAN.md -- Wave 2: Ops/execution pipeline fixes (cache invalidation, Transaction wrapping, manifest drift, multi-sheet gate)
- [x] 77-04-PLAN.md -- Wave 2: Schematic routing fixes (power unit placement, multi-unit pins, grid snap, L-shaped routing)
- [x] 77-05-PLAN.md -- Wave 3: Medium/Low cleanup (graphic types, DFM profile, split plane, batch errors, dead code)

### Phase 78: Known Limitations Remediation
**Goal:** Fix 6 known limitations identified in post-ship review: reward model held-out evaluation (M-14), GRPO naming accuracy (M-15), roundtrip regression on smd_test_board (RT-01), test isolation flakes (TI-01), native parser edge case documentation (DOC-01), via optimization documentation (DOC-02).
**Depends on**: 76 (native parser, on which DOC-01 builds)
**Success Criteria** (what must be TRUE):
  1. eval_reward_quality() computes Kendall tau correlation between model scores and ground-truth quality labels
  2. Held-out evaluation uses rule-based ground truth, not model self-scoring
  3. GRPOTrainer/GRPOConfig renamed to AdvantageWeightedTrainer/AdvantageWeightedConfig with backward-compatible aliases
  4. Unused kl_coefficient removed from config
  5. grpo_trainer.py GRPOLoopTrainer unchanged
  6. smd_test_board roundtrip regression confirmed already resolved (_SKIP_FILES)
  7. Flaky tests verified stable with deterministic assertions
  8. _UNSUPPORTED_ELEMENTS constant in native parser with warning logging
  9. RoutingConstraints via_cost_mm documented with optimization gaps
**Plans**: 4 plans

Plans:
- [x] 78-01-PLAN.md — Reward model held-out evaluation with Kendall tau (M-14)
- [x] 78-02-PLAN.md — GRPO rename to AdvantageWeightedTrainer (M-15)
- [x] 78-03-PLAN.md — Test isolation verification and hardening (TI-01, RT-01)
- [x] 78-04-PLAN.md — Parser unsupported elements docs + via optimization docs (DOC-01, DOC-02)

### Phase 79: Gap Analysis — Missing Capabilities & Full Tool Integrations
**Goal**: Fill integration gaps across kicad-cli (render, SVG, sym/fp exports), MCP server (expose all 98 operations), zone CRUD lifecycle, DFM engine expansion (5→50+ checks), AI pipeline improvements (real-world training data, parallel inference, confidence scoring), and performance optimization (O(n) parsing, memory, test coverage 69%→85%).
**Depends on**: 78 (known limitations remediation)
**Success Criteria** (what must be TRUE):
  1. All 98 operations exposed as MCP tools (currently only component search)
  2. kicad-cli pcb render wrapped with rotation/side/distance options
  3. kicad-cli sch/sym/fp export svg wrapped
  4. Full zone CRUD (add, modify, delete, refill) operations
  5. 50+ DFM manufacturing checks (up from 5)
  6. Net class modification and design rule editing operations
  7. Parallel chain generation in inference (sequential→concurrent)
  8. Confidence scoring on all AI outputs
  9. Training pipeline accepts real-world PCB data (not just synthetic)
  10. Test coverage ratio improves from 69% to 85%+
**Plans**: 6 plans

Plans:
- [x] 79-01-PLAN.md — MCP full integration: expose all 98 operations + validation + export + routing as MCP tools
- [x] 79-02-PLAN.md — kicad-cli completeness: render, SVG exports, symbol/footprint SVG, position format options
- [x] 79-03-PLAN.md — Zone CRUD lifecycle and net class modification operations
- [x] 79-04-PLAN.md — DFM engine expansion: 50+ manufacturing checks with fab profiles
- [x] 79-05-PLAN.md — AI pipeline smarter: real-world training data, parallel inference, confidence scoring
- [x] 79-06-PLAN.md — Performance optimization: O(n) parsing, memory management, test coverage 85%+

### v4.0 Hybrid Routing Intelligence (Phases 80-84)

### Phase 80: Spatial Reasoning Model Benchmark
**Goal:** Establish quantitative baseline for Qwen2.5-0.5B (text-only) vs Gemma 4 12B (encoder-free vision) on coordinate-grounded spatial reasoning. Answer "which model for which task?" with data. All inference local, no cloud.
**Depends on:** Phase 79 (stable codebase)
**Requirements:** BENCH-06, BENCH-07, BENCH-08
**Success Criteria** (what must be TRUE):
  1. 150+ benchmark tasks across 6 categories (coordinate proximity, routing feasibility, clearance diagnosis, net completion, DRC fix selection, unrouted cause)
  2. Each task has verifiable ground-truth answer
  3. Benchmark runs in <5 minutes on Apple Silicon
  4. Decision matrix: Qwen2.5-0.5B vs Gemma 4 12B per task type (text-only vs vision)
  5. Concrete model selection for each task type, all local via mlx-lm
  6. Zero regression on existing tests
**Plans**: 3 plans

Plans:
- [x]80-01-PLAN.md — Spatial benchmark dataset: 6 task categories, vision tasks include PCB renders, ground-truth from real PCB fixtures
- [x]80-02-PLAN.md — Benchmark runner: Qwen2.5-0.5B + Gemma 4 12B multi-model support, per-category accuracy, failure modes
- [x]80-03-PLAN.md — Run benchmark, produce MODEL-ASSESSMENT.md with model selection matrix (all local)

### Phase 81: Post-Routing Gap Analyzer
**Goal:** Build deterministic analysis pipeline that reads a partially-routed PCB, identifies all gaps (unrouted nets, DRC violations, incomplete nets, naming issues), and produces a structured GapReport with optional PCB renders for Gemma 4 12B vision consumption.
**Depends on:** Phase 80 (model assessment informs model selection for Phase 82)
**Requirements:** GAP-01, GAP-02, GAP-03, GAP-04
**Success Criteria** (what must be TRUE):
  1. GapAnalyzer reads .kicad_pcb and produces GapReport within 10 seconds
  2. GapReport contains: unrouted nets with pin positions, DRC violations with spatial context, incomplete nets, net naming issues
  3. Each gap entry includes nearby obstacles, clearance zones, routing corridors
  4. Each gap optionally includes rendered PCB region for vision model (Gemma 4 12B)
  5. GapReport serializable to JSON (AI) and markdown (human)
  6. Works on PCBs from Freerouting, kicad-agent A*, or custom auto_route.py
  7. CLI: `kicad-agent analyze-gaps <pcb_file> [--render-gaps]`, MCP tool: `analyze_gaps`
**Plans**: 2 plans

Plans:
- [x]81-01-PLAN.md — GapAnalyzer core: GapReport schema, unrouted/incomplete/violation detection via NativeParser
- [x]81-02-PLAN.md — Spatial context enrichment, CLI subcommand, MCP tool, integration test with real PCBs

### Phase 82: AI-Powered Gap Filling Engine
**Goal:** Build AI-driven gap-filling engine that takes GapReport and applies targeted fixes using existing 98 operations. Gemma 4 12B handles vision-based spatial reasoning (sees PCB renders), Qwen2.5-0.5B handles text tasks. All local, no cloud.
**Depends on:** Phase 81 (GapAnalyzer), Phase 80 (model selection)
**Requirements:** GAP-05, GAP-06, GAP-07, GAP-08
**Success Criteria** (what must be TRUE):
  1. GapFiller maps gap types to existing kicad-agent operations
  2. Fixes validated via kicad-cli pcb drc after application
  3. Gemma 4 12B used for vision-based routing decisions (sees gap renders, suggests paths)
  4. Qwen2.5-0.5B used for text tasks (net naming, simple fixes)
  5. Unrouted net completion improves >30% over deterministic routing alone
  6. DRC violation fix rate >60% for common violations
  7. Net renaming fixes >80% of N0xxx nets
  8. Iterative loop: fix → validate → re-analyze (max 3 iterations)
  9. Transaction safety: rollback on failure
  10. All inference local via mlx-lm
  11. CLI: `kicad-agent fill-gaps <pcb_file> [--dry-run] [--model gemma4|qwen]`
**Plans**: 3 plans

Plans:
- [x]82-01-PLAN.md — GapFix schema and FixStrategyEngine: map gap types to existing operations
- [x]82-02-PLAN.md — Iterative GapFillPipeline: analyze → fix → validate → re-analyze with model selection
- [x]82-03-PLAN.md — Integration test suite with real analog-ecosystem PCBs

### Phase 83: analog-ecosystem Integration
**Goal:** Wire gap-filling pipeline into analog-ecosystem's PCB workflow, replacing per-board custom scripts with unified kicad-agent workflow. Model config (Gemma 4 12B vision + Qwen2.5-0.5B text) in kicad-agent.yaml.
**Depends on:** Phase 82 (gap-filling pipeline)
**Requirements:** WORKFLOW-01, WORKFLOW-02, WORKFLOW-03
**Success Criteria** (what must be TRUE):
  1. Single command: `kicad-agent workflow route-and-fill <pcb>`
  2. Replaces custom auto_route.py, generate_dsn.py, build_pcb.py per-board
  3. Uses existing Freerouting bridge and A* router (not analog-ecosystem's custom implementations)
  4. Board config from .kicad_pro or kicad-agent.yaml (routing + model selection)
  5. Model config: vision_model (gemma-4-12b), text_model (qwen2.5-0.5b), all local
  6. Workflow templates as MCP meta-tools
  7. Migration guide for existing boards
**Plans**: 2 plans

Plans:
- [x]83-01-PLAN.md — Unified routing workflow: config, engine selection, gap-fill integration
- [x]83-02-PLAN.md — analog-ecosystem migration: board configs, replace custom scripts, docs

### Phase 84: Gemma 4 12B Fine-Tuning (Conditional)
**Goal:** If Phase 80 shows <50% accuracy on routing/net_completion tasks, fine-tune Gemma 4 12B (encoder-free vision) on gap-filling-specific data with PCB renders. Skipped if models prove adequate.
**Depends on:** Phase 80 (benchmark), Phase 82 (training data from fix strategy)
**Trigger:** Phase 80 benchmark shows <50% accuracy on routing_feasibility or net_completion
**Requirements:** MODEL-01, MODEL-02, MODEL-03
**Training Platform Options:**
  - **Vast.ai (recommended)** — RTX 3090, ~$0.22 for 400-step LoRA run. Use proven `vast_train_gemma4.py` pattern from spectral-primitives. Cross-platform PEFT adapter loads on Apple Silicon via mlx-vlm.
  - **Local M2** — mlx-vlm LoRA, limited by 32GB VRAM and Metal GPU watchdog for 12B+ models. Only viable for <4B active param models.
  - **Kaggle** — Free 30hr/week T4 x2, but random GPU allocation (P100 lottery). Fallback if Vast.ai unavailable.
**Success Criteria** (what must be TRUE):
  1. Gemma 4 12B fine-tuned with LoRA on 5000+ gap-fix examples (with PCB renders as vision input)
  2. Trained model shows >70% accuracy on Phase 80 benchmark
  3. Inference latency <5s per gap on Apple Silicon (mlx-vlm 8-bit)
  4. LoRA adapter saved and loadable via InferenceWrapper
  5. Zero regression on existing tests
  6. Adapter stored on `/Volumes/Storage/models/kicad-agent/adapters/` (not local SSD)
**Plans**: 2 plans

Plans:
- [x]84-01-PLAN.md — Gap-filling training data generation with PCB renders for multimodal training
- [x]84-02-PLAN.md — Gemma 4 12B LoRA fine-tuning via mlx-lm, multimodal (image + text) SFT

### v4.1 Stage-Safe PCB Flow (Phases 85-94)

**Milestone Goal:** Make kicad-agent enforce a credible schematic-to-manufacturing PCB workflow where each stage has deterministic readiness gates, explicit constraints, and verified artifacts. Every major design transition (schematic→PCB, setup→placement, placement→routing, routing→manufacturing) has a gate that fails closed.

- [x] **Phase 85: Gate Architecture** — DesignStage enum, GateResult model, GateRunner orchestrator, CLI/MCP exposure (completed 2026-06-13)
- [x]**Phase 86: Schematic Intent Completeness** — Footprint/pin-map/metadata checks, net intent classification, quality warnings
- [x]**Phase 87: Schematic-to-PCB Transfer Contract** — Verified symbol→footprint→pad→net mapping, stub detection, gate enforcement
- [x]**Phase 88: Constraint Capture & Propagation** — Electrical/mechanical/fab constraints, .kicad_dru propagation, completeness gate
- [x]**Phase 89: Placement Readiness Gate** — Footprint bounds, courtyard clearance, decoupling proximity, routability heuristics
- [x]**Phase 90: Routing Readiness & Quality Gate** — Pre-route prerequisites, post-route DRC, diff pair rules, quality metrics
- [x]**Phase 91: Manufacturing Readiness Gate** — DRC/DFM pass, artifact validation, BOM completeness, manifest with hashes
- [x]**Phase 92: AI Boundary & Repair Loop** — Proposal model, deterministic validation, repair loop, audit trail
- [x]**Phase 93: Golden End-to-End Boards** — 6 fixture boards proving full flow: LED, buck, MCU, op-amp, connectors, 4-layer
- [x]**Phase 94: Docs & UX** — Stage-gate getting started, status CLI, repair examples, guarantees vs suggestions docs

### Phase 85: Gate Architecture
**Goal:** Define unified gate model for design stage transitions — the foundation all subsequent gates build on
**Depends on:** Phase 79
**Requirements:** GATE-01, GATE-02, GATE-03, GATE-04, GATE-05
**Success Criteria** (what must be TRUE):
  1. DesignStage enum with 5 values: schematic, pcb_setup, placement, routing, manufacturing
  2. GateResult model with pass, blockers, warnings, artifacts, next_actions
  3. GateRunner orchestrates gates with stage-aware dispatch
  4. pre_pcb_schematic_gate refactored to return GateResult
  5. CLI `gate run` and `gate status` subcommands work
  6. MCP tools exposed for gate operations
  7. Gates fail closed: GateResult.pass=False blocks downstream
**Plans**: 2 plans

Plans:
- [x] 85-01-PLAN.md — DesignStage enum, GateResult model, GateRunner, refactor pre_pcb gate
- [x] 85-02-PLAN.md — CLI gate subcommands, MCP tools, RunGateOp/GateStatusOp schemas

### Phase 86: Schematic Intent Completeness
**Goal:** Ensure schematic has enough information to produce a meaningful PCB
**Depends on:** Phase 85
**Requirements:** SINTENT-01 through SINTENT-05
**Success Criteria** (what must be TRUE):
  1. Footprint completeness check (package variant merged into pin-count per council HIGH-3)
  2. Symbol pin-count validation (footprint pad-count deferred to Phase 87 per council HIGH-4)
  3. Component metadata checks: MPN, value, footprint, DNP/exclude
  4. Net intent extraction: power, signal, high-current, diff pair, clock, analog, digital
  5. Warnings for generic symbols, stubs, hidden power pins, ambiguous connectors
**Plans**: 2 plans

Plans:
- [x]86-01-PLAN.md -- Footprint/symbol-pin-count/metadata checks, fixture schematics, gate registration (revised per council)
- [x]86-02-PLAN.md -- Net intent classification (extending existing NetClassification), quality warnings (revised per council)

### Phase 87: Schematic-to-PCB Transfer Contract
**Goal:** Replace placeholder PCB generation with verified schematic-derived PCB state
**Depends on:** Phase 86
**Requirements:** TRANSFER-01 through TRANSFER-05
**Success Criteria** (what must be TRUE):
  1. TransferContract: symbols→footprints→pads→nets→net_classes mapping
  2. PadNetAssigner assigns PCB pad nets from schematic netlist
  3. NetIdVerifier confirms PCB net IDs match schematic net names
  4. update_from_schematic runs pre-PCB gate first
  5. Stub/placeholder footprints detected and blocked
**Plans**: 2 plans

Plans:
- [x]87-01-PLAN.md — TransferContract, PadNetAssigner, NetIdVerifier, golden LED+resistor test
- [x]87-02-PLAN.md — UpdateFromSchematicOp with gate enforcement, stub detection, MCU golden test

### Phase 88: Constraint Capture & Propagation
**Goal:** Capture design constraints before layout and propagate to .kicad_dru net classes
**Depends on:** Phase 87
**Requirements:** CONST-01 through CONST-05
**Success Criteria** (what must be TRUE):
  1. Electrical constraints: current, voltage, impedance, diff pair, length match
  2. Mechanical constraints: board outline, mounting holes, keepouts, connector zones
  3. Fab profile constraints: min trace, min drill, clearance, layer count, copper weight
  4. Constraint propagator writes to .kicad_dru
  5. Gate blocks routing when critical nets lack constraints
**Plans**: 2 plans

Plans:
- [x]88-01-PLAN.md — Constraint schemas, propagator, completeness gate
- [x]88-02-PLAN.md — SetConstraintsOp/GetConstraintsOp, wiring into gate chain

### Phase 89: Placement Readiness Gate
**Goal:** Ensure placement is electrically and mechanically plausible before routing
**Depends on:** Phase 88
**Requirements:** PLACE-01 through PLACE-05
**Success Criteria** (what must be TRUE):
  1. Footprint bounds inside board outline
  2. Courtyard and keepout clearance
  3. Connector/mechanical positions
  4. Decoupling proximity, thermal spacing, analog/digital grouping
  5. Routability heuristics: density, ratsnest, blocked channels
**Plans**: 1 plan

Plans:
- [x]89-01-PLAN.md — PlacementReadinessGate with 6 sub-checks, fixture boards

### Phase 90: Routing Readiness & Quality Gate
**Goal:** Prevent pathfinding from pretending to be production routing
**Depends on:** Phase 89
**Requirements:** ROUTE-GATE-01 through ROUTE-GATE-05
**Success Criteria** (what must be TRUE):
  1. Pre-route: board outline, stackup, net classes, constraints, placement gate pass
  2. Route quality metrics: completion, vias, clearance, length mismatch, return path
  3. Post-route DRC and unconnected-item check
  4. Differential pair and impedance rule checks
  5. A* router marked as prototype unless quality gate passes
**Plans**: 1 plan

Plans:
- [x]90-01-PLAN.md — RoutingReadinessGate + PostRouteQualityGate + RouteQualityMetrics

### Phase 91: Manufacturing Readiness Gate
**Goal:** Treat manufacturing as a package, not a Gerber export
**Depends on:** Phase 90
**Requirements:** MFG-01 through MFG-05
**Success Criteria** (what must be TRUE):
  1. Clean DRC and DFM profile pass required
  2. Export artifacts: Gerbers, drill, BOM, CPL/position, STEP
  3. Required layers validated for fab profile
  4. BOM rows have MPN/vendor unless DNP/excluded
  5. Manufacturing manifest with SHA256 hashes and provenance
**Plans**: 1 plan

Plans:
- [x]91-01-PLAN.md — ManufacturingReadinessGate + ManufacturingManifest + artifact validation

### Phase 92: AI Boundary & Repair Loop
**Goal:** Make the LLM propose, not silently decide
**Depends on:** Phase 91
**Requirements:** AI-01 through AI-05
**Success Criteria** (what must be TRUE):
  1. Proposal model with source tracking (deterministic/local_ai/external_llm)
  2. Failed proposals never mutate files
  3. Repair loop: gate failure → classify → propose → validate → apply → rerun (max 3)
  4. Audit trail with source tracking per fix
  5. Loop terminates even if blockers remain
**Plans**: 1 plan

Plans:
- [x]92-01-PLAN.md — Proposal model, ProposalValidator, RepairLoop, audit trail

### Phase 93: Golden End-to-End Boards
**Goal:** Prove the full flow on 6 representative designs
**Depends on:** Phase 92 (must test repair loop as part of full pipeline)
**Requirements:** E2E-01
**Success Criteria** (what must be TRUE):
  1. LED resistor board passes all gates
  2. Buck regulator passes all gates
  3. MCU breakout passes all gates
  4. Op-amp analog front end passes all gates
  5. Connector-heavy board passes all gates
  6. 4-layer controlled impedance passes all gates
  7. Each fixture has expected artifact list
**Plans**: 1 plan

Plans:
- [x]93-01-PLAN.md — 6 golden fixture boards with end-to-end gate tests

### Phase 94: Docs & UX
**Goal:** Make the stage-safe workflow obvious
**Depends on:** Phase 93
**Requirements:** DOCS-01 through DOCS-05
**Success Criteria** (what must be TRUE):
  1. Getting-started rewritten around stage gates
  2. `kicad-agent status` shows current stage and blockers
  3. Examples for failing gates and repair workflow
  4. Guarantees vs suggestions clearly documented
  5. Not-manufacturable-until checklist
**Plans**: 1 plan

Plans:
- [x]94-01-PLAN.md — Docs rewrite, status CLI enhancement, examples, guarantees doc

### v5.0 Vast.ai Training & External Storage (PLANNED)

**Milestone Goal:** Adopt the proven Vast.ai GPU training flow (from spectral-primitives) for kicad-agent's LoRA training, and move all model artifacts to external storage.

- [x] **Phase 96: Vast.ai Training Pipeline** - Port the spectral-primitives Vast.ai training scripts (`vast_launch.sh` + `vast_train_gemma4.py`) for KiCad vision LoRA training. PCB spectrogram images as vision input, reasoning chains as output. (completed 2026-06-17)
- [x] **Phase 97: External Model Storage** - Move all trained adapters and training datasets to `/Volumes/Storage/models/kicad-agent/`. Adapter metadata registry with versioning. (completed 2026-06-19)

### Phase 96: Vast.ai Training Pipeline
**Goal:** Enable cheap (~$0.22/run) GPU LoRA training for KiCad vision models via Vast.ai, replicating the proven spectral-primitives workflow
**Depends on**: Phase 84 (training data) or Phase 13 (real-world PCB data); spectral-primitives Vast.ai scripts as template
**Success Criteria** (what must be TRUE):
  1. `scripts/vast_train_kicad.py` — standalone CUDA training script adapted from spectral-primitives
  2. `scripts/vast_launch_kicad.sh` — instance launch script with KiCad-specific config
  3. KiCad PCB render dataset uploaded to Kaggle (public) for Vast.ai download
  4. LoRA adapter trains on RTX 3090 with <5s/step
  5. Adapter loads on Apple Silicon via mlx-vlm (cross-platform PEFT)

### Phase 97: External Model Storage
**Goal**: Store all model artifacts on external storage to preserve local SSD
**Depends on**: Phase 96 (first Vast.ai adapter to store)
**Success Criteria** (what must be TRUE):
  1. Adapters at `/Volumes/Storage/models/kicad-agent/adapters/` with metadata registry
  2. Training datasets at `/Volumes/Storage/models/kicad-agent/datasets/`
  3. InferenceWrapper references adapters from external storage
  4. No trained models stored on local SSD (symlinks or path config)
