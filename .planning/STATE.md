---
gsd_state_version: 1.0
milestone: v2.2
milestone_name: Complete-Ops
status: Ready to plan
stopped_at: Completed Phase 100 Plan 02 — RoutingOrchestrator + DeterministicStrategy + audit trail + PcbIR rollback. Phase 100 fully implemented (both plans complete). Ready for `/gsd-verify-work 100` or next phase.
last_updated: "2026-06-25T08:34:23.268Z"
last_activity: 2026-06-25
progress:
  total_phases: 129
  completed_phases: 49
  total_plans: 269
  completed_plans: 209
  percent: 78
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-01)

**Core value:** LLM -> intent JSON -> AST mutation -> valid KiCad file. Zero corruption, every time.
**Current focus:** Phase 100 — routingorchestrator-and-human-approval-loop
Last activity: 2026-06-25

## Current Position

Phase: 101
Plan: Not started
**All milestones shipped (v1.0 through v4.1). 94 phases, 266 plans, 3300+ tests.**

Last milestone: v4.1 Stage-Safe PCB Flow (Phases 85-94)

- Phase 85: Gate Architecture (DesignStage, GateResult, GateRunner)
- Phase 86: Schematic Intent Completeness (footprint, pin-map, metadata checks)
- Phase 87: Schematic-to-PCB Transfer Contract (TransferContract, PadNetAssigner)
- Phase 88: Constraint Capture & Propagation (electrical/mechanical/fab)
- Phase 89: Placement Readiness Gate (6 sub-checks)
- Phase 90: Routing Readiness & Quality Gate (pre/post-route)
- Phase 91: Manufacturing Readiness Gate (DRC/DFM/BOM)
- Phase 92: AI Boundary & Repair Loop (Proposal model, RepairLoop)
- Phase 93: Golden E2E Boards (6 fixture boards)
- Phase 94: Docs & UX (stage-gate docs, status CLI)

Prior milestones: v4.0 Hybrid Routing (80-84), v3.2 Gap Analysis (79), v3.1 Council Remediation (60-76), v3.0 Full-Stack EDA (50-54), v2.5 Benchmark (41-44), v2.4 Schematic Intelligence (38-40)

- Phase 50: Constraint Propagation (81 tests)
- Phase 51: PCB Spatial Intelligence (51 tests)
- Phase 52: Layout-Aware Placement (41 tests)
- Phase 53: PCB DRC Intelligence (56 tests)
- Phase 54: Design for Manufacturing (62 tests)

Council review: 4 findings fixed, all passing.

Last activity: 2026-06-25 -- Phase 100 execution started

### Phase 99: Freerouting Integration Hardening (in progress)

- Plan 99-01: DSN generator NativeBoard refactor + R-1/R-2/R-3/R-5/R-7 (COMPLETE)
  - NativeBoard-backed DSN generation replaces regex extraction
  - Courtyard-accurate footprint outlines (R-1) with rotation-aware AABB
  - Per-net-class rules with self-contained per-class via padstacks (R-2 + H-2)
  - 3-way zone classification: plane / routing-keepout / placement-only-skip (R-3 + C-1)
  - 45° trace mode via (control (snap_angle ...)) (R-5)
  - snap_angle threaded through export_dsn + route_with_freerouting (BLOCKER-1)
  - 22 new tests across 7 files

- Plan 99-02: Via padstacks per stackup + SES multi-layer bridge (R-4, R-6) (COMPLETE)
  - NativeStackupLayer type + _extract_stackup_layers helper (R-4 stackup typing)
  - Stackup-based via padstacks: THT always, blind+buried when 4+ copper layers (R-4)
  - parse_ses rewritten for actual Freerouting v2.2.4 (wiring ...) section format (R-6)
  - Via layers derived from padstack name (Via[0-In1] -> F.Cu/In1.Cu)
  - ses_to_kicad_sexpr routes through ViaSegment.to_sexpr (WARN-2 canonical emitter)
  - Reference SES captured from Freerouting v2.2.4 on Arduino_Mega (H-3)
  - Rule 1 fixes: empty pad number, FreerouteBatch scoring NPE, unquoted UUID (KiCad 10)
  - M-4 smoke test: kicad-cli pcb drc accepts quoted UUID via (exit 0)
  - 18 new tests across 4 files + reference SES fixture

