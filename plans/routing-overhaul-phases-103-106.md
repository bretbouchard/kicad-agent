# Routing Overhaul: Placement-Aware Diagnosis, Negotiation, and Model Repoint

**Date:** 2026-07-01
**Status:** Council Review Pending
**Authors:** Bret Bouchard + ZCode
**Phases:** 103 (Foundation), 104 (Diagnosis), 105 (Negotiation), 106 (Placement-Advisor)
**Dependency chain:** 103 → 104 → 105 (sequential); 106 ∥ 105 (parallel, data from 104)
**Predecessors:** Phase 99 (Freerouting Integration Hardening), Phase 100 (RoutingOrchestrator), Phase 98 (AI Routing Strategy Advisor — to be repointed)

---

## 1. Problem Statement

Our routing stack is a **two-backend hybrid** (Freerouting Java router + in-house grid A*) with a strategy layer on top. It works, but it is **open-loop**: failures are recorded as booleans, not diagnosed. When routing fails on a dense board, we know *that* a net failed, not *why*, not *where*, and not *what to move\*. The verifier (`kicad-cli pcb drc`) runs post-hoc as a gate; its output never drives regeneration.

Three structural gaps block improvement:

1. **No failure signal.** `route_net` returns `None` on failure — the A\* search frontier (the true "dead end") is discarded at the `networkx.astar_path` boundary. The audit trail records `{net_name, dispatch_reason}` with no coordinates, no blocker identity, no violation type.
2. **No negotiation loop.** We have per-net rollback and retry-with-coarser-grid, but no PathFinder-style rip-up-and-reroute with escalating congestion cost. The verifier's rich DRC signal is wasted.
3. **The model is pointed at the wrong task.** `AiRoutingStrategy` asks Gemma 4 12B for per-net astar-vs-freerouting dispatch JSON — a low-value decision (a hand-coded rule makes it adequately) that the model was **never trained on** (training was maze-solving coordinate chains + spatial Q&A). The model's _actual_ trained capability — coordinate-grounded spatial reasoning, obstacle identification, "which fix is correct" counterfactuals — is exactly what placement-aware blocker diagnosis needs. It is wired to the wrong task.

**The core insight:** the model's trained capability is almost exactly what placement-aware blocker diagnosis needs. The current dispatch task is _both_ low-value _and_ out-of-distribution. The repoint is a move _toward_ the training distribution, not away from it.

---

## 2. Design Principle: Reverse-Perspective Blocker Diagnosis

The connective idea across all four phases: **when routing hits a dead end, look from the dead end's perspective. Find what blocks its path. That blocker is the thing to move.**

