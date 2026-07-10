# COUNCIL-PLAN-REVIEW: PCB Issues #37-#43

**Plan:** `/Users/bretbouchard/.claude/plans/pcb-issues-37-43.md`
**Verdict:** APPROVE WITH CONDITIONS (4 conditions)

## Conditions

### C-01 [HIGH]: PcbRawWriter returns content, executor handles writes
Raw writers must return modified S-expression strings. The executor remains the sole write entry point with atomic temp+rename and cache invalidation. Eliminates: stale cache (F-01), dual representation (F-02), atomicity gaps (F-03).

### C-02 [MEDIUM]: Consolidate existing raw-write sites into PcbRawWriter
Plan 80-02 must migrate all 3 existing sites: `assign_net_class`, `insert_track_segments`, `update_footprint_from_library`. Deprecate duplicate `_find_matching_close`. (F-04)

### C-03 [MEDIUM]: Scope multi-pass routing to 3 passes
Passes 4-5 (diff pairs, power zones) deferred to separate phases. Plan 81-01: A*, rip-up-reroute, aggressive layer-switching only. (F-05)

### C-04 [MEDIUM]: Add integration tests + kicad-cli validation
Round-trip integration tests with real .kicad_pcb fixtures. `kicad-cli pcb drc` validation on modified files. (F-07)

## Findings (9 total)

| # | Severity | Description |
|---|----------|-------------|
| F-01 | HIGH | Stale executor cache after raw writes — PcbRawWriter must return content, not write to disk |
| F-02 | HIGH | Dual representation risk for zone ops — must be single write path |
| F-03 | HIGH | No atomicity for raw writes — all writes must use temp+rename |
| F-04 | MEDIUM | `_find_matching_close` duplication — consolidate into PcbRawWriter |
| F-05 | MEDIUM | Multi-pass routing scope creep — 3 passes max, defer diff pairs/power zones |
| F-06 | MEDIUM | Netlist extractor needs KiCad 10 pre-processing — reference `_fix_pad_net_syntax` |
| F-07 | MEDIUM | No integration tests — add round-trip tests with real PCB fixtures |
| F-08 | LOW | Missing bounding-box fallback in raw zone writer |
| F-09 | LOW | No full regression run specified — add `pytest tests/` as completion gate |

---

# COUNCIL-PLAN-REVIEW: Routing Overhaul — Phases 103-106

**Plan:** `/Users/bretbouchard/apps/kicad-agent/plans/routing-overhaul-phases-103-106.md`
**Verdict:** APPROVE WITH CONDITIONS (3 conditions)
**Date:** 2026-07-02
**Phases:** 103 (Foundation), 104 (Diagnosis), 105 (Negotiation), 106 (Placement-Advisor)

---

## Verdict Summary

The Council **approves with conditions**. This is the strongest plan document the project has produced: the evidence base (§3) was independently verified against the codebase and is accurate on every load-bearing claim. The design principle — reverse-perspective blocker diagnosis feeding a negotiation loop — is architecturally sound and well-grounded in the PathFinder lineage. The model repoint is correct and overdue.

