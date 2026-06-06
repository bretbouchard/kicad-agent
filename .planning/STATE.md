---
gsd_state_version: 1.0
milestone: v3.1
milestone_name: Council Remediation
status: execute
stopped_at: Completed Phase 63 - Training Integrity (all plans)
last_updated: "2026-06-06T19:14:00Z"
last_activity: 2026-06-06
progress:
  total_phases: 76
  completed_phases: 59
  total_plans: 233
  completed_plans: 164
  percent: 70
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-01)

**Core value:** LLM -> intent JSON -> AST mutation -> valid KiCad file. Zero corruption, every time.
**Current focus:** All milestones shipped. Ready for next milestone planning.
Last activity: 2026-06-01

## Current Position

**All milestones complete (v1.0 through v3.0). 54 phases, 143 plans, 3171+ tests.**

Last milestone: v3.0 Full-Stack EDA (Phases 50-54)
- Phase 50: Constraint Propagation (81 tests)
- Phase 51: PCB Spatial Intelligence (51 tests)
- Phase 52: Layout-Aware Placement (41 tests)
- Phase 53: PCB DRC Intelligence (56 tests)
- Phase 54: Design for Manufacturing (62 tests)
Council review: 4 findings fixed, all passing.

Last activity: 2026-06-01

### Phase 62: Routing Correctness (v3.1)

- Plan 62-01: STRtree spatial index for snap_to_node (H-6) (COMPLETE)
  - Per-layer STRtree indexes with lazy rebuild via _node_index_dirty flag
  - O(log n) nearest-neighbor lookup replacing O(n) linear scan
  - 5 new tests in TestSpatialIndexSnap

- Plan 62-02: Multi-pin Steiner tree routing (H-7) (COMPLETE)
  - Sequential nearest-neighbor heuristic for 3+ pin nets
  - route_all_nets dispatches 2-pin and multi-pin nets separately
  - 4 new tests in TestMultiPinRouting

- Plan 62-03: Fix hardcoded net number 0 (H-8, H-9) (COMPLETE)
  - net_id field on TrackSegment/ViaSegment with net_id_map propagation
  - S-expression format: (net {id} "{name}") with proper KiCad net IDs
  - 5 new tests in TestNetIds

- Plan 62-04: Clearance corridor in mark_path_as_obstacle (H-10) (COMPLETE)
  - _mark_clearance_corridor() uses STRtree for O(W * log N) edge proximity scan
  - _point_to_segment_distance() helper for edge distance checks
  - 7 new tests in TestClearanceCorridor + TestPointToSegmentDistance

### Phase 63: Training Integrity (v3.1)

- Plan 63-01: Fix GitHub Token Handling (H-11) (COMPLETE)
  - _resolve_github_token() with regex validation for all 5 GitHub token prefixes
  - Environment variable fallback (GITHUB_TOKEN), explicit param takes precedence
  - SEC-1: error messages hide actual token content
  - 15 new tests in TestResolveGitHubToken

- Plan 63-02: Fix Parallel Seed Offset (H-12) (COMPLETE)
  - Per-worker seed offsets with 1M spacing: seed_base + worker_id * _SEED_SPACING
  - Overlap assertion raises ValueError for misconfiguration
  - 4 new tests in TestParallelSeedOffset

- Plan 63-03: Fix Unseeded Random in train_step (H-13) (COMPLETE)
  - GRPOTrainer._step_counter initialized to 0, incremented per step
  - RNG seeded with config.seed + _step_counter for deterministic training
  - GRPOConfig.seed defaults to 42
  - 6 new tests in TestGRPOSeededRandom

- Plan 63-04: Fix Self-Referential Best-of-N (H-14) (COMPLETE)
  - _independent_score() uses format + step count heuristics (no model self-ref)
  - generate() accepts optional reference_model for external neural scoring
  - 50/50 heuristic/neural blend when reference model provided
  - 12 new tests in TestIndependentScore + TestRewardModelGenerate

### Phase 61: Security Hardening (v3.1)

- Plan 61-01: Replace eval() with safe AST parser (C-1) (COMPLETE)
  - Replaced eval() in circuit_templates.py with AST-walking predicate evaluator
  - Supports comparison, arithmetic, boolean operators; rejects imports/calls/attribute access
  - 12 new tests in TestSafePredicateEvaluator