This is **negotiation-based rip-up-and-reroute** (foundational paper: [McMurchie & Ebeling, PathFinder 1995](https://dl.acm.org/doi/pdf/10.1145/201310.201328)), enhanced with **targeted diagnosis** (closer to [SATRoute](http://www.cse.cuhk.edu.hk/~byu/papers/J166-TCAD2026-SATRoute.pdf) and [RL-based rip-up selection](https://openreview.net/pdf?id=jjdngaZiwVb)). Plain PathFinder is blind — it globally penalizes congested nodes and hopes the router wanders elsewhere. This design is **targeted**: identify the exact blocker, classify it (trace / own-trace / movable-component / fixed-component / contested), and act on _that specific_ obstacle.

The diagnostic step is the leverage point. It powers all three downstream loops:

| Loop                    | Without diagnosis                        | With diagnosis                                                       |
| ----------------------- | ---------------------------------------- | -------------------------------------------------------------------- |
| Close orchestrator loop | "Failed net, retry coarser" (blind)      | "Failed net → diagnose blocker → rip up _that_ → reroute" (targeted) |
| DRC as reward           | Binary pass/fail (weak)                  | "Failed _because of clearance-to-net-M_ at point P" (rich, typed)    |
| Learned policy          | Learn to route from scratch (huge space) | Learn _which blocker to rip up first_ (small decision space)         |

A binary "it failed" teaches nothing. A typed "it failed because component U3's courtyard blocks the corridor at (x,y)" is a _training signal_ and a _negotiation decision_ at the same time. Build the diagnostic once, feed it to all three.

---

## 3. Evidence Base (all claims codebase-verified)

Every architecture decision below is grounded in verified facts about the current codebase. Council reviewers can verify each against the cited file:line.

### 3.1 Router frontier recovery is feasible

- `RoutingGraph.graph` is a public read-only property exposing the underlying networkx Graph (`src/volta/routing/graph.py:336-339`).
- `route_net` (`pathfinder.py:63-118`) catches `nx.NetworkXNoPath` at line 109 and returns `None`, discarding the search frontier. The `src_node`/`tgt_node` are in scope (lines 92-96) before the try block.
- `nx.single_source_dijkstra_path_length(graph.graph, src_node)` recovers the reachable component (DRC-weighted) after the failure — same complexity class as the failed A\* (`O(V+E)`), bounded by `max_nodes = 500_000` (`constraints.py:65`, raises `ValueError` if exceeded at `graph.py:171-176`).
- networkx's `astar_path` does **not** expose its closed set (verified). Post-failure reachable-component query is the cleanest recovery method.
- Scale check: at 0.25mm grid on 100×100mm board, ~160k nodes/layer. BFS over source's component is at most the cost of the failed search. **Not prohibitively slow.**

### 3.2 The legacy handler is the canonical production path

- `_handle_auto_route` (`src/volta/ops/handlers/pcb.py:513`) is reached via CLI (`cli.py:441`), MCP server (`mcp/edit_server.py:730,1248`), and handler dispatch (`ops/executor.py:49,64` → `__init__.py:9,22`).
- `RoutingOrchestrator.route_board` (`orchestrator.py:157`) is **only** called from `scripts/phase98_eval.py:112` and `tests/test_phase100_*.py`. **Zero production wiring.**
- The orchestrator's `_dispatch_astar` (`orchestrator.py:349-412`) is a **feature subset**: `obstacles=[]` (empty), no power-net filtering, 2-pin only (no multi-pin Steiner), no retry loop. The legacy handler has all of these.

**Implication:** Foundation work must target the legacy handler to have production effect. Borrow the orchestrator's audit-trail patterns.

### 3.3 DSN locked pre-routed nets are spec-supported (make-or-break resolved)

- Our `generate_dsn` (`dsn_generator.py:54-265`) emits **no** `(wiring ...)` section — pure connectivity-from-scratch.
- The [Specctra Design Language Reference](https://cdn.hackaday.io/files/1666717130852064/specctra.pdf) (Cadence v10.0, p.143) explicitly defines wire locking:
  > "A **fix** type wire cannot be altered in any way, and the router cannot route to this type."
  > "A **protect** type cannot be altered unless the user first unprotects the wire."
  > "A **normal** type wire can be deleted, ripped up, and rerouted."
- Sample (p.168): `(wire (path L1 80 ...) (net SD2) (type protect) (attr fanout))`.
- [Cadence Specctra docs](https://amroldan.granasat.space/pcb/2007/modulos/temas/CadenceSpecctraAutorouter.doc): "The protect command prevents the autorouter from ripping-up and rerouting existing wires and vias."
- Freerouting claims Specctra compatibility. The empirical unknown: does Freerouting **v2.2.4** specifically honor `(type fix)`? **This is a 30-minute hand-craft test, not a research unknown.** It is the single highest-leverage question and should be resolved before any other work.

### 3.4 Component moves are a 1-line write, fully schematic-safe

- `PcbRawWriter.modify_footprint_position(content, reference, x, y, angle)` (`ops/pcb_raw_writer.py:422`) — targeted regex sub of the footprint's first `(at X Y ROT)`. Battle-tested by the placement simulated-annealing loop at `pcb.py:1670-1678, 1729-1742`.
- Pads auto-anchor to footprint origin (`NativePad.position` is local; world coords computed at read time in `pcb_ir.py:708-709`). Moving the footprint moves all pads automatically. No dangling references.
- Exposed as the `move_footprint` op (`_schema_pcb.py:718`, handler `pcb.py:225-245`).
- **Crossfile sync never touches positions.** Sync is strictly sch→pcb (`schematic_sync.py:458`); `SafeSyncPcbFromSchematicOp.preserve_placement=True` is the contract (`_schema_crossfile.py:247`). No coordinated schematic update needed for a PCB move. The transfer contract (`transfer_contract.py:40-58`) checks footprint presence and pin-pad coverage, never coordinates.
- **A PCB component move requires ONLY the PCB file change.**

### 3.5 Fixed vs. movable components: heuristic required (parser drops the lock flag)

- `NativeFootprint` (`parser/pcb_native_types.py:116`) has **no `locked` field**. The parser (`pcb_native_parser.py:528-595`) silently skips `(locked yes)`.
- KiCad **does** write `(locked yes)` — proven in fixtures. `Arduino_Mega.kicad_pcb:202-206` shows `(locked yes)` on a PinSocket 2x18 (edge connector). 14 locked footprints in Arduino_Mega, 4 in RaspberryPi-uHAT.
- `(locked yes)` is greppable from `raw_content` via `PcbRawWriter._find_footprint_block` + token test — **no parser change required** to respect it.
- Board-edge geometry is parseable: `PcbIR.get_board_bounds()` (`pcb_ir.py:642`) reads Edge.Cuts graphics. Footprint AABB via `PcbRawWriter.extract_footprint_extent` (`pcb_raw_writer.py:1009`).
- Ref-prefix classification exists in `zone_partition.py:72-77`: `J*` → connector zone, `TP*` → power, `MH*`/`H*` → mounting holes.
- The placement engine's notion of "fixed" is caller-supplied `fixed_positions` dict (`engine.py:82`, `interactive.py:74`). No internal classification.

### 3.6 Test fixtures are sparse

- Only 4 `.kicad_pcb` fixtures: Arduino_Mega (101KB, the only real dense board), RaspberryPi-uHAT, smd_test_board (trivial), phase99_synthetic_4layer_mixedsignal (synthetic).
- x64 boards are **schematic-only** — no `.kicad_pcb` exists for `x64-smart-grid` or `x64-test`.
- The external `analog-ecosystem/hardware/backplane/` PCB (referenced in `test_net_resolve_and_wire_validation.py:297`) is **not vendored**.
- Failure-path tests exist only on toy boards: `test_route_no_path_returns_none` (`test_routing.py:264-280`) uses a 20×20mm board at 1.0mm grid (~400 nodes). No test inspects the router frontier.
- **Strategy:** vendor the backplane PCB; force failures on Arduino_Mega via `forbidden_zones`.

### 3.7 The model is unwired and mis-tasked

- `AiRoutingStrategy` is **never constructed in any production path**. Default is `DeterministicStrategy` (`orchestrator.py:120`). Config flags `strategy="auto"` (`config.py:46`) and `use_ai=True` (`config.py:49`) are dead — `use_ai` only reaches `GapFillEngine` (DRC repair), never routing strategy.
- The inference task (per-net `router_assignment` JSON) is **out-of-distribution**: the strategy prompts module's own docstring admits it (`strategy_prompts.py:5-6`: _"The adapter was trained on 6696 samples of FREE-TEXT PCB analysis (zero contained routing strategy JSON)."_).
- Training reward is synthetic: coordinate-proximity to a **precomputed** BFS path through synthetic mazes (`training/reward.py:155-192`). No router runs during training. No DRC. No real routing outcome feeds back as gradient.
- The model **is** trained on coordinate-grounded spatial reasoning: maze coordinate chains, clearance Q&A, "which fix is correct" (`generate_gap_training_data.py`, `training/chains.py`). This is the capability being wasted.
- The prompt passes only net names + pin counts — no coordinates, no placement data. `BoardState` (`strategy.py:57-71`) carries no spatial information. The orchestrator ignores `layer_hints`/`keepouts` entirely (`obstacles=[]` at `orchestrator.py:371`).

---

## 4. Architecture Decisions (all research-resolved)

| Question                 | Verdict           | Evidence                                                                                  |
| ------------------------ | ----------------- | ----------------------------------------------------------------------------------------- |
| Router frontier recovery | ✅ Feasible       | §3.1 — `graph.graph` public; Dijkstra reachable-component query bounded by `max_nodes`    |
| Canonical entrypoint     | ✅ Legacy handler | §3.2 — `_handle_auto_route` is sole production path; orchestrator is test-only subset     |
| DSN locked nets          | ✅ Spec-supported | §3.3 — Specctra defines `(type fix)`; empirical test needed for Freerouting v2.2.4        |
| Component move safety    | ✅ 1-line write   | §3.4 — `modify_footprint_position` exists, pads auto-anchor, sync never touches positions |
| Crossfile sync           | ✅ PCB-only safe  | §3.4 — sch→pcb only, `preserve_placement=True` contract                                   |
| Fixed vs movable         | ⚠️ Heuristic      | §3.5 — `(locked yes)` greppable; ref-prefix + edge-proximity heuristic                    |
| Failure test fixtures    | ⚠️ Sparse         | §3.6 — Arduino_Mega + vendored backplane; force failures via `forbidden_zones`            |
| Model role               | 🔄 Repoint        | §3.7 — retire strategy-dispatch, build diagnostician (move toward training distribution)  |

---

## 5. Phase Plan

### Phase 103 — Foundation: Signal Capture

**Goal:** Stop throwing away the dead end. Make every routing failure carry typed, located, attributable data.

**Council condition C-01 (HIGH):** The `route_net` return-type change from `None` → `RouteResult | RouteFailure` is a **cross-cutting API change across 11 call sites in 6 files**, not "~150 lines." Every call site uses the `if result is None` pattern, which breaks silently if `RouteFailure` is a truthy dataclass. This phase must include an explicit migration table (below) and a passing full test suite as its completion gate.

**C-01 Migration table (all 11 call sites):**

| #   | File:line                                                         | Current pattern     | Migration                          |
| --- | ----------------------------------------------------------------- | ------------------- | ---------------------------------- |
| 1   | `pathfinder.py:164` (`route_all_nets`)                            | `if result is None` | `isinstance(result, RouteFailure)` |
| 2   | `pathfinder.py:217` (`_route_multi_pin_net`)                      | `if result is None` | `isinstance(result, RouteFailure)` |
| 3   | `pathfinder.py:228` (`_route_multi_pin_net`)                      | `if result is None` | `isinstance(result, RouteFailure)` |
| 4   | `orchestrator.py:392` (`_dispatch_astar`)                         | `if result is None` | `isinstance(result, RouteFailure)` |
| 5   | `ops/handlers/pcb.py:806` (`_handle_auto_route` — **PRODUCTION**) | `if result is None` | `isinstance(result, RouteFailure)` |
| 6   | `multi_pass.py:145`                                               | `if result is None` | `isinstance(result, RouteFailure)` |
| 7   | `diff_pair.py:279`                                                | `if result is None` | `isinstance(result, RouteFailure)` |
| 8   | `diff_pair.py:292`                                                | `if result is None` | `isinstance(result, RouteFailure)` |
| 9   | `analysis/spatial_benchmark.py:842`                               | `if result is None` | `isinstance(result, RouteFailure)` |
| 10  | `analysis/spatial_benchmark.py:898`                               | `if result is None` | `isinstance(result, RouteFailure)` |
| 11  | `tests/test_routing.py:264` (`test_route_no_path_returns_none`)   | `result is None`    | `isinstance(result, RouteFailure)` |

**Scope:**

1. `RouteFailure` dataclass (`routing/pathfinder.py`): `route_net` returns `RouteResult | RouteFailure` instead of `None`. On `NetworkXNoPath`, recover the true reachable component via `nx.single_source_dijkstra_path_length(graph.graph, src_node)`, select nearest-reached node to target as `dead_end_point`.
   ```python
   @dataclass(frozen=True)
   class RouteFailure:
       net_name: str
       source_point: tuple[float, float]
       target_point: tuple[float, float]
       dead_end_point: tuple[float, float]      # nearest reached node to target
       reachable_count: int                      # size of source's component
       failure_type: str                         # "no_path" | "blocked_source" | "blocked_target"
   ```
2. **C-01 mitigation:** Use a shared union base with `__bool__` and `is_success` to minimize call-site churn. `RouteResult` is truthy-success; `RouteFailure` is falsy. This means existing `if result is None` becomes `if not result` (one token change per site) rather than `isinstance` checks. The migration pattern:

   ```python
   class RouteOutcome:
       """Shared base. Truthy if success, falsy if failure."""
       @property
       def is_success(self) -> bool: ...
       def __bool__(self) -> bool: return self.is_success

   @dataclass(frozen=True)
   class RouteResult(RouteOutcome):
       # ... existing fields ...
       is_success = True

   @dataclass(frozen=True)
   class RouteFailure(RouteOutcome):
       # ... failure fields ...
       is_success = False
   ```

   Call sites migrate from `if result is None` → `if not result` (failure branch) or `if result` (success branch). Test sites that assert `result is None` migrate to `assert not result` or `isinstance(result, RouteFailure)`.

3. Audit enrichment (`routing/audit.py`): extend `RoutingAuditEntry` with `dead_end_point`, `target_point`, `failure_type`. Wire into `_handle_auto_route` failure branch (`pcb.py:818-820`) and orchestrator `_dispatch_astar` (`orchestrator.py:349`).
4. DRC parsing consolidation (F-08): two parsers exist (JSON-rich `pcb_stitch.py:83`, regex-scraping `pcb_cleanup.py:148`). Consolidate on the JSON path. **F-08 acceptance test:** both parsers produce identical violation sets on a known fixture (Arduino_Mega) before the regex path is retired.
5. **F-10 side-task:** Vendor the backplane PCB (`analog-ecosystem/hardware/backplane/`) into `tests/fixtures/` as the dense-board test case. Unblocks 104+105 testing.

**Deliverable:** Every routing failure emits `{net, dead_end_point, target_point, failure_type, reachable_count}`. Data foundation for all downstream phases.

**Testing:**

- Extend `test_route_no_path_returns_none` (`test_routing.py:264`) to assert the dead-end coordinate matches the expected nearest-reached node on a 3-wall maze.
- Audit JSONL contains `dead_end_point` on failure.
- Benchmark: `single_source_dijkstra_path_length` completes in <2s on Arduino_Mega at 0.25mm grid (~160k nodes). **F-11:** also benchmark on the vendored backplane once available (could be 5-10× larger).
- **C-01 completion gate:** `pytest tests/` full suite passes (zero regressions from the return-type migration).
- **F-08 acceptance test:** both DRC parsers produce identical violation sets on Arduino_Mega.

**Risk:** Medium (upgraded from Low per C-01). The return-type migration is mechanical but cross-cutting. Mitigation: the `__bool__` pattern minimizes per-site changes to one token; full test suite is the gate.

**SLC note** (`ponytail:`): Phase 103 unblocks everything and can proceed independently. The `__bool__` pattern is the minimum-churn migration strategy — prefer it over isinstance checks at every site.

---

### Phase 104 — Diagnosis: The Reverse-Perspective Classifier

**Goal:** "Look from the dead end's perspective, find the blocker, classify it."

**Scope — `BlockerDiagnostician`** (`routing/diagnostician.py`, new):

1. **Shadow casting**: from `dead_end_point` toward `target_point`, build a corridor (width = clearance + trace_width × 2) and query `SpatialQueryEngine` (`spatial/query.py:41`, STRtree-backed) for all obstacles intersecting it.
2. **Reachability test per blocker**: for each candidate obstacle, temporarily remove from `RoutingGraph`, re-test reachability source→target. If path opens, that obstacle is _causal_ (not coincidental).
3. **Classification**:

| Class            | Detection                                            | Action signal                           |
| ---------------- | ---------------------------------------------------- | --------------------------------------- |
| `SOFT_OTHER`     | Obstacle is a track/via belonging to another net     | `rip_and_reroute` + blocker net ID      |
| `SOFT_OWN`       | Obstacle is this net's own prior trace               | `reroute_self`                          |
| `HARD_COMPONENT` | Footprint courtyard; component movable               | `nudge_component` + component ref       |
| `HARD_FIXED`     | Footprint courtyard; component locked/edge/connector | `escalate`                              |
| `CONTESTED`      | Corridor blocked in prior rounds (audit history)     | `raise_priority` + PathFinder cost bump |

4. **Component movability heuristic** (precedence order per F-07 — conflicts resolve to **most restrictive** (fixed), all against existing APIs — no parser change):
   - `(locked yes)` in footprint block → greppable via `_find_footprint_block` + token test
   - Ref prefix: `J*`, `MH*`, `H*`, `TP*` → fixed (mirrors `zone_partition.py:72`)
   - Board-edge proximity: footprint AABB within ~1mm of `ir.get_board_bounds()` → fixed
   - Everything else → movable

   **F-07 precedence:** locked > connector-prefix > edge-proximity > movable. A locked `J1` near the edge is fixed for both reasons — classification resolves to the most restrictive.

   **F-05 success gate:** reachability-per-blocker is O(blockers × BFS). **Cap at top-5 shadow obstacles** (ranked by proximity to the dead-end→target corridor). This cap is a phase-104 completion gate, not just a risk-register note.

5. **Output schema** (operational signal AND training label):

   ```python
   @dataclass(frozen=True)
   class BlockerDiagnosis:
       net_name: str
       dead_end_point: tuple[float, float]
       blockers: tuple[Blocker, ...]   # ranked by removal_benefit

   @dataclass(frozen=True)
   class Blocker:
       entity_type: str        # "track" | "via" | "footprint"
       entity_id: str          # net name or ref designator
       classification: str     # SOFT_OTHER | SOFT_OWN | HARD_COMPONENT | HARD_FIXED | CONTESTED
       blocks_path: bool       # does removing it open the route?
       recommended_action: str
       removal_benefit: float  # estimated route-open probability
   ```

**Deliverable:** A diagnostic op (`diagnose_routing_failures`) emitting a per-failed-net blocker report. Immediately useful even without the loop — tells a human _why_ routing failed. Generates the training data Phase 106 needs.

**Testing:**

- Unit: 3-wall maze → diagnosis identifies wall as `HARD_FIXED`.
- Integration: Arduino_Mega with injected keepout corridor → diagnosis returns keepout as causal blocker.
- Property: `blocks_path=True` blockers, when removed, yield a routable path (re-run A\*, assert success).

**Risk:** Medium. Reachability-per-blocker is O(blockers × graph traversal). Mitigate: limit to top-N obstacles in the shadow; cache the reachable component from Phase 103.

---

### Phase 105 — Negotiation: The Closed Loop

**Goal:** PathFinder-style rip-up-and-reroute with Freerouting as executor and escalating congestion cost for convergence.

**R-1 RESOLVED (2026-07-02):** Freerouting honors `(type fix)` and `(type protect)` — empirically verified via `tests/test_phase105_type_fix_honored.py` (4/4 pass). The negotiation loop uses efficient per-net locking. The full-re-route fallback is no longer needed.

**Council condition C-02 (MEDIUM) — FIRST TASK before the loop:** The DSN `(wiring ...)` section emission is **net-new code** (current `dsn_generator.py` emits none — verified). The KiCad-mm ↔ DSN coordinate round-trip fidelity is load-bearing: a `(type fix)` wire that round-trips with slightly wrong coordinates defeats the locking mechanism silently. Before building the loop, implement and test the round-trip contract:

1. **Segment → wire conversion.** Read `(segment ...)`/`(via ...)` from PCB via `NativeParser`, convert to DSN `(wire ...)`/`(via ...)` with correct coordinate transform, layer mapping, and via representation.
2. **Coordinate-system fidelity.** Document the KiCad mm ↔ DSN (um × 10) transform. The existing `generate_dsn` handles pin transforms; extending to routed wire paths is a separate fidelity requirement.
3. **Round-trip fidelity test (C-02 gate):** route a net, export its segment as `(type fix)`, run Freerouting, re-import via SES, assert the wire survives with <1µm coordinate error. Do this as the **first** Phase 105 task.
4. **SES import reconciliation (F-03):** `import_ses_into_pcb` must merge new Freerouting routes with preserved `(type fix)` wires without duplicating or dropping segments. Specify how the merge detects/handles overlap.

**Scope — `NegotiationLoop`** (`routing/negotiation.py`, new):

```
round 0: route all nets (Freerouting preferred, A* fallback)
         verify via DRC
         diagnose failures (Phase 104)
for round k in 1..max_rounds:
    locked_nets = successfully routed nets (emit as (type fix) in DSN)
    reroute_nets = {failed nets} ∪ {ripped-up SOFT_OTHER blockers}
    contested_corridors += {newly contested regions}  # monotonic cost
    re-export DSN with locked wiring + raised priorities for reroute_nets
    run Freerouting (or A* for the small/contested subset)
    import SES, verify DRC, diagnose failures
    if no SOFT blockers remain and only HARD left: break (escalate to placement)
    if DRC delta <= 0 for 2 consecutive rounds: break (convergence stall)
```

**DSN wiring emission** (extend `dsn_generator.py` per C-02 above): add `(wiring ...)` section emitter with `(type fix)` for locked nets. Net-new code, not "extend existing emitter."

**Congestion bookkeeping (F-06 — graph lifecycle):** The negotiation loop needs **its own mutable-weight graph instance** — it cannot piggyback on the per-call graph that `route_net` currently operates on. The legacy handler (`pcb.py:806`) calls `route_net(current_graph, ...)` per-net with progressive `mark_path_as_obstacle`; the negotiation loop must own a persistent `RoutingGraph` with `congestion_cost: dict[graph_node, float]` injected into edge weights between rounds. This is an explicit architectural requirement, not an assumption.

**Termination guarantees** (from [PathFinder, McMurchie & Ebeling 1995](https://dl.acm.org/doi/pdf/10.1145/201310.201328)):

- Historical congestion cost is monotonic (only increases) → no oscillation
- `max_rounds` cap (default 8) → bounded runtime
- Stall detection (no DRC improvement for 2 rounds) → early exit

**Freerouting-as-executor contract:** we own negotiation intelligence (cheap, inspectable, DRC-driven); Freerouting owns local maze search (world-class). Per round: locked nets preserved via `(type fix)`, only contested/failed nets re-routed.

**Deliverable:** `negotiate_route` op that closes the loop. Where real routing quality improves on dense boards.

**Testing:**

- **C-02 round-trip fidelity test** (first task): route a net, export as `(type fix)`, re-import via SES, assert wire survives with <1µm error.
- Convergence: 2 nets sharing a single corridor → both routed within 3 rounds via rip-up/reroute.
- Termination: unsatisfiable board (keepout bisects board) → terminates within `max_rounds`, escalates cleanly.
- Regression: Arduino_Mega routing completeness ≥ baseline (no degradation).
- DSN locking: `(type fix)` wires survive a Freerouting round (automate the R-1 test).

**Risk:** Medium (downgraded from Medium-high per R-1 resolution). C-02 (DSN round-trip fidelity) is the remaining risk; mitigated by making the fidelity test the first task.

---

### Phase 106 — Placement-Advisor: The Model Repoint (parallel with 105)

**Goal:** The model's trained spatial-reasoning capability, repointed from low-value strategy-dispatch to high-value blocker diagnosis + component-nudge recommendation.

**The repoint (three changes):**

1. **Retire `AiRoutingStrategy` as the inference task.** Per-net astar-vs-freerouting dispatch is low-value (`DeterministicStrategy` handles it) and out-of-distribution (model never trained on strategy JSON). Keep code for reference; stop investing.

2. **Build `BlockerDiagnosticianModel`** — consumes `(board render + dead_end_point + target_point + blocker candidates)` and emits `{blocker_id, classification, recommended_nudge}`. Matches what the model _actually trained on_: coordinate-grounded spatial reasoning, obstacle identification, "which fix is correct" (the `generate_gap_training_data.py` Q&A format).

3. **Close the training loop with real DRC reward.** Stop training on synthetic maze BFS-coordinate matching. Reward becomes: run negotiation loop, measure DRC delta after the model's recommended action. Positive delta = good, negative = bad. The audit trail (enriched in Phase 103) _is_ the dataset.
   - **SFT data**: harvest `(board, failure, diagnosis, resolution, DRC outcome)` tuples from real negotiation runs. The deterministic diagnostician (Phase 104) generates ground-truth labels for easy cases.
   - **Reward signal**: DRC violation count delta + route completion delta. Real, grounded, not synthetic.
   - **Where the model adds value over deterministic Phase 104**: the `HARD_COMPONENT` classification with nudge recommendation. The deterministic classifier identifies the blocker; only the model reasons holistically about "if I nudge U3 left 2mm, does the breakout clear _and_ not block the adjacent net?" That counterfactual spatial reasoning is hard for algorithms and exactly what the model trained for.

**Component nudge execution:**

- Use existing `modify_footprint_position` (`pcb_raw_writer.py:422`) — the 1-line write, proven safe by placement SA loop.
- Re-run routing on affected nets only (Phase 105's locked-net mechanism preserves everything else).
- Measure DRC delta. If negative, revert via audit trail's pre-nudge snapshot.

**Testing:**

- Baseline gate (from `benchmark_gemma_baseline.py`): if model <50% on blocker-classification accuracy, deterministic Phase 104 classifier used (graceful degradation, mirrors R-6 fallback in `ai_strategy.py:168`).
- Counterfactual accuracy: for `HARD_COMPONENT` nudges, DRC-delta success rate of model-recommended nudges vs random. Model must beat random.
- Regression: negotiation loop with model-advisor ≥ negotiation loop with deterministic-only advisor.

**Deliverable:** The model becomes a real participant in routing, doing the one thing it's genuinely good at (holistic spatial reasoning for placement counterfactuals) rather than the thing it was never trained for (strategy JSON dispatch).

**Risk:** Medium. Training-data distribution shift is real — but existing maze/spatial Q&A training is _closer_ to diagnosis than to strategy dispatch. The repoint moves toward the training distribution, not away.

**Checkpoint hygiene — Council condition C-03 (MEDIUM, hard gate):** the Gemma v2 adapter lives on `/Volumes/Storage` (external drive, not in repo, may be unmounted) per `phase98_eval.py:54`. **A committed, repo-tracked checkpoint path (or a documented, reproducible fetch script) must exist before Phase 106's training-infra work begins.** Training runs that depend on a drive that may be unmounted are not reproducible.

**F-09 — deprecation marking:** When retiring `AiRoutingStrategy`, add an explicit "deprecated, do not wire" comment (rather than silent retention) at `ai_strategy.py` and the dead config flags at `config.py:46,49`, to prevent a future agent from reviving the strategy-dispatch path.

**Q4 council guidance (training compute):** Fold into existing infra (`vast_train_kicad.py`). **Start with SFT on harvested diagnostic traces** (cheap, deterministic labels from Phase 104). **Defer GRPO/reward loop** until SFT baseline is measured — if the reward signal proves unstable (DRC delta is noisy), revisit. A dedicated training-run plan is premature scope; the reward loop is a modification of the existing SFT pipeline, not a new system.

**106 gating (per council):**

- Cannot begin SFT data collection until Phase 104 has a stable output schema AND ≥1 real-board diagnostic run.
- Cannot begin training infra until C-03 (checkpoint) is satisfied.

---

## 6. Dependency Graph

```
Phase 103 (Foundation)
   │  audit trail + RouteFailure
   ▼
Phase 104 (Diagnosis)
   │  BlockerDiagnostician + training data
   ├────────────────────────┐
   ▼                        ▼
Phase 105 (Negotiation)   Phase 106 (Placement-Advisor)
   closed loop               model repoint, trains on 104's output
```

- **103 → 104**: diagnosis needs `dead_end_point`.
- **104 → 105**: negotiation needs blocker classification to decide rip-up targets.
- **104 → 106**: model trains on diagnostic traces; parallel with 105.
- **105 ↔ 106**: model's nudge recommendations execute through 105's loop; 105's audit trail feeds 106's training.

---

## 7. Risk Register

| ID  | Risk                                                                  | Phase | Severity          | Mitigation                                                                                                                                                                                                                                                                |
| --- | --------------------------------------------------------------------- | ----- | ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| R-1 | ~~Freerouting ignores `(type fix)`~~ **RESOLVED 2026-07-02: HONORED** | 105   | ~~High~~ Resolved | Empirically verified via `tests/test_phase105_type_fix_honored.py`: both `(type fix)` and `(type protect)` preserve a deliberately suboptimal U-detour wire that the router would otherwise replace with a direct route. Negotiation loop uses efficient per-net locking. |
| R-2 | Reachability-per-blocker is slow on dense boards                      | 104   | Medium            | Limit to top-N shadow obstacles; cache reachable component from 103.                                                                                                                                                                                                      |
| R-3 | Negotiation loop latency (Freerouting subprocess per round)           | 105   | Medium            | Batch/offline routing is acceptable for real boards; 8-round cap.                                                                                                                                                                                                         |
| R-4 | Model nudge creates new DRC violation elsewhere                       | 106   | Medium            | Post-nudge DRC delta measurement with revert. Pre-nudge AABB check as fast-fail (not gate).                                                                                                                                                                               |
| R-5 | Training-data distribution shift on repoint                           | 106   | Medium            | Repoint moves toward training distribution (maze Q&A → diagnosis). Existing adapter is a starting point, not scratch.                                                                                                                                                     |
| R-6 | Component move parser drops `(locked yes)`                            | 104   | Low               | Greppable from `raw_content`; no parser change required.                                                                                                                                                                                                                  |
| R-7 | Negotiation loop oscillates (doesn't converge)                        | 105   | Medium            | PathFinder's monotonic historical cost guarantees termination; stall detection as backup.                                                                                                                                                                                 |
| R-8 | Orchestrator/legacy handler divergence deepens                        | all   | Low               | Note as deferred refactor; foundation work targets legacy handler (production). Orchestrator parity is separate.                                                                                                                                                          |

---

## 8. Open Questions for Council

**Q1 (highest leverage):** ~~Does Freerouting honor `(wire (type fix))`?~~ **RESOLVED 2026-07-02: YES — HONORED.** Empirically verified via `tests/test_phase105_type_fix_honored.py` (4/4 tests pass). Both `(type fix)` and `(type protect)` preserve a deliberately suboptimal pre-routed U-detour wire — the router does not rip it up or reroute it, even when its own direct route is geometrically superior. Phase 105 uses efficient per-net locking; the negotiation loop design holds.

_Test methodology:_ NET_A on `smd_test_board.dsn` connects (9250, 10000) to (49250, 10000). Pre-routed as a U-detour climbing to y=7000 (geometrically worse than the direct route). Control run (no fix wire): NET_A routes direct at y_min≈8585. Fixed run: NET_A preserves the U-detour at y_min=7000. The paths diverge by >1400µm, proving the fix directive held. Notable: this Freerouting build (post-v2.2.4, build revision 20f1a72e) honors `(type fix)` despite a documented history of ignoring other Specctra directives — SC-5 at `FreerouteBatch.java:181-206` shows `(control (snap_angle ...))` is ignored and worked around via the Java API. Wire locking works; snap-angle didn't.

**Q2:** Negotiation loop latency budget — each Freerouting round is a full subprocess (DSN export + Java + SES import). On Arduino_Mega this is seconds; on a dense backplane it could be minutes. Is an 8-round cap acceptable for batch routing? (Recommendation: yes — real boards are routed offline — but worth confirming the use case.)

**Q3:** Component-nudge validation depth — when the model recommends nudging a component, what prevents a nudge that creates a _new_ DRC violation elsewhere? Post-nudge DRC delta catches it post-hoc with revert, but should there be a pre-nudge routing-aware collision check (beyond the existing AABB overlap at `pre_analysis_pcb.py:206`)? (Recommendation: rely on post-nudge DRC delta with revert; treat pre-nudge check as fast-fail optimization, not a gate.)

**Q4:** Training compute for Phase 106 — GRPO/SFT on Gemma 4 12B is expensive. The existing `vast_train_kicad.py` (cloud GPU) is the path, but the reward-loop training (run router → measure DRC → backprop) is a different compute profile than the current maze-chain SFT. Does the council want a dedicated training-run plan, or fold it into existing infra?

**Q5:** Orchestrator convergence — Phase 103 modifies the legacy handler (production). Should the orchestrator be brought to feature-parity (obstacle extraction, power filtering, multi-pin) as part of this work, or deferred? (Recommendation: defer. The orchestrator is test-only with a primitive A\* branch; porting the legacy handler's features is a refactor, not part of this plan.)

---

## 9. Success Criteria (per phase)

| Phase | Success criterion                                                                                                                                                                                                                           |
| ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 103   | Every routing failure emits `{dead_end_point, target_point, failure_type}` in the audit trail. `single_source_dijkstra_path_length` <2s on Arduino_Mega.                                                                                    |
| 104   | `diagnose_routing_failures` op classifies blockers correctly on the 3-wall maze (HARD_FIXED) and the Arduino_Mega keepout injection (causal blocker identified). Property test: removing `blocks_path=True` blockers yields routable paths. |
| 105   | `negotiate_route` op routes a 2-net-shared-corridor board within 3 rounds. Unsatisfiable board terminates within `max_rounds` and escalates. Arduino_Mega completeness ≥ baseline.                                                          |
| 106   | Model blocker-classification accuracy ≥50% (gate) or graceful degradation to deterministic. Model-recommended nudges beat random on DRC-delta success rate. Negotiation loop with model ≥ deterministic-only.                               |

---

## 10. Out of Scope (explicitly deferred)

- **Orchestrator→legacy handler unification.** The orchestrator lacks obstacle extraction, power filtering, multi-pin routing. Porting these is a refactor, separate from this plan.
- **Full placement↔routing co-optimization.** Phase 106 handles reactive component nudges (move a blocker to unblock routing). Full proactive placement optimization (rearrange all components for routability before routing starts) is a larger problem, deferred.
- **Real-time interactive routing.** The negotiation loop is latency-bound (Freerouting subprocess per round). It targets batch/offline routing, not interactive.
- **Schematic-side bug fixes.** The 6 open P0 bugs (BUGS/README.md) are all schematic-side (annotate, place-missing-units, ERC auto-fix, dangling wires). They block ~600 ERC violations on the backplane but are out of scope for routing.
- **RL policy that replaces A\* or Freerouting broadly.** A learned per-net routing policy (DreamerV3+FR, multi-agent DQN style) is a future direction. This plan uses the model for _diagnosis + placement advice_, not as a replacement router.

---

## 11. References

**Foundational algorithms:**

- [PathFinder: Negotiation-Based, Performance-Driven Router (McMurchie & Ebeling, 1995)](https://dl.acm.org/doi/pdf/10.1145/201310.201328)
- [SATRoute: Selecting Nets to Rip Up via SAT (TCAD)](http://www.cse.cuhk.edu.hk/~byu/papers/J166-TCAD2026-SATRoute.pdf)
- [RL-based Rip-up and Reroute (OpenReview)](https://openreview.net/pdf?id=jjdngaZiwVb)

**Specctra / DSN:**

- [Specctra Design Language Reference (Cadence v10.0)](https://cdn.hackaday.io/files/1666717130852064/specctra.pdf)
- [Cadence Specctra V8.0 — protect command](https://amroldan.granasat.space/pcb/2007/modulos/temas/CadenceSpecctraAutorouter.doc)

**RL routing frontier (context for future work):**

- [DreamerV3+FR: World-Model RL for PCB Routing (Expert Systems with Applications)](https://www.sciencedirect.com/science/article/abs/pii/S0957417426003374)
- [MCTS + DRL for PCB Routing (Iowa State dissertation)](https://dr.lib.iastate.edu/server/api/core/bitstreams/baa06fe6-541d-4f4a-888d-94f3083cd518/content)
- [Dueling Double DQN Multi-Agent PCB Routing](https://www.semanticscholar.org/paper/Reinforcement-Learning-Based-PCB-Routing-Using-Deep-Xiang-Liang/df6abd08a7cfea4538d6ea965071835b82c75450)

**Classical routing (what Freerouting already is):**

- [Lee's maze routing + net ordering (ScienceDirect 1980)](https://www.sciencedirect.com/science/article/abs/pii/0010448580900275)
- [Performance Driven Multi-Layer PCB Routing — rip-up & reroute (DAC 1998)](https://www.cecs.uci.edu/~papers/compendium94-03/papers/1998/dac98/pdffiles/23_1.pdf)

**Commercial RL routers (reality check):**

- [Quilter.ai / Quarter.ai — constrained optimization in PCB design](https://www.quarter.ai/blog/constrained-optimization-pcb-design-eda-automation)
- [DeepPCB.ai — what RL learns when routing](https://deeppcb.ai/reinforcement-learning-pcb-routing-explained/)