- Plan 99-03: SC-3/SC-4/SC-5 validation + baseline metrics (COMPLETE)
  - SC-3 PASS: Freerouting-routed smd_test_board passes kicad-cli pcb drc (0 unconnected)
  - SC-4: Baseline metrics for 3 fixtures (smd_test_board 50% completion DRC PASS, RaspberryPi-uHAT 3.2%, synthetic 4-layer)
  - SC-5 xfail: Freerouting v2.2.4 ignores DSN snap_angle in batch mode (documented limitation)
  - scripts/phase99_baseline.py CLI with --json for Phase 100 dispatch
  - Synthetic 4-layer fixture: 4 copper layers, 2 net classes (Power/Signal), 2 zones
  - 6 Rule 1/3 fixes: DSN class doubling, SMD padstack spaces, net name regex, SES resolution divisor, Y-negation, FreerouteBatch snap_angle
  - smd_test_board fixture fixed (was DRC-unloadable: nets in setup, missing B.Cu)
  - 5 new tests across 2 files + baseline script + synthetic fixture

### Phase 95: Dual Knowledge Base Integration (v2.2)

- Cognee ingestion script (`ingest_cognee.py`) outputs JSON MCP command payloads for 4 KiCad reference docs
- KnowledgeManager core (`knowledge.py`) with H2 section chunking, per-operation doc mapping (all 117 registry ops)
- CORE_RULES injected as trusted system instructions (not sanitized), doc-sourced content sanitized
- Token budget enforcement: per-section 800 + combined 2000 tokens via tiktoken
- KnowledgeManager wired into TextIntentParser, TextErrorFixer, InferenceWrapper, CLI
- `--no-knowledge` CLI flag disables knowledge injection
- Thread-safe singleton with double-checked locking
- 73 new tests (47 knowledge + 26 cognee ingestion), all passing
- Council: APPROVE after 2 rounds (9 findings fixed: 3 HIGH, 4 MEDIUM, 2 LOW)

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

### Phase 65: Architecture Refactor (v3.1)

- Plan 65-01: Split executor.py (H-18) (COMPLETE)
  - executor.py reduced from 1032 to 800 lines via batch_executor.py extraction
  - execute_batch method extracted to ops/batch_executor.py (297 lines)
  - OperationExecutor.execute_batch delegates to batch_executor.execute_batch()
  - Test patches updated from ops.executor to ops.batch_executor
  - 12/12 batch executor tests pass

- Plan 65-03: Split topology_graph.py (H-20) (COMPLETE)
  - topology_graph.py reduced from 950 to 197 lines (data types + constants)
  - TopologyBuilder class extracted to analysis/topology_builder.py (788 lines)
  - TopologyBuilder re-exported from topology_graph.py for backward compat
  - 116/116 topology tests pass

- Plan 65-04: Fix Medium Findings M-1 through M-12 (COMPLETE)
  - All 12 MEDIUM findings already fixed in prior phases (verified by existing tests)
  - M-6 test bug fixed: replaced MagicMock with real Shapely geometry for STRtree
  - 22/22 Phase 65 architecture tests pass

### Phase 70: Post-Repair Verification (v3.1)

- Plan 70-01: PersistentUndoStack Test Suite (UNDO-06) (COMPLETE)
  - 15 comprehensive tests: persistence, LIFO order, multi-file isolation, max_size pruning, manifest corruption, missing entry files, atomic writes, prune, clear, path traversal, concurrent access, redo not persisted, post_mtime preserved, empty project dir, fallback to in-memory
  - All 15 tests pass (0.57s total)
  - Rule 1 fix: added missing `Any` import in persistent_undo.py

- Plan 70-02: CLI Undo/Redo Commands + Gitignore (UNDO-07, UNDO-08) (COMPLETE)
  - `kicad-agent undo [file] [-p project-dir]` and `kicad-agent redo [file] [-p project-dir]` subcommands
  - Automatic .gitignore entry for `.kicad-agent/` via _ensure_gitignore() in PersistentUndoStack.__init__()
  - 8 tests: undo no history, undo with history, redo after undo, undo specific file, gitignore created/no-duplicate/append, subprocess undo
  - All 8 tests pass

### Phase 71: Tool Awareness Registry (v3.1)

- Plan 71-01: Pin-to-Net Mapping Test Suite (PINMAP-01, PINMAP-02) (COMPLETE)
  - 24 tests (5 new) covering all safety gates: wire connectivity, existing labels, dry_run, no_connect, reference filter, multi-instance, label type
  - Extended backplane profile completeness to validate all 10 ICs
  - All 24 tests pass (0.22s)