- Plan 61-02: Upload content validation (H-1) (COMPLETE)
  - Added _validate_content() checking file bytes against KiCad S-expression signatures
  - Rejects non-KiCad content declared as KiCad types; allows empty templates
  - 6 new tests in TestUploadContentValidation

- Plan 61-03: Public network binding warning (H-2) (COMPLETE)
  - Added stderr warning when playground binds to 0.0.0.0 or ::
  - 2 new tests in TestPublicBindingWarning

- Plan 61-04: Repo name validation (H-3) (COMPLETE)
  - Added _REPO_NAME_RE regex and validation in BulkFetcher._repo_dir()
  - Rejects path traversal, Unicode separators, oversized names
  - 7 new tests in TestRepoNameValidation

- Plan 61-05: Runtime security tests (H-4) (COMPLETE)
  - Converted inspect.getsource() tests to runtime OperationExecutor.execute() tests
  - All 19 security hardening tests + 27 Phase 61 tests passing

### Phase 60: Test Infrastructure (v3.1)

- Plan 60-01: Fix stale test constants T-1 through T-5 (COMPLETE)
  - Created tests/helpers/counts.py with dynamic count_op_classes(), count_schema_files(), count_operation_tools()
  - Refactored test_slc_compliance.py, test_code_quality.py, test_edit_server.py to use shared helpers
  - All 5 hardcoded constants eliminated; counts derive from source

- Plan 60-02: Fix autouse API key fixture H-5 (COMPLETE)
  - Verified autouse=True already removed from conftest_llm.py
  - Created test_fixture_isolation.py with regression tests (positive/negative verification)
  - 2 new tests, 114 total Phase 60 tests passing

### Phase 76: Native KiCad 10 PCB Parser (v3.1)

- Plan 76-01: NativeBoard dataclass types and sexpdata-based parser (COMPLETE)
  - 13 mutable dataclasses + _NativePosition NamedTuple in pcb_native_types.py
  - NativeParser with parse_pcb()/parse_pcb_content() and depth pre-scan (CRITICAL-1)
  - Kiutils-compatible properties: graphicItems, traceItems, layers, zone.tstamp/net/netName/minThickness
  - 6 graphic item types (line/arc/circle/rect/poly/curve), np_thru_hole pad type, pinfunction/pintype
  - 68 tests, all passing. Zero kiutils imports, zero new dependencies.

- Plan 76-02: Wire NativeParser into PcbIR and executor (COMPLETE)
  - PcbIR.from_native() creates NativeBoard-backed IR without UUID map requirement
  - _is_native branching in all 8 mutation/query methods (add_net, remove_net, rename_net, swap_footprint, get_net_pads, get_footprint_pads, get_board_bounds, extract_netlist)
  - Executor dual-parser: native for reads, kiutils for serialization (zero regression)
  - _try_native_parse() with Exception catch per CRITICAL-1
  - 41 integration tests, all passing. 73 total (adapter + pcb_ops + handler), zero regression.

  - Code review fixes (3 HIGH findings addressed):
    - HIGH-1: update_footprint_from_library() native path (was only mutation method missing _is_native branch)
    - HIGH-2: External consumers (extractor, graph_builder, spatial_drc) duck-typed for tuple positions
    - HIGH-3: CacheEntry stores native_board; cache hits preserve native parser benefit
    - 185 total tests passing after fixes, zero regression

### Phase 75: Pre-Analysis Gate & Context Intelligence (v3.1)

- Plan 75-01: PreAnalysisGate, executor wiring, context upgrade (COMPLETE, retroactive)
  - PreAnalysisGate with overlap detection, collision zones, pin resolution, wire collision check
  - Tiered enforcement: blockers prevent execution, warnings log but proceed
  - render_component_intelligence() with per-component pin maps, connectivity, power nets
  - Wired into executor._execute_schematic() and execute_batch() validation loop
  - 32 new tests, all passing. No new dependencies.

### Phase 47: Circuit Intent Inference

- Plan 47-01: IntentInference, DesignIntent schemas (COMPLETE)
  - IntentInferrer with 15 ordered intent rules (THAT4301, NE5532, CD4066, CD4060, LM358, etc.)
  - DesignIntent and SubcircuitIntent Pydantic schemas with validation
  - DesignGoal enum with 9 categories
  - Signal flow generation with arrow notation: "Input -> VCA -> Output"
  - InferenceResult frozen dataclass with rule_matched and timing
  - 27 TDD tests, 244 total analysis tests pass