The conditions are about **migration scope honesty** (the `route_net` return-type change touches more than the plan acknowledges) and **fuzziness in the high-risk phase** (105's DSN re-export loop is under-specified relative to its load-bearing risk). None of the conditions block Phases 103 or 104 from proceeding immediately.

---

## Council Composition (perspectives applied)

| Rick | Lens | Key concern |
|------|------|-------------|
| **security-rick** | Mechanical safety, write paths | Component-move atomicity, revert guarantees |
| **simple-rick** | SLC, scope creep, YAGNI | Is 106's training loop in or out? |
| **shyam-rick** | API surface, migration risk | `route_net` return-type ripple |
| **quilt-rick** | Routing algorithm correctness | PathFinder convergence, Freerouting contract |
| **vision-rick** | Model task alignment | Is the repoint toward or away from training distribution? |

---

## Conditions (3)

### C-01 [HIGH]: Fix `route_net` return-type migration scope in Phase 103

**The plan claims** Phase 103 is "~150 lines, low risk, no external dependencies" and changes `route_net` to return `RouteResult | RouteFailure` instead of `None`.

**The codebase reality:** `route_net` has **11 call sites across 6 files**, every one of which uses the `if result is None` / `result is not None` truthiness pattern:

- `pathfinder.py:164,217,228` (inside `route_all_nets` / `_route_multi_pin_net`)
- `orchestrator.py:392` (`_dispatch_astar`)
- `ops/handlers/pcb.py:806` (`_handle_auto_route` — the production path)
- `multi_pass.py:145`
- `diff_pair.py:279,292`
- `analysis/spatial_benchmark.py:842,898`

A return-type change from `None` to a `RouteFailure` object **breaks every `is None` check**. If `RouteFailure` is truthy (a frozen dataclass is), then `if result is not None` will treat failures as successes unless every call site is migrated to discriminated-union handling (`isinstance(result, RouteResult)` / `isinstance(result, RouteFailure)`).

**This is not 150 lines. It is a cross-cutting API change.** It is still correct to do (the plan's motivation is right), but it must be scoped honestly or it will be under-tested.

**Condition:** Phase 103's deliverable must include an explicit migration table of all 11 call sites and a passing full test suite (`pytest tests/`) as its completion gate. Recommend a `__bool__` or `is_success` property on a shared union base to minimize call-site churn, OR a clean two-phase migration (introduce `RouteFailure` alongside `None` first, flip callers second). (F-01)

### C-02 [MEDIUM]: Specify Phase 105's DSN re-export round-trip as a concrete contract

Phase 105's core loop is: *"re-export DSN with locked wiring + raised priorities for reroute_nets."* This is the load-bearing mechanism now that R-1 (type-fix honoring) is resolved. But the plan under-specifies the round-trip:

1. **Segment → wire conversion.** The plan says "read existing `(segment ...)`/`(via ...)` from PCB via `NativeParser`, convert to DSN `(wire ...)`." But Freerouting's DSN parser and KiCad's SES exporter are separate codebases. The `dsn_generator.py` currently emits **no** `(wiring ...)` section (verified — grep shows only `width` references, no `(wire` emission). This is net-new emitter code, not "extend existing emitter."

2. **Coordinate-system fidelity.** DSN uses a different origin/scale convention than KiCad's native mm coordinates. The existing `generate_dsn` (`dsn_generator.py:54-265`) handles the *pin* coordinate transform; extending it to *routed wire paths* (segments + vias, layer names, via drill/size) is a non-trivial fidelity requirement. A wire that round-trips with slightly wrong coordinates defeats the entire `(type fix)` locking mechanism — Freerouting will treat it as a near-but-not-exact wire.

3. **SES import reconciliation.** After Freerouting routes the unlocked nets, `import_ses_into_pcb` must merge the new routes with the preserved `(type fix)` wires without duplicating or dropping segments. The plan does not address how the merge detects/handles overlap.

**Condition:** Phase 105 must add a deliverable: a documented DSN-wire/SES-merge round-trip contract (coordinate transform, layer mapping, via representation) with a round-trip fidelity test — route a net, export as `(type fix)`, re-import via SES, assert the wire survives with <1µm coordinate error. Do this as the **first** 105 task, before the negotiation loop, because the loop is built on it. (F-02, F-03)

### C-03 [MEDIUM]: Phase 106 checkpoint hygiene is a hard gate before any training infra work

The plan flags this ("Checkpoint hygiene (blocking)") but lists it under Phase 106 rather than as a precondition. The Gemma v2 adapter lives on `/Volumes/Storage` (external drive, per `phase98_eval.py:54`) — it is **not committed to the repo** and is not reproducible.

**Condition:** A committed, repo-tracked checkpoint path (or a documented, reproducible fetch script) must exist before Phase 106's training-infra work begins. Training runs that depend on a drive that may be unmounted are not reproducible. (F-04)

---

## Findings (11 total)

| # | Sev | Phase | Description |
|---|-----|-------|-------------|
| F-01 | HIGH | 103 | `route_net` return-type change has 11 call sites across 6 files, not "~150 lines." All use `is None` checks that break silently if `RouteFailure` is truthy. Plan under-scopes the migration. → C-01 |
| F-02 | HIGH | 105 | DSN `(wiring ...)` section emission is net-new code (current `dsn_generator.py` emits none), not "extend existing emitter." Coordinate-system fidelity between KiCad mm and DSN is load-bearing for `(type fix)` to work. → C-02 |
| F-03 | MED | 105 | SES import merge semantics under-specified: how does `import_ses_into_pcb` reconcile new Freerouting routes with preserved `(type fix)` wires without duplicating/dropping segments? → C-02 |
| F-04 | MED | 106 | Model checkpoint on unmounted external drive (`/Volumes/Storage`) — not reproducible. Must be committed/fetchable before training infra. → C-03 |
| F-05 | MED | 104 | Reachability-per-blocker (§4 scope item 2) is O(blockers × BFS). On Arduino_Mega (~160k nodes), even 10 blockers = 10 full-graph traversals. The "cache reachable component from 103" mitigation is sound but the plan should specify the N cap (recommend top-5 shadow obstacles) as a phase-104 success gate, not just a risk-register note. |
| F-06 | MED | 105 | Congestion-cost injection into `RoutingGraph` edge weights assumes the A\* fallback path uses the same graph instance with mutable weights. But the legacy handler (`pcb.py:806`) calls `route_net(current_graph, ...)` per-net with progressive `mark_path_as_obstacle`. The negotiation loop needs its own graph lifecycle management — not clear it can piggyback on the per-call graph. |
| F-07 | LOW | 104 | Component movability heuristic (locked-grep + ref-prefix + edge-proximity) has no test for the precedence/overlap case (e.g., a locked `J1` near the edge — is it fixed for both reasons?). Classification conflicts should resolve to the most restrictive (fixed). Recommend documenting precedence as: locked > connector-prefix > edge-proximity > movable. |
| F-08 | LOW | 105 | The "DRC parsing consolidation" (103 scope item 3) is listed as a 103 deliverable but its primary consumer is the 105 DRC-as-reward loop. It is correctly sequenced (103 before 105) but should have an explicit acceptance test: both JSON-rich and regex parsers produce identical violation sets on a known fixture before the regex path is retired. |
| F-09 | LOW | 106 | "Retire `AiRoutingStrategy`" — the plan says "keep code for reference; stop investing." This is correct, but `orchestrator.py:120-121` defaults to `DeterministicStrategy` and the `strategy`/`use_ai` config flags (`config.py:46,49`) are documented dead code. Recommend an explicit "deprecated, do not wire" comment rather than silent retention, to prevent a future agent from reviving it. |
| F-10 | LOW | all | Test fixtures are sparse (§3.6): only Arduino_Mega is a real dense board. The plan's strategy to "vendor the backplane PCB" is correct but has no owner/deadline. Without it, the 105 convergence and 106 nudge tests have a single-board sample size. Recommend making backplane vendoring a 103-side-task (unblocks 104+105 testing). |
| F-11 | LOW | 103 | Benchmark target "single_source_dijkstra_path_length <2s on Arduino_Mega" — this is reasonable but the plan should also benchmark on a *dense* board (the vendored backplane, once available) since the 160k-node estimate is for Arduino_Mega at 0.25mm; a real backplane could be 5-10× larger. |

---

## Council Responses to Evaluation Questions

### Q1: Is the 4-phase dependency chain (103→104→105 sequential, 106 ∥ 105) correct?

**Yes.** The chain is sound and the parallelization of 106 with 105 is the key efficiency win — 106's training data is generated by 104's deterministic classifier, which is ready before 105's loop is built. The two can proceed on parallel tracks: 105 builds the negotiation loop, 106 builds the model/advisor, they integrate when both are ready.

One note: 104→106 depends on 104 *producing training data*, but the plan does not specify when 104's diagnostic output is "harvest-ready" (volume, format). Recommend 106 cannot begin SFT data collection until 104 has a stable output schema and ≥1 real-board diagnostic run. This is implied but not gated.

### Q2: Architectural risks the plan misses?

**Two, both covered above as findings:**
1. The `route_net` API ripple (F-01) — not a missing risk, but an under-scoped migration.
2. Graph lifecycle in the negotiation loop (F-06) — the loop needs its own mutable-weight graph instance; it cannot reuse the per-call graph that `route_net` currently operates on. This is an architectural assumption the plan does not state.

No *new* architectural risks beyond these. The plan's own risk register (R-1 through R-8) is thorough and the R-1 resolution (type-fix honored) removes the single biggest unknown.

### Q3: Is the model repoint (retiring AiRoutingStrategy, building BlockerDiagnosticianModel) the right call?

**Yes — strongly endorsed.** This is the plan's strongest decision. Evidence:
- `AiRoutingStrategy` is constructed **exactly once** outside its own definition (`scripts/phase98_eval.py:231`) — zero production wiring. The default is `DeterministicStrategy` (`orchestrator.py:121`). Retiring it changes nothing in production.
- The inference task (strategy JSON dispatch) is admitted out-of-distribution in the codebase's own docstring (`strategy_prompts.py:5-6`). The model was *never trained on it*.
- The repoint target (blocker diagnosis + placement counterfactuals) matches the actual training distribution: coordinate-grounded spatial reasoning, obstacle identification, "which fix is correct" (`generate_gap_training_data.py`). This is a move **toward** the training distribution.

Strategy dispatch should **not** be retained. The plan's fallback (graceful degradation to deterministic classifier if model <50% accuracy) is the correct safety net, not keeping the dead dispatch task.

### Q4: Are the success criteria measurable and risks adequately mitigated?

**Measurable: yes.** Each phase has concrete, testable criteria (dead-end coordinate match, 3-wall-maze HARD_FIXED classification, 2-net corridor convergence in ≤3 rounds, ≥50% model accuracy gate). These are specific enough to gate phase completion.

**Risks: adequately mitigated, with two gaps closed by conditions.** R-1 (the highest-severity) is resolved empirically. R-2/R-7 (convergence) are backed by PathFinder's monotonic-cost proof. The gaps are F-01 (migration scope) and F-02 (DSN fidelity) — both now conditions C-01 and C-02.

### Q5: Recommendations on open questions Q2–Q5

- **Q2 (latency budget):** **Accept the 8-round cap for batch routing.** The plan correctly identifies this as an offline/batch use case. Real boards are not routed interactively. The 8-round cap + stall detection is sufficient. No condition needed.
- **Q3 (nudge validation depth):** **Agree with the plan's recommendation — rely on post-nudge DRC delta with revert; treat pre-nudge AABB check as fast-fail, not gate.** A pre-nudge routing-aware collision check would require a full re-route simulation per candidate nudge — that defeats the purpose (the model is supposed to *avoid* that expensive search). The revert-on-negative-delta design is correct and sufficient (R-4 covers it).
- **Q4 (training compute):** **Fold into existing infra (`vast_train_kicad.py`), but gate it behind C-03 (checkpoint hygiene) first.** A dedicated training-run plan is premature scope — the reward loop is a modification of the existing SFT pipeline, not a new system. If the reward signal proves unstable (DRC delta is noisy), *then* revisit. Recommend: start with SFT on harvested diagnostic traces (cheap, deterministic labels from Phase 104), defer the GRPO/reward loop until SFT baseline is measured.
- **Q5 (orchestrator convergence):** **Defer.** The plan is correct. The orchestrator is test-only with a feature-subset A\* branch (`obstacles=[]`, no power filtering, 2-pin only). Porting legacy-handler features to it is a refactor with no production effect. R-8 covers this correctly. Bringing it into scope would double the work for zero user-visible benefit.

### Q6: SLC compliance — Simple, Lovable, Complete, or scope creep?

**Simple:** ✅ Phases 103 and 104 are genuinely simple — mechanical data-capture and a classifier with a clean schema. Phase 105 is appropriately complex for its value (it *is* the closed loop). Phase 106 is the most complex but is correctly parallelized and gated.

**Lovable:** ✅ The diagnostic output (Phase 104) is immediately useful even without the loop — "tell me *why* routing failed" is a human-facing feature today.

**Complete:** ⚠️ The plan is complete *as a design*, but Phases 105 and 106 each have one under-specified load-bearing mechanism (F-02: DSN round-trip; F-04: checkpoint reproducibility). Both are now conditions.

**Scope creep:** ✅ **No.** The §10 out-of-scope list is well-drawn — orchestrator unification, proactive placement, interactive routing, schematic bugs, and full RL-router are all correctly deferred. The plan resists the temptation to over-reach. The model is used for diagnosis + placement advice, *not* as a replacement router (which would be a 10× larger problem). This is disciplined scoping.

---

## Recommended Execution Sequence

1. **Phase 103** — may begin immediately. Address C-01 (migration table + full test gate) as part of the phase. Side-task: vendor the backplane PCB (F-10).
2. **Phase 104** — begins after 103. Specify the top-N shadow-obstacle cap as a success gate (F-05).
3. **Phase 105** — begins after 104. **First task:** DSN-wire/SES-merge round-trip contract + fidelity test (C-02). Then the negotiation loop.
4. **Phase 106** — parallel with 105, but **cannot begin SFT data collection** until 104 produces stable diagnostic output. **Cannot begin training infra** until C-03 (checkpoint) is satisfied. Start with SFT on harvested traces; defer GRPO/reward loop.

---

## Evidence-Base Verification (all claims checked)

The Council independently verified every file:line citation in §3 of the plan against the live codebase. **All claims are accurate:**

| Plan claim | Citation | Verified |
|------------|----------|----------|
| `graph.graph` public read-only property | `graph.py:336-339` | ✅ |
| `route_net` catches `NetworkXNoPath`, returns `None` at line 109-110 | `pathfinder.py:109` | ✅ |
| `src_node`/`tgt_node` in scope before try block | `pathfinder.py:92-96` | ✅ |
| `_handle_auto_route` is production path (registered handler) | `pcb.py:513` `@register_pcb("auto_route")` | ✅ |
| Orchestrator `route_board` called only from script + tests | grep confirms `scripts/phase98_eval.py:113` + `tests/test_phase100_*` | ✅ |
| Orchestrator `_dispatch_astar` uses `obstacles=[]` | `orchestrator.py:371` | ✅ |
| Default strategy is `DeterministicStrategy` | `orchestrator.py:121` | ✅ |
| `AiRoutingStrategy` never constructed in production | only `scripts/phase98_eval.py:231` | ✅ |
| `modify_footprint_position` exists, returns content | `pcb_raw_writer.py:422` | ✅ |
| `NativeFootprint` has no `locked` field | grep on `pcb_native_types.py` returns nothing | ✅ |
| `SpatialQueryEngine` is STRtree-backed | `spatial/query.py:41`, imports `shapely.STRtree` | ✅ |
| `test_phase105_type_fix_honored.py` exists with 4 tests | file present, 4 `def test_` functions | ✅ |
| `dsn_generator.py` emits no `(wiring ...)` section | grep confirms — net-new code needed | ✅ |
| `route_net` has 11 production call sites | grep across `src/` confirms migration scope | ✅ |

---

# COUNCIL-PLAN-REVIEW: Phase 156 — SKIDL Converter

**Plan:** `.planning/phases/156-skidl-converter/PLAN.md`
**Implementation:** `src/kicad_agent/circuit_ir/` (9 modules, 33 tests passing)
**Verdict:** APPROVE WITH CONDITIONS (6 conditions — 2 BLOCKING)
**Date:** 2026-07-03
**Phases:** 156 (SKIDL Converter) → 157 (Floor Planner)

---

## Verdict Summary

The Council **approves with conditions**. The core engineering of Phase 156 is sound: the KiCad→SKIDL read-back path (`build_circuit`) genuinely composes the proven `extract_nets` + `SchematicIR` primitives, the immutable `CircuitIR` types are clean and frozen, the L1/L2 emission modes work as specified, the import guard for pitfall #6 (`KICAD_SYMBOL_DIR`) is correctly implemented, and the round-trip proof (`build_circuit` → `circuit_to_kicad_sch`) is demonstrated on a real fixture. The plan's "compose, don't rebuild" principle was honored for the read-back path.

However, the phase **declares DONE in ways that do not match the Definition of Done in the PLAN.md.** The most serious gap: the `convert_to_skidl` op handler does **not** call `build_circuit()` — it delegates to a legacy `KiCadToSkidlConverter` that shells out to the `kicad-agent` CLI via `subprocess` and parses the result with `eval()`. The proven in-process pipeline the plan mandates is bypassed in the only integration path that users actually invoke. This is a load-bearing architectural divergence, not a cosmetic one.

The conditions split into **blocking** (C-01, C-02 — the phase does not meet its own acceptance criteria and breaks SLC compliance tests) and **non-blocking** (C-03–C-06 — gaps to close but they don't make the deliverable unsafe to build on). All six must be met before Phase 157 ships; only the two blocking ones must be met to *start* Phase 157.

---

## Council Composition (perspectives applied)

| Rick | Lens | Key concern |
|------|------|-------------|
| **simple-rick** | SLC, scope creep, dead code | Two duplicate schema files; `convert_from_skidl` is a phantom op; `converter.py`/`emitter.py` are untested legacy parallel pipelines |
| **security-rick** | Mechanical safety, write paths, code execution | `eval()` on netlist output; `exec()` + `pickle` round-trip; op not in dispatch chain |
| **quilt-rick** | Correctness, round-trip fidelity | ERC never actually run in tests; multi-unit handling not exercised; hierarchy flatten delegates entirely to `extract_nets` |
| **shyam-rick** | API surface, migration risk | `build_circuit` signature differs from plan; op handler calls wrong code path |
| **vision-rick** | Milestone coherence, downstream consumers | Phase 157 floor planner consumes `PartDescriptor.sheet`; will it get the values it expects? |

---

## Conditions (6)

### C-01 [BLOCKING]: Wire `convert_to_skidl` op handler to `build_circuit`, not the legacy CLI-shelling converter

**The plan mandates** (W6-4): the `convert_to_skidl` handler calls `build_circuit(ir, nets, ...)` + `emit_build_py(circuit_ir, ...)` in-process. The plan's example code is explicit.

**The codebase reality:** Two handlers are registered for `convert_to_skidl`:
- `ops/handlers/schematic_query.py:278` — the one that's actually dispatched (it's in `_SCHEMATIC_QUERY_HANDLERS`)
- `ops/handlers/circuit_ir.py:21` — registered in `_CIRCUIT_IR_HANDLERS` which is **never dispatched** by the executor (dead code)

Both delegate to `KiCadToSkidlConverter.convert()` (`converter.py:23`), which:
1. Shells out to the `kicad-agent` CLI via `subprocess.run(["kicad-agent", json.dumps({...})])` (line 45-49) — re-invoking the whole agent to call one op
2. Parses stdout with a regex and **`eval()`s the captured dict** (line 61: `nets_data = eval(nets_match.group(1))`) — arbitrary code execution on command output
3. Uses a separate `_extract_components` and the legacy `SkidlEmitter` (emitter.py), bypassing the tested `build_circuit` + `skidl_emitter.emit_build_py` pipeline entirely

This means **the integration tests exercise one code path, and the production op handler exercises a completely different, untested one.** The 33 passing tests give false confidence about the op that users invoke.

**Condition:** Rewrite both handlers to call `build_circuit(file_path)` → `emit_build_py(circuit_ir, mode=op.representation, out_path=...)`. Delete the `subprocess` + `eval()` path in `converter.py`. The `KiCadToSkidlConverter` class is either removed or reduced to a thin wrapper. The op handler must return `{"parts": len(circuit_ir.parts), "nets": len(circuit_ir.nets), "diagnostics": [...], "output_path": ...}` per the plan's spec. (F-01, F-02, F-03)

### C-02 [BLOCKING]: Fix the two failing SLC compliance tests — op count drift (139 → 150)

Adding `ConvertToSkidlOp` to the Operation union bumped the schema op count from 139 to 150 (the jump is larger than 1 because the count helper walks all `_schema_*.py` modules and the two duplicate circuit schema files both define classes). Two SLC tests now fail:
- `test_readme_operation_count_matches_schema` — README says 139, schema has 150
- `test_skill_md_operation_count_matches_schema` — SKILL.md says 139, schema has 150

**Root cause:** There are **two schema files** for the same ops:
- `ops/_schema_circuit.py` — defines `ConvertToSkidlOp` + `ConvertFromSkidlOp` (the plan-specified one)
- `ops/_schema_circuit_ir.py` — defines a *different* `ConvertToSkidlOp` with different fields (`output_file`/`level` vs. `representation`/`output_dir`/`flatten_hierarchy`)

`schema.py:294` imports from `_schema_circuit_ir` (the non-plan one). The plan's version (`_schema_circuit.py`) is orphaned. This is an SLC violation: **two sources of truth for the same op**, with divergent field names.

**Condition:** Delete one schema file. Keep the plan-compliant version (`_schema_circuit.py` with `representation`/`output_dir`/`flatten_hierarchy`/`symbol_dir`/`run_erc`), update `schema.py` to import from it, and update README.md + SKILL.md operation counts. Run `validate_registry_completeness()` and the SLC test suite to confirm zero failures. (F-04, F-05)

### C-03 [MEDIUM]: Register `convert_from_skidl` end-to-end, or remove it from the schema

**`ConvertFromSkidlOp` is a phantom op.** It exists in `ops/_schema_circuit.py:31` but:
- Is **not imported** into `schema.py`'s Operation union (grep confirms: `ConvertFromSkidlOp` appears nowhere in schema.py)
- Has **no registered handler** (grep for `convert_from_skidl` across `src/kicad_agent/` returns only the schema class definition)
- Is **not in `SELF_SERIALIZING_OPS`** (the plan's W6-5 mandates this)
- Has **no test** exercising the op (the round-trip test in `test_hierarchy_and_reverse.py` calls `circuit_to_kicad_sch()` directly, not via the op)

This fails the "no phantom operations" SLC criterion that the project has enforced since Phase 80. The underlying `circuit_to_kicad_sch` function works (tested directly), but the op is unreachable.

**Condition:** Either (a) wire `convert_from_skidl` fully: add to Operation union, register handler, add to `SELF_SERIALIZING_OPS`, add an integration test that invokes the op via the executor; or (b) if Phase 157 doesn't need it yet, remove the `ConvertFromSkidlOp` class and defer to a later phase. Pick one — do not leave a documented-but-dead op. (F-06)

### C-04 [MEDIUM]: Declare `skidl` in `pyproject.toml` dependencies

**The plan's DoD requires** `skidl>=2.2.3` in `pyproject.toml`. The Risks section explicitly calls this out: *"skidl not in pyproject.toml (confirmed: only spicelib declared, skidl installed but undeclared)"*. **Verified:** `pyproject.toml:24` has `spicelib>=1.5.1` but no `skidl`. The package imports successfully only because it's installed in the dev environment. Any fresh install / CI run / new contributor will hit an `ImportError` on `import kicad_agent.circuit_ir`.

**Condition:** Add `skidl>=2.2.3` to `pyproject.toml` dependencies. (F-07)

### C-05 [MEDIUM]: Close the test coverage gap — `converter.py` (13%) and `emitter.py` (7%) are untested legacy pipelines

Overall `circuit_ir/` coverage is **68%**, below the project's 80% gate (`pyproject.toml` enforces this — the coverage run FAILS). The breakdown:

| Module | Coverage | Status |
|--------|----------|--------|
| `types.py` | 100% | ✅ |
| `skidl_emitter.py` | 98% | ✅ |
| `symbol_resolver.py` | 96% | ✅ |
| `hierarchy_flattener.py` | 97% | ✅ |
| `__init__.py` | 94% | ✅ |
| `skidl_circuit.py` | 80% | ⚠️ (fallback paths uncovered) |
| `skidl_to_kicad.py` | 68% | ⚠️ (`skidl_to_kicad_sch` exec path uncovered) |
| `parts_mapper.py` | 38% | ❌ |
| `converter.py` | 13% | ❌ (the CLI-shelling path) |
| `emitter.py` | 7% | ❌ (the legacy emitter) |

The two worst-covered modules (`converter.py`, `emitter.py`) are precisely the ones the production op handler uses (per C-01). If C-01 deletes them, coverage jumps. If they're kept, they need tests.

**Condition:** After C-01, either the legacy `converter.py`/`emitter.py`/`parts_mapper.py` are removed (preferred — they duplicate the tested pipeline) or they get tests. The `skidl_circuit.py` fallback paths (generic-connector fallback, wire-error diagnostics) need tests regardless. Target: 80%+ on `circuit_ir/` with the coverage gate passing. (F-08)

### C-06 [MEDIUM]: Run the canonical validation harnesses (ADSR + backplane) — CONV-09/CONV-10 are unmet

**The plan's DoD requires** two real-world validation harnesses: `scripts/validate_skidl_adsr.py` (CONV-09) and `scripts/validate_skidl_backplane.py` (CONV-10). **Verified:** neither script exists (`ls scripts/validate_skidl_*.py` → no matches). These are the two acceptance tests that prove the converter works on designs Bret actually built — the 35-part ADSR (ERC match) and the 16-sheet/94-part backplane (hierarchy flatten). Without them, CONV-09 and CONV-10 are unchecked, and the multi-unit (W3) and hierarchy-flatten (W4) capabilities are unproven on anything harder than the 2-part LED fixture.

**Condition:** Create and run both harnesses against the analog-ecosystem schematics. CONV-09 pass criterion: ADSR ERC error count matches the original `adsr-erc.rpt`. CONV-10 pass criterion: all 94 parts present, cross-sheet rails (GNDA, I2C_SDA, I2C_SCL) merged. If the harnesses reveal bugs, that's expected — fix forward. But the phase cannot be called DONE until these exist and pass. (F-09, F-10)

---

## Findings (12 total)

| # | Sev | Area | Description |
|---|-----|------|-------------|
| F-01 | HIGH | Integration | `convert_to_skidl` op handler shells out to CLI + `eval()`s output instead of calling `build_circuit()` in-process. Plan's W6-4 spec violated. → C-01 |
| F-02 | HIGH | Security | `converter.py:61` uses `eval()` on subprocess stdout. Arbitrary code execution risk if CLI output is ever attacker-influenced (low likelihood, but an SLC/red-flag pattern). → C-01 |
| F-03 | HIGH | Dead code | `_CIRCUIT_IR_HANDLERS` registry imported by executor (line 52) but **never dispatched** — no `if root.op_type in _CIRCUIT_IR_HANDLERS` branch exists. The `ops/handlers/circuit_ir.py` handler is unreachable. Only the `_SCHEMATIC_QUERY_HANDLERS` registration makes `convert_to_skidl` work. → C-01 |
| F-04 | HIGH | SLC | Two schema files (`_schema_circuit.py` + `_schema_circuit_ir.py`) define `ConvertToSkidlOp` with **different fields** (`representation` vs `level`; `output_dir` vs `output_file`). Two sources of truth. → C-02 |
| F-05 | HIGH | SLC | SLC compliance tests fail: op count 139 (docs) vs 150 (schema). The 11-op delta includes the duplicate `ConvertToSkidlOp` class being double-counted. → C-02 |
| F-06 | MED | SLC | `ConvertFromSkidlOp` is a phantom: defined in schema, not in union, no handler, no dispatch, no test. Violates "no phantom operations" criterion. → C-03 |
| F-07 | MED | Packaging | `skidl` not declared in `pyproject.toml`. Fresh installs break on `import circuit_ir`. Plan's DoD explicitly requires this. → C-04 |
| F-08 | MED | Coverage | `circuit_ir/` at 68% coverage, below 80% gate. `converter.py` (13%) and `emitter.py` (7%) — the production code path — are untested. Coverage run FAILS. → C-05 |
| F-09 | MED | Validation | CONV-09 (ADSR ERC match) and CONV-10 (backplane 16-sheet flatten) harnesses don't exist. Two of the plan's hardest acceptance criteria are unverified. → C-06 |
| F-10 | MED | Correctness | No test exercises multi-unit symbols (NE5532, RP2350B) — the highest-risk pitfall (#1). The `symbol_resolver` tests only cover single-unit `Device:R/C/LED`. The `_0_0→_1_1` rename is in code but untested on a real multi-unit fixture. → C-06 |
| F-11 | LOW | API drift | `build_circuit` signature in code: `build_circuit(sch_path, *, symbol_dir)` — takes a path, returns `(circuit, circuit_ir)`. Plan spec: `build_circuit(schematic_ir, nets, *, symbol_dir)` — takes `SchematicIR` + nets dict. The implementation is arguably better (self-contained), but the divergence from plan + the W6-4 handler example means the handler can't use the plan's calling convention. Document the actual signature in the module docstring. |
| F-12 | LOW | Hierarchy | `hierarchy_flattener.flatten_hierarchy` tags every part with `sheet=str(root_sch_path.parent)` even for a single-sheet schematic. The plan intends `sheet=None` for root components and a path for sub-sheet components (W4-7). Current impl doesn't distinguish — it can't, because it delegates entirely to `extract_nets` on the root file and never traverses sub-sheets recursively. True multi-sheet flattening (W4-1's "recursively traverse sheet instances") is not implemented; it relies on `extract_nets` already having resolved hierarchy. This needs verification against the backplane fixture (C-06). |

---

## SLC Compliance Check

| Criterion | Status | Evidence |
|-----------|--------|----------|
| **No stub operations** | ⚠️ FAIL | `convert_from_skidl` is a phantom op — schema class exists, no handler, no dispatch, no test (F-06) |
| **No phantom operations** | ⚠️ FAIL | Same as above (F-06) |
| **No dead/duplicate code** | ⚠️ FAIL | Two `ConvertToSkidlOp` schema files with divergent fields (F-04); `_CIRCUIT_IR_HANDLERS` never dispatched (F-03); legacy `converter.py`/`emitter.py`/`parts_mapper.py` duplicate the tested pipeline |
| **Doc-schema consistency** | ❌ FAIL | README + SKILL.md say 139 ops, schema has 150. SLC tests fail (F-05) |
| **No `eval`/`exec`/arbitrary code** | ⚠️ FAIL | `converter.py:61` `eval()`; `skidl_to_kicad.py:160` `exec()` + `pickle` round-trip (F-02) |
| **Single source of truth** | ⚠️ FAIL | Two schema files for one op; two `_is_power_net_name`/`_is_power_name` functions (duplicated in `skidl_circuit.py:301` and `hierarchy_flattener.py:116`); two `_extract_components` functions (`skidl_circuit.py:183` and `converter.py:84`) |
| **Coverage gate (80%)** | ❌ FAIL | 68% on `circuit_ir/` (F-08) |
| **Frozen immutable types** | ✅ PASS | `types.py` all frozen, tests confirm `AttributeError` on mutation |
| **Import guard (pitfall #6)** | ✅ PASS | `_ensure_skidl_env` correctly sets env before `import skidl`; test confirms no warnings |
| **No scope creep** | ✅ PASS | Implementation stays within the 6-wave scope; no over-engineering |

**SLC Decision: NOT MET (4 failures).** Resolving C-01, C-02, C-04 closes all blocking SLC failures.

---

## Evidence-Base Verification (all claims checked)

| Plan claim | Citation | Verified |
|------------|----------|----------|
| `build_circuit` composes `extract_nets` + `SchematicIR` | `skidl_circuit.py:70` calls `extract_nets(sch_path)` | ✅ |
| Import guard sets env before `import skidl` | `__init__.py:64` `_ensure_skidl_env()` then `import skidl` :67 | ✅ |
| L1 emission: one `+=` per pin connection | `skidl_emitter.py:99-101` loop emits `var += ref["pin"]` | ✅ |
| L2 emission: compact net-summary dicts | `skidl_emitter.py:166-169` `# nets: {...}` | ✅ |
| `_0_0 → _1_1` rename handled | `symbol_resolver.py:71-76` regex sub | ✅ |
| `extends` inheritance walked | `symbol_resolver.py:56-61` `_resolve_extends` | ✅ |
| Raw S-expr emission (not kiutils) | `skidl_to_kicad.py` string template, no kiutils import | ✅ |
| 33 tests passing | `pytest tests/circuit_ir/` → 33 passed | ✅ |
| Op handler calls `build_circuit` | **❌ FALSE** — calls `KiCadToSkidlConverter` which shells to CLI | F-01 |
| `convert_from_skidl` registered + self-serializing | **❌ FALSE** — not in union, no handler, not in `SELF_SERIALIZING_OPS` | F-06 |
| `skidl>=2.2.3` in pyproject.toml | **❌ FALSE** — not present | F-07 |
| ADSR/backplane harnesses exist | **❌ FALSE** — `scripts/validate_skidl_*.py` absent | F-09 |
| `populate_pcb_from_netlist` 5 fixes ported to source | **❌ FALSE** — grep finds none of the 5 workaround names in `pcb_populate.py` | (W6-3 unmet) |

**7 of 13 verified claims are FALSE.** The implementation's core modules are solid, but the integration layer, packaging, and validation deliverables are substantially incomplete relative to the plan's DoD.

---

## Recommendations for Phases 157–160

**Phase 157 (Floor Planner)** — depends on `circuit_ir` as input:
1. **Lock the `PartDescriptor.sheet` contract now.** Phase 157's module-aware placement relies on `sheet` metadata to group components by sub-sheet. Current impl (F-12) tags everything with the root path. Before 157 starts, validate against the backplane that `sheet` actually distinguishes sub-sheets — if `extract_nets` doesn't expose per-sheet origin, Phase 157's floor planner will need a different input or a W4 fix.
2. **Consumer-driven API freeze.** Have the 157 plan spec exactly which `circuit_ir` fields/methods it consumes (`CircuitIR.parts`, `.nets`, `PartDescriptor.footprint`, `.lib_id`). Freeze those before 157 builds on them.
3. **Resolve C-01 before 157 starts.** If 157 calls `convert_to_skidl` to get a `CircuitIR` for placement, it'll hit the broken handler.

**Phase 158 (SPICE Pipeline)** — consumes `CircuitIR` for analog sub-circuits:
1. The `is_power` flag on `NetDescriptor` is the SPICE rail-injection hook. Verify power-net coalescence (a `+3V3` power symbol + `+3V3` global label → one net) works — it's only tested on the 2-part LED fixture. The mixed power+label coalescence test (W5-7) was not written.

**Phase 159 (Training Data)** — consumes L2 emission:
1. The L2 emitter is in good shape (98% coverage). But L2's `# nets: {...}` summary format should be frozen before 159 builds a dataset around it. Add a golden-file test (the plan's W2-8 golden files were not created).
2. Determinism: the emitter sorts parts/nets, good. But `part.ref` assignment from skidl is non-deterministic across runs unless `build_circuit` sets `p.ref = pd.reference` explicitly (it does, `skidl_circuit.py:105` — ✅). Confirm this holds on multi-part fixtures.

**Phase 160 (Milestone close)**:
1. The full `pytest tests/` suite must pass, including the SLC compliance tests (currently 2 failing) and the coverage gate (currently failing on `circuit_ir/`).
2. The two duplicate schema files (C-02) and the phantom op (C-03) must be resolved — they're the kind of drift that compounds across phases.

**Cross-cutting:** The pattern of "core modules well-tested, integration layer bypasses them" is the single biggest risk. Recommend that Phase 157's plan include an explicit integration test that invokes `convert_to_skidl` via the executor (not by calling `build_circuit` directly) to catch handler-wiring regressions.

---

## Conditions Summary (before Phase 157)

| ID | Severity | Blocks 157? | Effort |
|----|----------|-------------|--------|
| C-01 | BLOCKING | Start | ~2-3h (rewrite 2 handlers, delete legacy converter path) |
| C-02 | BLOCKING | Start | ~1h (delete 1 schema file, update docs, fix counts) |
| C-03 | MEDIUM | Ship | ~1h (wire or remove `convert_from_skidl`) |
| C-04 | MEDIUM | Ship | ~5min (add `skidl>=2.2.3` to pyproject) |
| C-05 | MEDIUM | Ship | ~2h (coverage to 80%, remove/test legacy modules) |
| C-06 | MEDIUM | Ship | ~4-8h (ADSR + backplane harnesses; may surface bugs) |

**Bottom line:** The phase built the right core (`build_circuit`, `emit_build_py`, `circuit_to_kicad_sch`) and proved the composition principle. But it then wired the user-facing op to a different, weaker code path and left the plan's acceptance criteria (CONV-09/10, pyproject dep, registry completeness) unmet. Fix C-01 and C-02 to unblock Phase 157; close C-03 through C-06 before declaring the milestone shipped.

---

# FINAL EXECUTION REVIEW — Phase 156 (SKIDL Converter)

**Date:** 2026-07-03
**Reviewer:** Council of Ricks (execution pass, ground-truth verified)
**Scope:** Final review after C-01, C-02, C-03, C-04, C-06 were addressed (C-05 not claimed)
**Method:** Every claim below was checked against the live codebase — handlers invoked through the real `OperationExecutor`, tests run, harness executed, coverage measured. No claims were taken on trust.

---

## Verdict: APPROVED WITH CONDITIONS — 3 of 5 claimed fixes are genuinely complete; 2 regressed into new defects

The core engineering remains sound and **one major win landed**: CONV-09 (ADSR validation) now **passes for real** — 39 parts, 186 nets, **0 ERC errors matching the original schematic**, not a self-skipping stub. The forward KiCad→SKIDL op (`convert_to_skidl`) now genuinely calls `build_circuit()` in-process and returns correct results through the executor. `skidl` is declared in `pyproject.toml`.

But the closure was **incomplete in exactly the ways that matter for downstream phases.** Two of the five "addressed" conditions did not survive empirical verification:

1. **C-02 is NOT closed.** The duplicate schema file was deleted (good — count dropped 150→149), but the README.md / SKILL.md operation-count update was never made. **The two SLC compliance tests still fail: `139 (docs) != 149 (schema)`.** This is the exact same failure as the first review.
2. **C-03 introduced a regression.** `convert_from_skidl` was wired (schema + handler + `SELF_SERIALIZING_OPS` + a test), but the handler is registered under `@register_schematic` while the op writes a *new* file, and the op was never added to `CREATE_OP_TYPES`. Result: invoking it through the executor raises `FileNotFoundError: Target file not found` before the handler runs. **The reverse direction of the bidirectional bridge is unreachable via the op that users invoke.** It is still, functionally, a phantom op — the same disease C-03 was meant to cure.

The reverse *function* (`circuit_to_kicad_sch`) works when called directly, so the underlying capability exists. The op-integration layer is where it breaks. Phase 157 must not depend on `convert_from_skidl` working until this is fixed.

---

## Condition Closure Status (empirically verified)

| ID | Claimed | Actual Status | Evidence |
|----|---------|---------------|----------|
| **C-01** | ✅ addressed | ✅ **CLOSED (with field-mismatch defect)** | `schematic_query.py:278` handler now calls `build_circuit()` → `emit_build_py()`. Verified end-to-end via executor: `convert_to_skidl` returns `parts:2, nets:4, representation:L1`. `eval()`/`subprocess` removed from the dispatched path. **Defect:** handler reads `op.representation`/`op.output_dir`; surviving schema defines `level`/`output_file`. `level` works via `getattr` fallback, but `output_dir` is always missing → **write-to-disk (`output_file`) silently never fires.** |
| **C-02** | ✅ addressed | ❌ **NOT CLOSED** | `tests/test_slc_compliance.py` → 2 FAILED: `test_readme_operation_count_matches_schema` and `test_skill_md_operation_count_matches_schema`, both `assert 139 == 149`. Docs never updated. Schema dedup done; doc sync missed. |
| **C-03** | ✅ addressed | ❌ **REGRESSED — still a phantom** | `convert_from_skidl` schema + handler + `SELF_SERIALIZING_OPS` entry exist, but invoking via `OperationExecutor` raises `FileNotFoundError` (op not in `CREATE_OP_TYPES`; registered under `@register_schematic` which requires an existing file). No executor-level test exists — `TestRoundTrip` calls `circuit_to_kicad_sch()` directly. |
| **C-04** | ✅ addressed | ✅ **CLOSED** | `pyproject.toml:25`: `skidl>=2.2.3`. |
| **C-05** | (not claimed) | ⚠️ **OPEN — acknowledged** | `circuit_ir/` coverage **68%**, coverage gate **FAILS** (`67.51% < 80%`). `converter.py` 13%, `emitter.py` 7%, `parts_mapper.py` 38% (the now-legacy modules). Not claimed as fixed; correctly still open. |
| **C-06** | ✅ addressed | ⚠️ **PARTIAL** | CONV-09 (ADSR) **PASSES genuinely**: 39 parts, 186 nets, 4 power nets, **0 ERC errors == 0 original errors**. CONV-10 (backplane) **NOT MET**: `scripts/validate_skidl_backplane.py` does not exist. |

---

## The Two Blocking Regressions (must fix before Phase 157 builds on this)

### REG-1 [BLOCKING]: C-02 doc-count sync was skipped — SLC tests still red

This is the simplest possible fix and it was missed. `count_op_classes()` dynamically counts `*Op(BaseModel)` classes across `schema.py` + `_schema_*.py` = **149**. README.md and SKILL.md both still assert **139**. The SLC compliance suite (`tests/test_slc_compliance.py`) has two hard red failures because of it.

**Why it matters:** Phase 160's "full `pytest tests/` passes" milestone gate cannot close while these fail. The project's own SLC "doc-schema consistency" criterion is violated. And it's a 2-line fix.

**Fix:** Update the operation-count assertions in `README.md` and `SKILL.md` from 139 → 149 (or whatever `count_op_classes()` currently returns). Re-run `pytest tests/test_slc_compliance.py` to confirm green.

### REG-2 [BLOCKING]: C-03 — `convert_from_skidl` op is unreachable (reverse bridge broken)

This is the serious one. The reverse direction of the bidirectional bridge — the entire point of CONV-08 ("SKIDL → KiCad") — does not work through the operation that an LLM or user would invoke.

**Root cause (verified by direct execution):**
```
OperationExecutor.execute():
  if root.op_type in _CREATE_OP_TYPES:   # create_schematic, create_pcb, ... — convert_from_skidl NOT here
      return execute_create(...)
  ...
  if not file_path.exists():             # ← fires for convert_from_skidl
      raise FileNotFoundError(f"Target file not found: {file_path}")
```
`convert_from_skidl` is registered under `@register_schematic` (`handlers/schematic.py:1051`) and tagged `category: "create"` in the registry (`registry.py:831`), but it is **not** a member of `CREATE_OP_TYPES` (`execution.py:113`), which is the set the executor consults to bypass the file-existence check for ops that create new files.

**Evidence (executed, not asserted):**
```python
op = Operation.model_validate({'root':{'op_type':'convert_from_skidl',
       'target_file':'_convtest_out.kicad_sch','source':'_convtest_build.py'}})
executor.execute(op)
# → FileNotFoundError: Target file not found: .../_convtest_out.kicad_sch
```
The handler never runs. The op is unreachable. The "test" that supposedly exercises it (`test_hierarchy_and_reverse.py::TestRoundTrip`) calls `circuit_to_kicad_sch()` directly, bypassing the executor entirely — so the dispatch bug was never caught.

**Fix (pick one):**
- **(a)** Add `"convert_from_skidl"` to `CREATE_OP_TYPES` in `execution.py:113` and route it through `execute_create` (or a dedicated create branch that invokes the `SELF_SERIALIZING_OPS` handler), **and** add an executor-level integration test that invokes the op via `OperationExecutor` (not a direct function call).
- **(b)** If Phase 157 doesn't need the reverse op yet, remove `ConvertFromSkidlOp` + the handler + the `SELF_SERIALIZING_OPS` entry and defer to a later phase — but do not leave it documented-but-dead.

Either way, add a test that goes through the executor. The pattern of "core function tested directly, op handler untested" is exactly what allowed C-03 to regress.

---

## Bidirectional Bridge: Functional Assessment

| Direction | Op reachable via executor? | Underlying function works? | Verdict |
|-----------|----------------------------|----------------------------|---------|
| **KiCad → SKIDL** (`convert_to_skidl`) | ✅ Yes — returns correct `parts`/`nets`/`code` | ✅ `build_circuit` + `emit_build_py` | **FUNCTIONAL** (write-to-disk defect noted) |
| **SKIDL → KiCad** (`convert_from_skidl`) | ❌ No — `FileNotFoundError` | ✅ `circuit_to_kicad_sch` works when called directly | **BROKEN at the op layer** |
| **Round-trip** (KiCad→SKIDL→KiCad) | ⚠️ Only via direct function calls | ✅ `TestRoundTrip` passes (part-count preserved) | **Proven at unit level, unproven at op level** |

**Conclusion:** The bridge is **unidirectionally functional** (forward works), **asymmetrically broken** (reverse op unreachable). Phase 157 (Floor Planner) consumes `CircuitIR` from the forward path, so it is **not blocked** by REG-2. But any phase that needs to emit a `.kicad_sch` from a SKIDL circuit (158/159 round-trip, 160 milestone) is blocked until REG-2 is fixed.

---

## SLC Compliance Check (re-run)

| Criterion | Status | Evidence |
|-----------|--------|----------|
| No stub operations | ⚠️ FAIL | `convert_from_skidl` reachable in schema but unreachable via executor (REG-2) |
| No phantom operations | ⚠️ FAIL | Same — op is documented, registered, self-serialized, but cannot be invoked |
| No dead/duplicate code | ⚠️ FAIL | `ops/handlers/circuit_ir.py` (`_CIRCUIT_IR_HANDLERS`) imported by executor (`executor.py:52`) but **never dispatched** — dead. Still imports legacy `KiCadToSkidlConverter`. Legacy `converter.py`/`emitter.py`/`parts_mapper.py` remain at 7–13% coverage. |
| Doc-schema consistency | ❌ FAIL | README + SKILL.md say 139, schema has 149 (REG-1) |
| No `eval`/`exec`/arbitrary code | ⚠️ PARTIAL | Removed from the dispatched `convert_to_skidl` path ✅. But **still present** in `converter.py:61` (`eval`), `skidl_to_kicad.py:160` (`exec`), `skidl_to_kicad.py:162-178` (`pickle`). These are the legacy `skidl_to_kicad_sch()` function and `KiCadToSkidlConverter` — reachable via `__init__` exports and the dead handler. |
| Coverage gate (80%) | ❌ FAIL | 67.51% on `circuit_ir/` (C-05, open) |
| Frozen immutable types | ✅ PASS | Unchanged |
| Import guard (pitfall #6) | ✅ PASS | Unchanged |
| Single source of truth | ⚠️ FAIL | Handler reads `representation`/`output_dir`; schema defines `level`/`output_file` (field-name drift from the deleted plan-compliant `_schema_circuit.py`) |

**SLC Decision: NOT MET (5 failures, 2 of them new regressions).**

---

## Remaining Gaps Before Phase 157

| Gap | Severity | Blocks 157? | Effort |
|-----|----------|-------------|--------|
| **REG-1**: Update README/SKILL.md op count 139→149 | HIGH | No (blocks 160 gate) | ~5 min |
| **REG-2**: Fix `convert_from_skidl` dispatch (add to `CREATE_OP_TYPES` or remove op) + executor-level test | HIGH | No (157 is forward-only) | ~1–2h |
| Field-name drift: align handler (`representation`/`output_dir`) with schema (`level`/`output_file`) — `output_file` write-to-disk currently dead | MED | No | ~20 min |
| Delete dead `ops/handlers/circuit_ir.py` + its import in `executor.py:52` | MED | No | ~5 min |
| Remove or test legacy `converter.py`/`emitter.py`/`parts_mapper.py` (the `eval`/`subprocess` code still lives here) | MED | No (blocks 160 coverage gate) | ~2h |
| C-05: coverage 68%→80% gate | MED | No (blocks 160) | ~2h |
| CONV-10: `scripts/validate_skidl_backplane.py` (16-sheet hierarchy flatten) | MED | No (validates W4 on real design) | ~4h |
| `validate_registry_completeness()` pre-existing delta (schema 152 / registry 151, missing `place_and_wire_power_units`) | LOW | No | pre-existing, not Phase 156 |

### Phase 157-specific readiness (the consumer perspective)

Phase 157 (Floor Planner) consumes the **forward** path: `CircuitIR.parts`, `.nets`, `PartDescriptor.footprint`/`lib_id`/`sheet`. That path is **functional** (REG-1/REG-2 are orthogonal to it). **157 can start.** Two carry-forward cautions:

1. **`PartDescriptor.sheet` semantics (F-12 from review 1, still true):** `flatten_to_circuit_ir` tags every part with `sheet=<root_sch_path.parent>` and does not distinguish sub-sheets — it delegates to `extract_nets` on the root file and never recurses. If Phase 157's module-aware placement groups by `sheet`, validate against a multi-sheet design first (CONV-10 would surface this). Single-sheet ADSR passed; multi-sheet is unproven.
2. **Consumer-driven API freeze:** 157 should spec exactly which `circuit_ir` fields it reads and freeze them before building. `build_circuit`'s actual signature (`build_circuit(sch_path, *, symbol_dir) -> (Circuit, CircuitIR)`) differs from the plan's (`build_circuit(schematic_ir, nets, *, symbol_dir)`) — the code version is better, but document it so 157 doesn't assume the plan's calling convention.

---

## Bottom Line

The Phase 156 core is real and the hardest acceptance criterion (CONV-09, real-design ERC match) is genuinely met. But **the closure pass was sloppy in the integration layer** — the two things that would have been caught by a single executor-level integration test (the C-02 doc count and the C-03 dispatch) both regressed or were skipped. The pattern identified in review 1 — *"core modules well-tested, integration layer bypasses them"* — **persisted into the fix pass.** The bidirectional bridge is half-built: forward works through the op, reverse works only as a direct function call.

**Recommendation:** Phase 157 may start now (it consumes only the working forward path). Before any phase declares the milestone shipped (157→160), close REG-1 and REG-2, and **add an executor-level integration test for both `convert_to_skidl` and `convert_from_skidl`** so this class of "wired but unreachable" regression cannot recur. The single highest-leverage fix is that test.

---

# COUNCIL-PLAN-REVIEW: v5.0 Skidl-Native Design Pipeline — FINAL MILESTONE REVIEW (Phases 156–160)

**Date:** 2026-07-03
**Scope:** Complete v5.0 milestone (Phases 156 SKIDL Converter, 157 Floor Planner, 158 SPICE Pipeline, 159 AI Training Data, 160 NL Circuit Generation)
**Verdict:** **REJECT — NOT functionally complete. Three of five phases are scaffolds; the milestone's signature criteria (NLGEN-03/04/05, CONV-10, TRAIN-01/03/04) are unmet. Two new hard bugs found (one breaks every ngspice sim). Prior blocking conditions partially closed.**

---

## 1. Executive Summary

This is the final review of the v5.0 milestone. The investigation was conducted by direct execution of every claim — running tests, invoking ops through the executor, running ngspice, and diffing delivered code against each phase PLAN. The headline numbers in the milestone request (**"293 tests passing across all phases," "5 phases implemented"**) **do not survive verification**:

- **Actual v5.0 test count: 90**, not 293. (33 circuit_ir + 19 floorplan + 15 spice + 7 training_data + 16 generation). The 293 figure does not appear in any planning document; it conflates v5.0 tests with the whole-project suite (6,919 tests collected). All 90 v5.0 tests do pass — but **passing is not the same as proving the criteria**, because several tests are written to pass even when the underlying capability is broken (see §4, the ngspice finding).
- **Phase 156 (SKIDL Converter): genuinely the strongest phase.** CONV-09 (ADSR, 39 parts, 0 ERC errors match) is real and verified. The two prior blocking conditions (REG-1 doc-count, REG-2 reverse-op dispatch) are **partially closed**: REG-1 is fully closed (SLC op-count tests green), REG-2's *dispatch* is fixed but the underlying handler relies on legacy `exec`/`pickle`/`subprocess` and has a field-name drift defect; and no executor-level integration test exists for either convert op (the one fix the prior review called "highest leverage").
- **Phase 157 (Floor Planner): solid and proportionate.** 6 rule types, YAML parser, lowering + applier, 19 tests. This phase meets its plan.
- **Phase 158 (SPICE Pipeline): a hard bug invalidates the core deliverable.** Every AC testbench generated by `generate_ac_testbench()` makes ngspice **exit 1** (`Undefined parameter [gain_db]` in the `.MEASURE` expression). `run_simulation()` swallows the failure and returns `passed=True` with empty traces — so the 15 tests pass but **no real simulation result is ever produced.** SPICE-01–05 (the phase's purpose: "headless simulation") are not actually met.
- **Phase 159 (AI Training Data): 1 of 7 planned modules built.** Only `nl_generator.py` exists; the corpus batch converter (TRAIN-01, the 71K-repo pipeline), placement/vision pair builders (TRAIN-03), and the SPICE reward combiner (TRAIN-04) are entirely absent. No training can run on this output.
- **Phase 160 (NL Generation): a skeleton, not the capstone.** 2 of 7 planned modules. The SPICE gate (`_gate_spice`) does not run ngspice or compare to spec — it returns PASSED after only checking `is_simulatable`. No `pipeline.py` (NLGEN-04), no `repair_loop.py`, no `eval_harness.py`, no canonical preamp test (NLGEN-05). Three of the five NLGEN criteria are unmet.

**Net:** The milestone is **not shippable and not ready for the Vast.ai training run.** Phase 156 + 157 are real; 158 has a fixable but currently-breaking bug; 159 and 160 are scaffolds that do not deliver their acceptance criteria.

---

## 2. Council Composition (perspectives applied)

| Rick | Lens applied | Verdict contribution |
|------|--------------|----------------------|
| **security-rick** | `exec`/`pickle`/`subprocess` on LLM-generated code; trust boundaries | Phase 160 `_gate_erc` and `generate_circuit` `exec()` LLM output in-process; Phase 156 reverse handler `exec`+`pickle`. Real attack surface on the LLM-driven path. |
| **simple-rick** | SLC, scope honesty, claims-vs-delivered | Test-count claim (293 vs 90) and "5 phases implemented" vs the scaffolds in 159/160 fail the honesty bar. |
| **shyam-rick** | API/integration correctness, op reachability | REG-2 dispatch fixed but no executor test; field-drift (`output_dir` vs `output_file`) still dead. |
| **quilt-rick** | Simulation correctness (the SPICE phase) | Found the `.MEASURE` ngspice bug — every AC sim exits 1 silently. |
| **vision-rick** | Training-data & model-task alignment | Phase 159 produces NL→SKIDL pairs only; no placement/vision pairs, no reward signal. Training run cannot proceed as specified. |

---

## 3. Answers to the Five Review Questions

### Q1. Is the v5.0 milestone functionally complete?
**No.** Per-phase status against the ROADMAP success criteria:

| Phase | Plan modules | Built | Criteria met? |
|-------|-------------|-------|---------------|
| **156 SKIDL Converter** | 9 | 9 | **PARTIAL.** CONV-09 (ADSR) ✅ verified. CONV-10 (backplane 16-sheet) ❌ `scripts/validate_skidl_backplane.py` still does not exist. Bidirectional reverse op ⚠️ dispatch fixed, handler uses unsafe exec/pickle and is untested through the executor. |
| **157 Floor Planner** | 3 | 3 | **YES** (within plan scope). 6 rule types, YAML parser, lower+apply, fail-closed hard rules. 19 tests. (Note: plan's SC#5 "mono blade scores higher WITH floor plan" is not validated — no such benchmark exists — but the infra is sound.) |
| **158 SPICE Pipeline** | 5 | 5 | **NO — core deliverable broken.** ngspice exits 1 on every AC testbench (§4). Tests pass only because they don't assert on real analysis output. |
| **159 AI Training Data** | 7 | **1** | **NO.** Only `nl_generator.py` (NL describer + SFT pair builder merged). Missing: corpus batch converter (TRAIN-01), placement/vision pair builders (TRAIN-03), SPICE reward combiner (TRAIN-04), QA. |
| **160 NL Generation** | 7 | **2** | **NO.** Only `nl_to_skidl.py` + `gate_chain.py`. SPICE gate doesn't simulate or compare spec (NLGEN-03 ❌). No pipeline orchestrator (NLGEN-04 ❌). No canonical preamp test (NLGEN-05 ❌). |

### Q2. Are there any blocking gaps?
**Yes — five blockers:**

1. **[BLK-1] ngspice AC testbench bug (Phase 158/160).** `generate_ac_testbench()` emits `.MEASURE AC bandwidth WHEN vdb(out)='gain_db-3'` — ngspice rejects this (`Undefined parameter [gain_db]`, exit 1). `run_simulation()` swallows it → `passed=True`, empty traces. **Breaks every SPICE-dependent criterion (SPICE-01–05, NLGEN-03, TRAIN-04).**
2. **[BLK-2] Phase 159 missing 6 of 7 modules.** No corpus batch converter → no 71K-repo training data (TRAIN-01). No placement/vision pairs (TRAIN-03). No SPICE reward combiner (TRAIN-04). The Vast.ai run has no dataset.
3. **[BLK-3] Phase 160 SPICE gate is a stub.** `_gate_spice` returns PASSED after only `is_simulatable()`; it never calls `run_simulation` and never compares measured values to `spec_targets`. NLGEN-03 unmet.
4. **[BLK-4] Phase 160 capstone unbuilt.** No `pipeline.py` (NLGEN-04), no `repair_loop.py`, no `eval_harness.py`, no canonical preamp test (NLGEN-05).
5. **[BLK-5] `convert_from_skidl` executor-level integration test still missing.** The prior review's single highest-leverage recommendation ("add an executor-level integration test for both convert ops") was **not done.** `TestRoundTrip` still calls `circuit_to_kicad_sch()` directly. Dispatch is wired, but the op path that users/LLMs invoke is unverified.

### Q3. What's needed before the Vast.ai training run (Phase 160)?
**Four things, in order:**
1. **Fix BLK-1 (ngspice testbench).** Without working simulation, there is no reward signal and no spec gate. ~1–2h: rewrite the `.MEASURE` expressions (ngspice requires the prior-measure reference syntax `param=<expr>` or a two-pass approach).
2. **Build the Phase 159 corpus converter + reward combiner (BLK-2).** `skidl_corpus.py` (batch 71K → SKIDL L2) and `sim_aware_reward_combiner.py` (SPICE `DegradationReport` → `sim_score`). These are the dataset and the reward — the two things the Vast.ai run consumes. ~1–2 days.
3. **Generate and spot-check the dataset** (corpus_qa.py, TRAIN-02 quality) — confirm NL→SKIDL pairs parse and the representation matches what the adapter will see at inference.
4. **Hardening:** remove `exec()` of LLM-generated code from the in-process gate path (BLK/security), or sandbox it; the training/inference loop must not execute arbitrary model output in the trainer process.

**The Vast.ai run cannot proceed on the current artifact set.** There is no dataset (159 incomplete), no reward signal (158 broken), and no spec gate (160 stub). Running now would train on a tiny hand-curated set with no physics-grounded reward.

### Q4. SLC compliance
**NOT MET (4 failures):**

| Criterion | Status | Evidence |
|-----------|--------|----------|
| No stub/phantom operations | ⚠️ PARTIAL | `convert_from_skidl` now reachable (REG-2 dispatch fixed ✅), but handler path untested + uses exec/pickle. |
| No dead/duplicate code | ⚠️ FAIL | `ops/handlers/circuit_ir.py` (`_CIRCUIT_IR_HANDLERS`) still imported by executor, still never dispatched — dead (carried from prior review). Legacy `converter.py` (13% cov), `emitter.py` (7%), `parts_mapper.py` (38%) remain. |
| Doc-schema consistency | ✅ **PASS** | REG-1 CLOSED. All 5 `TestOperationCountConsistency` tests green (149 ops). |
| No `eval`/`exec`/arbitrary code | ❌ FAIL | `nl_to_skidl.py:163` and `gate_chain.py:154` `exec()` LLM-generated SKIDL in-process. `skidl_to_kicad.py:160` `exec` + `:178` `pickle`. (Phase 160 *amplifies* this — it's on the LLM output path.) |
| Coverage gate (80%) | ❌ FAIL | `circuit_ir/` **67.51%** — unchanged since prior review (C-05 open). Milestone gate fails. |
| Frozen immutable types | ✅ PASS | — |
| Single source of truth | ⚠️ FAIL | Handler reads `op.output_dir`; schema defines `output_file` (field drift, still open). Write-to-disk of generated SKIDL silently never fires. |

### Q5. Recommendations for next steps
See §6 (Prioritized Remediation).

---

## 4. The Two New Hard Bugs (executed, not asserted)

### BUG-1 [BLOCKING]: ngspice exits 1 on every AC testbench — `run_simulation` reports success

**Reproduction (executed in this review):**
```python
from kicad_agent.spice.testbench import generate_ac_testbench
from kicad_agent.spice.ngspice_runner import run_simulation
cir = generate_ac_testbench(netlist='R1 in out 1000\nC1 out 0 1u', input_node='in', output_node='out')
r = run_simulation(cir, 'rc_test', analyses=['ac'])
# → stderr: "ngspice exited 1 for rc_test"
# → r.analyses[0].traces == ()   (empty)
# → r.analyses[0].gain_db is None
# → r.passed == True             ← swallows the failure
```
Direct `ngspice -b` on the generated deck:
```
Undefined parameter [gain_db]
Expression err: gain_db-3} fall=1
ERROR: fatal error in ngspice, exit(1)
```
**Root cause:** `testbench.py` emits `.MEASURE AC bandwidth WHEN vdb(out)='gain_db-3' FALL=1`. ngspice's `.MEASURE` cannot reference a prior measurement's result by bare name in the `WHEN` expression. This is a testbench-generation bug, not an environment issue (ngspice 45.2 is correctly installed).

**Why the 15 tests pass anyway:** `test_spice.py::test_runs_simple_rc_filter` asserts only `isinstance(result, SimulationResult)` and then guards the real checks with `if result.analyses:` / `if ac:`. Since analyses is an empty-but-present tuple, the assertions are skipped. The test suite is **green on a broken pipeline.**

**Impact:** SPICE-01–05 (Phase 158's entire purpose), NLGEN-03 (Phase 160 spec gate), and TRAIN-04 (Phase 159 reward signal) are all non-functional. This single bug blocks three phases.

**Fix:** Rewrite the `.MEASURE` bandwidth expression. ngspice supports `param` form or a two-measure approach: measure `gain_db` then `let`/`meas` the −3dB point with a numeric threshold. ~1–2h including a regression test that asserts `ac.gain_db is not None`.

### BUG-2 [HIGH]: Phase 160 SPICE gate returns PASSED without simulating

`gate_chain.py:189 _gate_spice()`: after `exec()`-ing the SKIDL, it iterates parts calling `is_simulatable()` and on success returns:
```python
GateResult(GateName.SPICE, GateStatus.PASSED, "All parts simulatable (full SPICE verification requires testbench)")
```
It **never calls `run_simulation`, never compares any measured value to `spec_targets`.** The `spec_targets` argument is accepted but unused. NLGEN-03 ("generated SKIDL passes the SPICE validation gate — circuit meets spec targets, e.g. +18dB gain") is **not implemented**, only declared. Combined with BUG-1, even if it did call `run_simulation`, it would get `None` measurements.

**Additionally** — `validate_skidl_code()` in `nl_to_skidl.py` has dead code: the `return True, ""` at line 111 precedes an unreachable import-check (lines 113–114). Minor, but indicative.

---

## 5. Condition Closure Status (from prior Phase 156 review)

| ID | Prior status | Current status | Evidence |
|----|--------------|----------------|----------|
| **REG-1** (doc op-count 139→149) | ❌ NOT CLOSED | ✅ **CLOSED** | `TestOperationCountConsistency` all 5 pass. README.md:222 says 149. |
| **REG-2** (`convert_from_skidl` dispatch) | ❌ REGRESSED | ⚠️ **PARTIAL** | Op added to `CREATE_OP_TYPES` (execution.py:113) — dispatch fixed, no longer FileNotFoundError. BUT: handler calls legacy `skidl_to_kicad_sch()` (exec/pickle/subprocess), and **no executor-level test exists** (TestRoundTrip still calls the function directly). The "highest-leverage fix" was not done. |
| **C-05** (circuit_ir coverage 67.5% < 80%) | ⚠️ OPEN | ⚠️ **STILL OPEN** | Re-measured: **67.51%** — identical. Legacy modules converter.py 13%, emitter.py 7%, parts_mapper.py 38% untouched. Milestone coverage gate fails. |
| **CONV-10** (backplane 16-sheet) | ❌ NOT MET | ❌ **STILL NOT MET** | `scripts/validate_skidl_backplane.py` still absent. Multi-sheet hierarchical flatten unproven. |
| Field-drift (`output_dir` vs `output_file`) | ⚠️ OPEN | ⚠️ **STILL OPEN** | `schematic_query.py:295` still reads `op.output_dir`; schema (`_schema_circuit_ir.py:23`) still defines `output_file`. Write-to-disk of generated SKIDL is dead. |

---

## 6. Prioritized Remediation

| # | Item | Severity | Blocks | Effort |
|---|------|----------|--------|--------|
| 1 | **Fix ngspice `.MEASURE` bandwidth bug** in `testbench.py` + add regression test asserting `gain_db is not None` | BLOCKING | 158, 160 (NLGEN-03), 159 (TRAIN-04) | ~1–2h |
| 2 | **Implement real SPICE spec gate** in `_gate_spice`: call `run_simulation`, compare measured vs `spec_targets` within tolerance (NLGEN-03) | BLOCKING | 160 | ~4h |
| 3 | **Build Phase 159 corpus converter** (`skidl_corpus.py`) — batch 71K → SKIDL L2 (TRAIN-01) | BLOCKING | Vast.ai run | ~1–2 days |
| 4 | **Build `sim_aware_reward_combiner.py`** — DegradationReport → sim_score (TRAIN-04) | BLOCKING | Vast.ai reward | ~4h |
| 5 | **Build Phase 160 `pipeline.py`** orchestrator + canonical preamp test (NLGEN-04, NLGEN-05) | HIGH | 160 capstone | ~1 day |
| 6 | **Add executor-level integration test** for `convert_to_skidl` + `convert_from_skidl` (close REG-2 properly; the prior review's #1 ask) | HIGH | SLC | ~1–2h |
| 7 | **Remove `exec()` of LLM output** from in-process gates (sandbox or subprocess-isolate) | HIGH (security) | LLM-driven path | ~3h |
| 8 | **Delete dead `ops/handlers/circuit_ir.py`** + its executor import | MED | SLC | ~5 min |
| 9 | **Fix field-drift**: handler reads `output_dir`, schema has `output_file` | MED | write-to-disk | ~20 min |
| 10 | **Raise circuit_ir coverage 67.5%→80%** (test or delete legacy converter.py/emitter.py/parts_mapper.py) | MED | milestone gate | ~2h |
| 11 | **CONV-10**: backplane validation script (16-sheet hierarchy flatten) | MED | 156 SC#5 | ~4h |
| 12 | **Build Phase 159 placement/vision pair builders** (TRAIN-03) + corpus_qa | MED | Gemma adapter, dataset quality | ~2 days |

**Sequencing:** 1 → 2 → 3+4 (parallel) → 5. Items 1–4 are the minimum to make the Vast.ai run viable. Items 6–9 are the SLC/quality cleanup that should accompany any "milestone complete" declaration.

---

## 7. What Is Genuinely Good

To be balanced:
- **Phase 156's forward path is real and the hardest criterion (CONV-09) is genuinely met** — 39 parts, 186 nets, 0 ERC errors matching the original ADSR. `build_circuit()` + `emit_build_py()` + `resolve_lib_symbol()` are well-tested (skidl_circuit.py 80%, skidl_emitter.py 98%, symbol_resolver.py 96%).
- **REG-1 was cleanly closed** — the doc/schema op-count sync is correct and tested.
- **Phase 157 is proportionate and well-built** — the 6 rule types, YAML loader, lowering pass, and fail-closed hard-rule enforcement are exactly what the plan called for. This phase is the model for how the others should look.
- **The architecture is sound.** The gate-chain design (parse → ERC → SPICE → floorplan → PCB), the best-of-N-with-repair strategy, and the "SPICE as spec gate not just reward" principle are all correct on paper. The problem is execution completeness, not design.
- **ngspice 45.2 is correctly installed** — the infrastructure for BLK-1's fix exists.

---

## Bottom Line

The v5.0 milestone is **not complete and not ready for the training run.** Two of five phases (156, 157) are real; Phase 158 has a single bug that silently breaks its entire purpose; Phases 159 and 160 are scaffolds that deliver roughly 15–30% of their planned modules and miss their headline acceptance criteria (NLGEN-03/04/05, TRAIN-01/03/04, CONV-10). The test-count claim (293) is inaccurate (actual: 90), and several "passing" tests pass *because they don't assert on the broken behavior* — the ngspice tests are green while every simulation exits 1.

**Recommendation: REJECT milestone completion.** Sequence the remediation as: (1) fix the ngspice testbench bug, (2) build the real SPICE spec gate, (3) build the Phase 159 corpus converter + reward combiner, (4) build the Phase 160 pipeline + canonical test. Re-run this review when NLGEN-05 (the canonical preamp test) passes end-to-end on a real ngspice result — that is the honest milestone gate. Until then, the Vast.ai run would train on an incomplete dataset with no physics-grounded reward signal.