- Plan 71-02: Extended IC Profiles & Integration Test (PINMAP-03) (COMPLETE)
  - 20 integration tests: backplane completeness, channel-strip validation, power domain differences, auto-merge, JSON override, power pin enforcement
  - Validated RP2350B, NE5532, CD4066, CD4060, LM358 profiles correct
  - Confirmed NE5532 +/-12V (backplane) vs +/-15V (channel-strip) power domains
  - All 20 tests pass (0.23s combined)

### Phase 72: Read-Only Dispatch & MCP Annotations (v3.1)

- Plan 72-01: Verify Schematic Query Dispatch Path (COMPLETE)
  - 9 tests confirming _execute_schematic_query parse-only path works correctly
  - Verified 19 schematic query handlers skip Transaction/serialize
  - Verified all 25 registry readonly ops have proper dispatch handlers
  - No code changes needed (path already implemented in prior phases)

- Plan 72-02: Auto-Derive MCP Read-Only Annotations (COMPLETE)
  - Replaced manual _READ_ONLY_OPS frozenset (20 ops) with auto-derived set from registry (25 ops)
  - Replaced manual _DESTRUCTIVE_OPS frozenset (8 ops) with auto-derived set from registry (13 ops)
  - 5 previously missing readonly ops now annotated: analyze_split_plane, infer_connectivity, list_design_rules, list_lib_entries, list_net_classes
  - Bidirectional consistency test ensures registry and MCP annotations stay in sync

### Phase 74: Executor Refactor & Schema Organization (v3.1)

- Plan 74-01: Split executor handlers into modules (COMPLETE)
  - executor.py reduced from 800 to 287 lines (coordinator only)
  - New execution.py (640 lines) with all file-type execution functions as standalone functions
  - batch_executor.py updated to use standalone functions from execution.py
  - Backward-compatible re-exports preserved (handler registries, constants, dispatch functions)
  - All 55 directly affected tests pass with updated patches

- Plan 74-02: Reorganize miscategorized schema operations (COMPLETE)
  - Schema classes already moved in prior phase (verified in _schema_repair.py docstring)
  - Updated 6 OPERATION_REGISTRY entries from stale "repair" category to correct categories
  - swap_symbol -> component, update_symbols_from_library -> library, convert_kicad6_to_10 -> create
  - add_power_flag -> wire, rebuild_root_sheet -> sheet, place_net_labels -> routing

### Phase 73: Workflow Templates & Dependency Graph (v3.1)

- Plan 73-01: Operation Dependency Validation (COMPLETE)
  - Added `validate_conflicts()` to registry for detecting conflicting op sequences
  - Integrated `validate_dependencies()` and `validate_conflicts()` into `execute_batch()`
  - Added multi_file scope rejection in batch executor (generic, not name-based)
  - Filled missing metadata: `repair_schematic` requires `parse_erc` and conflicts with `remove_component`
  - `batch_connect` also requires `detect_routing_collisions` for correct batch ordering
  - 6 new batch dependency tests, 5 new registry conflict/dependency tests

- Plan 73-02: Workflow Templates as MCP Meta-Tools (COMPLETE)
  - 8 predefined workflow templates: fix_erc_errors, wire_schematic, add_component_full, repair_schematic, pcb_setup, design_review, full_pcb_layout, convert_legacy_schematic
  - Exposed `list_workflows` and `get_workflow` as read-only MCP meta-tools
  - All workflows validated against registry dependency chains and conflict checks
  - 6 new MCP dispatch tests for workflow tools
  - Meta-tool count updated from 7 to 9

### Phase 64: CLI/UX Polish (v3.1)

- Plan 64-01: Fix Route Crash on Paths Outside CWD (H-15) (COMPLETE)
  - try/except ValueError wrapping relative_to(Path.cwd()) in _handle_route
  - Falls back to absolute path when PCB file is outside CWD
  - 3 new tests in TestRoutePathOutsideCwd

- Plan 64-02: Add Top-Level Help with Subcommand Listing (H-16) (COMPLETE)
  - _SUBCOMMAND_DESCRIPTIONS dict with all 16 subcommands
  - _print_help() function with formatted subcommand table
  - main() routes --help/-h/no-args to help before subcommand dispatch
  - 5 new tests in TestTopLevelHelp

- Plan 64-03: Fix Component-Search Help (H-17) (COMPLETE)
  - argparse.parse_args() intercepts --help/-h before MCP import
  - MCP server never starts when --help is requested
  - 3 new tests in TestComponentSearchHelp

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