- Plan 47-02: DesignReviewer, design review engine (COMPLETE)
  - DesignReviewer with 5 deterministic template-based review checks
  - DesignFinding and DesignReview Pydantic schemas with auto-computed summary
  - ReviewSeverity (INFO, SUGGESTION, WARNING, CRITICAL) and ReviewCategory enums
  - Bypass cap detection, feedback compensation, power decoupling, input protection
  - Intent-aware severity escalation (CRITICAL for audio ICs)
  - 15 TDD tests, 143 total analysis tests pass

## Previous Milestone (v3.0 Full-Stack EDA)

**Final: 54/54 phases complete. 143 plans, 3171+ tests, constraint propagation, spatial intelligence, layout-aware placement, DRC intelligence, DFM.**

## Previous Milestone (v2.4 Schematic Intelligence)

**Final: 40/40 phases complete. 85 operations, 2343+ tests, structured logging, training infra, schematic routing.**

## Previous Milestone (v2.4 production-hardening)

**Final: 37/37 phases complete. 74 operations, 1900+ tests, structured logging, training infra.**

## Performance Metrics

**Velocity:**

- Total plans completed: 149
- Average duration: 5 min
- Total execution time: 6.5 hours

**Recent Trend:**

- Last 10 plans: 50-01 through 54-02 (all first-execution pass)
- Trend: Stable -- all plans passing on first execution

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [v2.4]: File content snapshots for undo (not Operation objects -- re-execution produces different UUIDs)
- [v2.4]: collections.deque(maxlen=N) for bounded O(1) undo stack
- [v2.4]: Per-executor undo stack keyed by resolved file path
- [v2.4]: Standard undo/redo semantics (new operation clears redo stack)
- [v2.4]: Session-scoped undo (lost on MCP server restart, same as KiCad)
- [v2.4]: LLMProvider protocol is superset of LLMBackend -- providers satisfy both protocols
- [v2.4]: Provider selection via KICAD_LLM_PROVIDER env var (default "anthropic")
- [v2.4]: Lazy LLMClient imports in consumers to avoid hard anthropic dependency
- [v2.4]: ModifyNetClassOp uses Optional[float] fields for partial updates (None=keep existing)
- [v2.4]: write_project_settings operates on raw JSON dict to preserve unknown keys
- [v2.4]: List handlers are read-only (no serialize), returning {items, count}
- [v2.4]: Atomic write via tempfile+os.replace for .kicad_pro (Council FE-02)
- [v2.4]: erc_auto_fix meta-op chains parse_erc to violation dispatch with iteration control (GEN-03)
- [v2.4]: parse_erc imported at module level in erc_auto_fix.py for test mockability
- [v2.4]: validate_power_nets function defaults check_hierarchical=False for backward compat; schema defaults True
- [v2.4]: _check_hierarchical_power reuses sheet traversal pattern from check_sheet_pin_labels
- [v2.4]: modify_copper_zone resolves net via get_net_by_name or creates new net if not found
- [v2.4]: remove_copper_zone prefers UUID lookup, falls back to index, raises ValueError if neither provided
- [v2.4]: Council H-01 fix: 6 repair ops added to schema union -- was 68, now 74
- [v2.4]: Council H-02 fix: ModifyProjectSettingsOp.updates bounded to max_length=50
- [v2.4]: Council M-04 fix: ModifyCopperZoneOp.layer validated with pattern r"^[FB]\.Cu|In[1-9]\d*\.Cu$"
- [v2.4]: Council L-03 fix: RemoveCopperZoneOp has model_validator requiring at least one of zone_uuid/zone_index
- [v2.4-SI]: Plans build on existing schematic_routing/ module (SchematicGraph, wire_router, batch_executor, netlist_parser)
- [v2.4-SI]: Schemas in _schema_schematic_routing.py and _schema_schematic_intel.py (new files)
- [v2.4-SI]: Schematic ops extend existing @register_schematic pattern in executor.py
- [v2.4-SI]: PinResolver uses unit-aware lib symbol indexing via _build_unit_index() for multi-unit IC pin resolution
- [v2.4-SI]: Collision zones use >=2 pins threshold (not >=2 refs) -- vertical wire through IC pin column shorts all pins regardless of component count
- [v2.4-SI]: Pin overlap severity: error (different nets from netlist), warning (same net or unknown) -- defaults to warning without netlist
- [v2.4-SI]: Net labels placed at pin body_position (not wire endpoint) for visual clarity and guaranteed connectivity
- [v2.4-SI]: L-shaped wires use horizontal-first path; collision zone check covers full segment range
- [v2.4-SI]: BatchWiring uses kiutils from_file/to_file for element stripping (not raw S-expression manipulation)
- [v2.4-SI]: Auto-detection of collision zones inside batch_connect when none explicitly provided
- [v2.4-SI]: regenerate_wiring strips wires/labels/no_connects via kiutils, reconnects via NetConnector per-net
- [v2.4-SI]: Voltage pattern regex matches both +3.3V and +3V3 KiCad power naming conventions
- [v2.4-SI]: Power convention detection uses pin_name only, not lib_id -- SchematicGraph filters power symbols
- [v2.4-SI]: Passive components identified by lib_id containing Device:R, Device:C, Device:L
- [v2.4-SI]: Violation classification uses _CLASSIFICATION_RULES ordered list (match_fn, category, root_cause, confidence) -- first match wins
- [v2.5-45]: Shared types.py for NetClassification/PinRole enums prevents circular imports between topology_graph and net_classifier
- [v2.5-45]: Union-Find with path compression for net resolution -- BFS wire tracing failed on multi-hop pin chains without labels
- [v2.5-45]: Ordered list (not dict) for _LIBID_TYPE_MAP to handle prefix ordering (LED before L, Crystal before C)
- [v2.5-45]: Feedback edges reclassified from any non-POWER classification, not just SIGNAL
- [v2.5-45]: SignalIntegrity rules reuse existing _CLOCK_PATTERNS and _CONTROL_PATTERNS (no duplication)
- [v2.5-45]: NetStats.is_stub detects diode, connector, misc components as dead-ends plus non-forward-adjacency
- [v2.5-45]: NetStats.is_multi_drop requires 2+ receiver ICs (not passive components)
- [v2.5-45]: Signal integrity rules stored as class-level _si_rules for extensibility matching _rules pattern
- [v2.5-46]: BFS clustering does not traverse through ICs -- each IC forms its own subcircuit
- [v2.5-46]: PREAMP rule requires resistor_count >= 2 to distinguish from OUTPUT_STAGE
- [v2.5-46]: Feature extraction as standalone _extract_features method for Plan 46-02 reuse
- [v2.5-46]: SubcircuitFeatures has 26 fields (subcircuit_id + 25 feature fields) for ML-ready vectors
- [v2.5-46]: Features dict merges ML fields (SubcircuitFeatures.to_dict) with legacy classifier fields (_extract_features) for backward compatibility
- [v2.5-46]: ClassificationResult.feature_vector populated only for confidence < 0.5 to minimize storage while capturing ML training data
- [v2.5-46]: extract_features accepts optional input_nets/output_nets set parameters for topology-level signal counting
- [v2.5-47]: Intent rule overall_type propagated directly from matched rule, not re-derived from function name
- [v2.5-47]: Signal flow adds Input/Output context when subcircuits have input/output nets
- [v2.5-47]: Subcircuit lib_id checked from features dict first (fast), topology nodes as fallback
- [v2.5-47]: Design checks use topology edges for net connectivity (TopologyNode has no pin_nets)
- [v2.5-47]: Feedback detection uses edge signal_direction plus resistor net-sharing analysis
- [v2.5-47]: Component value check excluded from pipeline -- TopologyNode lacks value data
- [v2.5-47]: Topology indexes (net_to_nodes, node_to_nets) built once per check, passed to helpers
- [v2.5-47]: Ref index dict for O(1) component lookup in intent inference
- [v2.5-47]: Quadratic weighted mean for overall confidence (squares dominate higher-confidence subcircuits)
- [v2.5-47]: Net connectivity ordering for multi-buffer signal flow (not positional heuristic)
- [v2.5-47]: Backward-compatible match_fn dispatch (3-arg with TypeError fallback for 2-arg custom rules)
- [v2.5-48]: Design rules use topology edges exclusively (not pin_nets) for net connectivity -- TopologyNode lacks pin_nets
- [v2.5-48]: Feedback comp cap detection uses any feedback net overlap (single-net feedback common in topology graph)
- [v2.5-48]: THERMAL_01 emits INFO severity since topology lacks thermal pad data
- [v2.5-48]: Test file named test_design_rule_engine.py to avoid collision with existing test_design_rules.py (DRU parsing)
- [v2.5-48]: Shared topology_utils.py for build_net_to_nodes/build_node_to_nets (deduplicated from design_review + builtin_rules)
- [v2.5-48]: PowerFilterRule scans edges for pattern-matched power nets (not just topology.power_nets)
- [v2.5-48]: _is_resistor() excludes R_Potentiometer, R_Photoresistor, R_Thermistor, R_Variable
- [v2.5-48]: Redundant _rule_id_format validator removed (Pydantic pattern enforces it)
- [v2.5-48]: pyyaml used for YAML config parsing (already installed, not in pyproject.toml)
- [v2.5-48]: cli/ package directory created for subcommand modules, registered in existing CLI routing
- [v2.5-48]: CLI tests use real CircuitTopology instead of MagicMock to avoid Pydantic validation errors
- [v2.4-SI]: ClassifyViolationsOp in _schema_erc_smart.py (separate from _schema_repair.py per D-01)
- [v2.4-SI]: IR position data (pin/wire/label positions) distinguishes #PWR symbols from regular components
- [v2.5-51]: Arc center computed via perpendicular bisector intersection; 32-segment LineString approximation
- [v2.5-51]: 1nm snap tolerance closes floating-point gaps before polygonize (manufacturing tolerance >> 1nm)
- [v2.5-51]: Graphic item type detection by attribute presence (has start/end/mid/center), not isinstance
- [v2.5-51]: SpatialQueryEngine rebuilt lazily on access when dirty; mark_dirty invalidates cached engine
- [v3.0-52]: LayoutAwarePlacer wraps HybridPlacementEngine (composition over inheritance)
- [v3.0-52]: Zone boundaries are soft constraints (logged, not enforced) to avoid rejecting valid placements
- [v3.0-52]: ThermalProfile forward-declared as Any in LayoutAwareRequest for Plan 52-02
- [v3.0-52]: Type priority fallback when signal flow ordering is ambiguous
- [v3.0-52]: ThermalProfile is opt-in -- distance heuristic fallback with explicit logging
- [v3.0-52]: Constraint penalties use duck-typed objects (getattr) since Phase 50 types not yet defined
- [v3.0-52]: Thermal exclusion zones are soft guidance (SA can violate with penalty)
- [v3.0-52]: SA refinement at 200 iterations for layout-aware (reduced latency)
- [v3.0-54]: DfmChecker mirrors DesignRuleEngine pattern (ABC + orchestrator + report)
- [v3.0-54]: Meta-finding uses DFM_CHECKER_01 check_id to satisfy pattern validation on crashed checks
- [v3.0-54]: SolderMaskCheck uses 4x sliver proximity window for O(n) pair optimization
- [v3.0-54]: ManufacturerProfile uses yaml.safe_load for security (T-54-02, same as rule_config.py)
- [v3.0-54]: Panelization score formula: fiducials (0.3/0.15), tooling holes (0.2/0.1), orientation (0.3), edge clearance (0.2)
- [v3.0-54]: Assembly score formula: 1.0 - (warnings * 0.05) clamped to [0.0, 1.0]
- [v3.0-54]: Multi-stage pipeline runs DfmChecker with filtered check subsets per stage
- [v3.0-54]: Overall DFM score is minimum of all stage scores and panelization score
- [v3.0-54]: CLI exit codes: 0 (score >= 0.5), 1 (score < 0.5), 2 (error)
- [v3.0-54]: isinstance() type guards prevent MagicMock auto-attribute string matching

### Pending Todos

- All milestones shipped. Ready for next milestone planning.
- Phase 75 added retroactively: Pre-Analysis Gate and Context Intelligence (ad-hoc work tracked post-hoc)

### Blockers/Concerns

None.

## Deferred Items

None.

## Session Continuity

Stopped at: Completed Phase 63 - Training Integrity (all 4 plans, 37 tests).
Resume with: Next phase planning or `/gsd-execute-phase`.