- Total plans completed: 157
- Average duration: 5 min
- Total execution time: 6.5 hours

**Recent Trend:**

- Last 10 plans: 50-01 through 54-02 (all first-execution pass)
- Trend: Stable -- all plans passing on first execution

## Accumulated Context

### Roadmap Evolution

- Phase 80 added: Spatial Reasoning Model Benchmark — evaluate 0.5B/1.5B on 6 coordinate-grounded task categories
- Phase 81 added: Post-Routing Gap Analyzer — deterministic gap identification on partially-routed PCBs
- Phase 82 added: AI-Powered Gap Filling Engine — AI-assisted fixes using existing 98 operations
- Phase 83 added: analog-ecosystem Integration — unified routing workflow replacing per-board custom scripts
- Phase 84 added: Model Upgrade (Conditional) — train larger model if benchmark shows insufficiency
- Phase 95 added: Dual Knowledge Base Integration — Cognee ingestion + section injection for local model prompts
- Phase 98 added: Closed-loop vision-guided PCB routing — wire trained V2 LoRA into pathfinder-driven routing loop with eval harness
- Phase 98 REFRAMED: AI Routing Strategy Advisor — vision model emits strategy consumed by Phase 100 orchestrator (closed-loop approach replaced by Option A architecture: Freerouting + orchestrator + AI advisor)
- Phase 99 added: Freerouting Integration Hardening — replaces conceptual Phase 122B; closes real multi-layer gaps (footprint obstacles, net classes, zones, via types, 45° traces). Multi-layer graph scaffolding already exists in graph.py:156-247
- Phase 100 added: RoutingOrchestrator and Human Approval Loop — dispatcher routes nets to A* vs Freerouting, defines RoutingStrategy interface that Phase 98 plugs into, extends InteractiveRoutingSession for Freerouting output
- Phase 101 added: Schematic Ops Bug Fixes — close 5 P0/P1 bugs (P0-001 through P0-005) from analog-ecosystem backplane cleanup. BUGS/ reports source.

### v4.1 Stage-Safe PCB Flow (Phases 85-94)

**Goal:** Enforce a credible schematic-to-manufacturing PCB workflow where each stage has deterministic readiness gates.

Planned phases:

- Phase 85: Gate Architecture (2 plans) — DesignStage enum, GateResult, GateRunner
- Phase 86: Schematic Intent Completeness (2 plans) — Footprint/pin-map/metadata/net intent
- Phase 87: Schematic-to-PCB Transfer Contract (2 plans) — Verified symbol→footprint→pad→net
- Phase 88: Constraint Capture & Propagation (2 plans) — Electrical/mechanical/fab constraints
- Phase 89: Placement Readiness Gate (1 plan) — 6 sub-checks
- Phase 90: Routing Readiness & Quality Gate (1 plan) — Pre/post-route gates
- Phase 91: Manufacturing Readiness Gate (1 plan) — Full package validation
- Phase 92: AI Boundary & Repair Loop (1 plan) — Proposal model, audit trail
- Phase 93: Golden E2E Boards (1 plan) — 6 fixture boards proving full flow
- Phase 94: Docs & UX (1 plan) — Stage-gate documentation

Total: 14 plans across 10 phases.

Priority: Start with Phases 85-87 (gate architecture + schematic intent + transfer contract) per document recommendation.

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [v4.1]: Stage-safe flow shifts from "file-safe editing" to "stage-safe design" — every design transition has a deterministic gate
- [v4.1]: Phases 85-87 prioritized — biggest current weakness is gap between safe KiCad files and real schematic-to-PCB transfer
- [v4.1]: LLM output is advisory; deterministic gates decide whether proposals can mutate files
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
- [v2.2-100]: RoutingStrategy is a typing.Protocol (not ABC) — enables Phase 98 structural subtyping without inheritance
- [v2.2-100]: RouterBackend has exactly 2 variants (ASTAR, FREEROUTING) — MULTI_PASS removed as dead code (H1, YAGNI)
- [v2.2-100]: BoardState has no layer_count field — no dispatch case reads it (H3, YAGNI)
- [v2.2-100]: DeterministicStrategy dispatch order is first-match-wins: diff pair → power+zones → high pin (>10) → simple 2-pin (≤20 nets) → default ASTAR
- [v2.2-100]: Audit trail uses JSONL with os.fsync after each line for crash durability (H5); query_by_net skips truncated lines gracefully
- [v2.2-100]: Rollback uses PcbRawWriter.delete_segment/delete_via via UUID extraction — NOT regex on S-expressions (H2, avoids pad-definition corruption)
- [v2.2-100]: UUID extraction uses bulk extract_uuids(content, file_type) then parent_index filtering (R3-L3)
- [v2.2-100]: Per-net Freerouting completion attribution via SES parse (parse_ses), not just success flag — accurate baseline measurement
- [v2.2-100]: SC-5 baseline test asserts >= 45% (lower bound only) — orchestrator combines A* + Freerouting so should meet or exceed Freerouting-alone baseline

### Pending Todos

- All milestones shipped. Ready for next milestone planning.
- Phase 75 added retroactively: Pre-Analysis Gate and Context Intelligence (ad-hoc work tracked post-hoc)
- **Phase 102 (proposed): Schematic Ops Bug Fixes** — 5 P0/P1 bugs from analog-ecosystem backplane cleanup (BUGS/P0-001 through P0-005). Out-of-scope for Phase 99 (freerouting) but blocking ~600 ERC violations on production backplane work. Fix priority: P0-003 deprecation (data loss) → P0-001 quick fix → P0-002+P0-004 position transforms → P0-005 criteria alignment. See `BUGS/README.md` for details.

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260616-wqd | Build a validate_labels pre-flight check in kicad-agent | 2026-06-17 | ee47896 | [260616-wqd-build-a-validate-labels-pre-flight-check](./quick/260616-wqd-build-a-validate-labels-pre-flight-check/) |

### Blockers/Concerns

None.

## Deferred Items

- **CR-01** (Critical, Council Exec Review 99): **RESOLVED 2026-06-25 (Phase 100 Plan 01).** All 14 NativeBoard dataclasses converted to `@dataclass(frozen=True)`; 16 list fields converted to tuple defaults; `NativeFootprint.properties` exposed as `MappingProxyType` read-only view; all native-path mutation sites in `pcb_ir.py` (`add_net`, `remove_net`, `rename_net`, `swap_footprint`) and `pcb_native_parser.py` (every extractor) migrated to `dataclasses.replace` / construct-once pattern. 8 new immutability tests + 357 existing regression tests pass (365 total). See `.planning/phases/100-routingorchestrator-and-human-approval-loop/100-01-SUMMARY.md`. Tags: council-deferred,immutability,phase-99,cr-01,wr-07.

- **WR-07** (Medium, Council Exec Review 99): **RESOLVED 2026-06-25 (subsumed by CR-01 closure above).** `PcbIR.remove_net` now rebuilds pads via `dataclasses.replace(pad, net_name="", net_number=0)` and rebuilds the footprint and board via replace chain. Tags: council-deferred,immutability,phase-99,wr-07.

## Session Continuity

Stopped at: Completed Phase 100 Plan 02 — RoutingOrchestrator + DeterministicStrategy + audit trail + PcbIR rollback. Phase 100 fully implemented (both plans complete). Ready for `/gsd-verify-work 100` or next phase.
Resume with: Phase 100 verification, or Phase 101 (Schematic Ops Bug Fixes), or Phase 98 (AI Routing Strategy Advisor — now has the RoutingStrategy Protocol contract to implement).

### Phase 100: RoutingOrchestrator and Human Approval Loop (complete)

- Plan 100-01: CR-01 NativeBoard immutability refactor (COMPLETE)
  - 14 frozen dataclasses, all native-path mutation sites migrated to dataclasses.replace
  - Foundation for Plan 02's snapshot-based rollback

- Plan 100-02: RoutingOrchestrator + audit + rollback (COMPLETE)
  - RoutingStrategy Protocol (Phase 98 integration contract — pure, serializable, validatable)
  - DeterministicStrategy with 5-case dispatch (diff pair → power+zones → high pin → simple 2-pin → default ASTAR)
  - RouterBackend enum (2 variants: ASTAR, FREEROUTING — H1: MULTI_PASS removed)
  - RoutingOrchestrator batch API (route_board single-call for full board)
  - PcbIR-based per-net rollback via PcbRawWriter UUID deletion (H2 — no regex)
  - Durable JSONL audit trail with os.fsync (H5)
  - InteractiveRoutingSession.ingest_freerouting_result (SES wires → suggestions)
  - Strategy output validation (H4 — unknown nets/invalid backends raise ValueError)
  - 66 Phase 100 tests + 357 regression tests pass (431 total, zero regressions)
