# Phase 100: RoutingOrchestrator and Human Approval Loop — Research

**Researched:** 2026-06-25
**Domain:** Routing orchestration, dispatch policy, human approval loop, immutability refactor
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

1. **Architectural decision (Option A):** Use Freerouting as the heavy lifter. Build a thin orchestration layer that decides which router handles which net, and provide a human approval gate over the result. Avoids reinventing push-pull routing in Python. `[VERIFIED: CONTEXT.md:11, Phase 99 CONTEXT Option A decision]`

2. **Phase 100 depends on Phase 99 (Freerouting Integration Hardening) — COMPLETE.** All three plans (99-01, 99-02, 99-03) shipped with 45 new tests and baseline metrics. `[VERIFIED: STATE.md:58-88, 99-01/02/03 SUMMARY.md]`

3. **Existing infrastructure to extend (NOT rewrite):**
   - `InteractiveRoutingSession` (485 lines) — extend to ingest Freerouting output `[VERIFIED: src/kicad_agent/routing/interactive.py]`
   - `MultiPassRouter` (274 lines) — extend, don't rewrite `[VERIFIED: src/kicad_agent/routing/multi_pass.py]`
   - `PersistentUndoStack` — for rollback (R-4) `[VERIFIED: src/kicad_agent/ops/persistent_undo.py]`

4. **CR-01 deferral (MUST incorporate):** Convert 14 NativeBoard dataclasses in `src/kicad_agent/parser/pcb_native_types.py` to `@dataclass(frozen=True)` and migrate 8 mutation sites to `dataclasses.replace()`. `[VERIFIED: STATE.md:532-534, pcb_native_types.py:10-14 TODO comment]`

5. **RoutingStrategy interface is the Phase 98 integration point.** Must be: pure (no side effects), serializable, validatable. `[VERIFIED: CONTEXT.md:54-77]`

### Claude's Discretion

1. **Exact dispatch heuristics** (net class → router mapping thresholds) — research recommends values based on Phase 99 baseline data, but planner can adjust.
2. **Audit trail storage format** (JSONL vs SQLite vs in-memory) — research recommends JSONL for simplicity and streaming, but SQLite is viable if query patterns demand it.
3. **Internal class structure of RoutingOrchestrator** — how many helper classes, where to put dispatch logic.
4. **Test fixture selection** for rollback validation — which board(s) to use for the 10-cycle approve/reject test.

### Deferred Ideas (OUT OF SCOPE)

- **AI strategy** — Phase 98 (AI Routing Strategy Advisor). Phase 100 defines the interface; Phase 98 plugs in. `[VERIFIED: CONTEXT.md:46]`
- **New routing algorithms** — no new A* variants or push-pull implementations. `[VERIFIED: CONTEXT.md:47]`
- **Real-time shove** — not pursuing (Option A decision from Phase 99). `[VERIFIED: CONTEXT.md:48]`
- **Microvia padstack emission** (H-1 from Phase 99) — rare in hobby boards, Freerouting support unverified. `[VERIFIED: 99-02 SUMMARY.md:156-167]`
- **M-3 board outline NativeBoard migration** — deferred Bead from Phase 99-01, `_extract_board_outline` still uses regex. Not blocking Phase 100. `[VERIFIED: 99-01 SUMMARY.md:103-114]`
- **Inter-class clearance** (RESEARCH.md Open Question 2 from Phase 99) — deferred, requires DSN `(clearance_class ...)` extension. `[VERIFIED: 99-03 SUMMARY.md:177-179]`
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| R-1 | `RoutingOrchestrator` class with `RoutingStrategy` interface | §Technical Approach R-1; §Integration Points (Phase 98 contract) |
| R-2 | Per-net dispatch logic: net class, pin count, density, diff-pair flag → router selection | §Technical Approach R-2; §Dispatch Policy (from Phase 99 baseline) |
| R-3 | `InteractiveRoutingSession` extended to ingest Freerouting output | §Technical Approach R-3; §Existing Infrastructure Audit |
| R-4 | Rollback mechanism via existing PersistentUndoStack | §Technical Approach R-4; §Existing Infrastructure Audit |
| R-5 | Audit trail: every routing decision logged | §Technical Approach R-5; §Architecture Patterns |
| R-6 | Deterministic fallback policy when AI unavailable | §Technical Approach R-6; §Dispatch Policy |
| R-7 | Batch orchestration API: route entire board, get per-net results + audit | §Technical Approach R-7; §Architecture Patterns |
| CR-01 | NativeBoard immutability refactor (14 dataclasses → frozen, 8 mutation sites → replace) | §Technical Approach CR-01; §Runtime State Inventory |
</phase_requirements>

---

## Executive Summary

Phase 100 builds the intelligent dispatch layer that sits between the user/LLM and the two routing backends (in-house A* and Freerouting). The infrastructure to extend is substantial and well-tested: `InteractiveRoutingSession` (485 lines, handles approve/reject/reroute cycles for A* results), `MultiPassRouter` (274 lines, 3-pass A* strategy), `PersistentUndoStack` (file-based undo with atomic writes), and the Phase 99 Freerouting pipeline (DSN export → route → SES import, fully working with baseline metrics on 3 fixtures).

The core new work is: (1) a `RoutingStrategy` Protocol that Phase 98's AI advisor will later implement, (2) a `DeterministicStrategy` that encodes the dispatch policy derived from Phase 99 baseline data, (3) extending `InteractiveRoutingSession` to accept Freerouting SES results as suggestions (currently only consumes A* `RouteResult`), (4) wiring rollback through `PersistentUndoStack` so rejected routes revert the board file, (5) a JSONL audit trail capturing every dispatch decision, and (6) the CR-01 immutability refactor of 14 `NativeBoard` dataclasses.

**Primary recommendation:** Implement in 2 plans as CONTEXT.md estimates. Plan 1: CR-01 immutability refactor first (it's a prerequisite — the orchestrator must not mutate board state in place). Plan 2: RoutingOrchestrator + dispatch + InteractiveRoutingSession extension + audit trail + batch API. This ordering avoids rework: the orchestrator's rollback mechanism depends on immutable board snapshots.

**Key risk:** The `NativeFootprint.properties: dict[str, str]` field is the hardest immutability migration — kiutils consumers and `maze_generator.py` mutate it directly. The 5-step resolution plan in STATE.md is sound; `dataclasses.replace()` at every append site is the correct pattern. `[CITED: STATE.md:532]`

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Dispatch policy (which router per net) | Orchestration layer | — | Pure function of board state + net metadata; no I/O. Must be deterministic and testable. |
| A* routing execution | Routing engine (pathfinder.py) | — | Already exists, immutable `RouteResult`. No change needed. |
| Freerouting execution | External process (Java) | Routing bridge (freerouting.py) | Subprocess call; DSN out, SES in. Phase 99 hardened this. |
| SES → suggestion conversion | InteractiveRoutingSession extension | — | New method to bridge Freerouting SES output into the existing approve/reject lifecycle. |
| Board state rollback | PersistentUndoStack (file-based) | — | File content snapshots, atomic writes. Already tested (15 tests in Phase 70). |
| Audit trail persistence | JSONL log file | — | Append-only, one line per dispatch decision. Streaming-friendly, grep-friendly. |
| RoutingStrategy interface | Protocol definition | — | Pure contract. Phase 98 implements; Phase 100 defines + provides DeterministicStrategy. |
| Batch orchestration | RoutingOrchestrator | — | Coordinates per-net dispatch, collects results, writes audit. Single entry point for R-7. |

---

## Existing Infrastructure Audit

### What to EXTEND (not rewrite)

| Component | Location | Lines | Current State | Phase 100 Change |
|-----------|----------|-------|---------------|------------------|
| `InteractiveRoutingSession` | `routing/interactive.py` | 485 | Consumes A* `RouteResult` only; approve/reject/reroute with locked-route obstacles | **Add `ingest_freerouting_result()` method** that converts `SesParseResult` → `RoutingSuggestion` objects. Reuse existing `approve()`/`reject()`/`reroute_rejected()` unchanged. |
| `MultiPassRouter` | `routing/multi_pass.py` | 274 | 3-pass A* strategy with fallback | **No change needed** — orchestrator calls it for A*-dispatched nets. Already returns `dict[str, RouteResult]`. |
| `PersistentUndoStack` | `ops/persistent_undo.py` | ~300 | File-based undo with atomic writes, thread-safe, gitignore auto-add | **No change needed** — orchestrator calls `push(file, pre_content, post_content, "route")` before routing and `pop_undo(file)` on reject. |
| `route_with_freerouting()` | `routing/freerouting.py` | 955 | DSN export → Java subprocess → SES parse. Returns `FreeroutingResult`. | **No change needed** — orchestrator calls it for Freerouting-dispatched nets. |
| `import_ses_into_pcb()` | `routing/freerouting.py` | — | Merges SES wires/vias into PCB raw content | **No change needed** — orchestrator uses it to apply Freerouting results to board. |
| `RoutingConstraints` | `routing/constraints.py` | — | Frozen dataclass (clearance, grid, trace width, via params) | **No change needed** — passed to A* graph builder. |
| `RoutingGraph` | `routing/graph.py` | — | Multi-layer graph with via edges (Phase 99 Gap 2) | **No change needed** — already supports 3D nodes `(x, y, layer)` and via edges between adjacent layers. |
| `TrackSegment` / `ViaSegment` | `routing/bridge.py` | — | Frozen dataclasses with `.to_sexpr()` | **No change needed** — used by SES import and A* result emission. |
| `RouteQualityMetrics` | `validation/gates/route_quality.py` | — | Post-route quality computation | **No change needed** — orchestrator can call `compute_route_quality()` for validation. |

### What to BUILD NEW

| Component | Location (proposed) | Purpose |
|-----------|---------------------|---------|
| `RoutingStrategy` Protocol | `routing/strategy.py` (new) | Phase 98 integration contract. Pure function: `(BoardState, netlist) → RoutingStrategyResult`. |
| `DeterministicStrategy` | `routing/strategy.py` (new) | Default strategy implementing the dispatch policy from Phase 99 baseline. No AI. |
| `RoutingOrchestrator` | `routing/orchestrator.py` (new) | Main entry point. Dispatches per-net, collects results, manages audit trail. |
| `RoutingAuditEntry` / `RoutingAuditLog` | `routing/audit.py` (new) | JSONL audit trail. Frozen dataclass per entry, append-only log writer. |
| `ingest_freerouting_result()` | added to `routing/interactive.py` | Converts `SesParseResult` wires into `RoutingSuggestion` objects for the existing session lifecycle. |
| Immutability refactor | `parser/pcb_native_types.py` + `ir/pcb_ir.py` + `parser/pcb_native_parser.py` | CR-01: 14 dataclasses → `frozen=True`, 8 mutation sites → `dataclasses.replace()`. |

### Dispatch Policy (from Phase 99 Baseline Data)

Phase 99-03 produced concrete baseline metrics that inform the deterministic dispatch policy `[VERIFIED: 99-03 SUMMARY.md:64-73]`:

| Fixture | Total Nets | Routed (FR) | Completion | DRC | Dispatch Recommendation |
|---------|-----------|-------------|------------|-----|-------------------------|
| smd_test_board | 8 | 4 | 50% | PASS | **Freerouting** (simple, ≤20 nets, 2-layer) |
| RaspberryPi-uHAT | 31 | 1 | 3.2% | FAIL | **A*** (dense SMD, FR struggles) |
| synthetic 4-layer | 8 | — | — | ERROR | **A*** for simple nets, **Freerouting** for power (zones crash FR) |

**Proposed deterministic dispatch heuristics** (R-2, R-6) `[ASSUMED — based on Phase 99 data, planner can adjust]`:

```python
def dispatch(net_name, net_metadata, board_metadata) -> RouterBackend:
    # Diff pairs → always A* (length matching is in-house)
    if net_metadata.is_diff_pair:
        return RouterBackend.ASTAR

    # Power nets on boards with zones → A* (Freerouting crashes on zone polygons)
    if net_metadata.net_class == "Power" and board_metadata.has_zones:
        return RouterBackend.ASTAR

    # High pin count (>10) → Freerouting (better at dense connectivity)
    if net_metadata.pin_count > 10:
        return RouterBackend.FREEROUTING

    # Simple 2-pin signal nets on boards ≤20 nets → Freerouting (proven)
    if net_metadata.pin_count <= 2 and board_metadata.total_nets <= 20:
        return RouterBackend.FREEROUTING

    # Default: A* (safe, in-house, no external dependency)
    return RouterBackend.ASTAR
```

---

## Technical Approach

### R-1: RoutingOrchestrator + RoutingStrategy Interface

**What:** Define `RoutingStrategy` as a `typing.Protocol` with a single `strategize()` method. Define `RoutingOrchestrator` as the class that accepts a strategy (default: `DeterministicStrategy`) and executes it per-net.

**Interface contract (Phase 98 integration point):**

```python
# Source: CONTEXT.md:62-77 (locked schema sketch)
from typing import Protocol
from dataclasses import dataclass
from enum import Enum

class RouterBackend(str, Enum):
    ASTAR = "astar"
    FREEROUTING = "freerouting"
    MULTI_PASS = "multi_pass"

@dataclass(frozen=True)
class RoutingStrategyResult:
    net_priorities: tuple[str, ...]  # net names in routing order
    layer_hints: dict[str, str]      # net_name -> copper layer (frozen dict or plain)
    keepouts: tuple[Keepout, ...]    # additional keepouts
    router_assignment: dict[str, RouterBackend]  # net -> backend
    routing_notes: str               # free-text rationale

class RoutingStrategy(Protocol):
    def strategize(
        self,
        board_state: BoardState,
        netlist: dict[str, list[Pin]],
    ) -> RoutingStrategyResult: ...
```

**Why Protocol not ABC:** Phase 98's AI advisor should be able to implement the strategy without inheriting from a base class. Protocol enables structural subtyping (duck typing with type checker support). `[CITED: typing.Protocol docs, Python 3.8+]`

**Purity requirement:** `strategize()` must be side-effect-free. It takes board state and returns a plan. The orchestrator executes the plan. This separation is critical for Phase 98's validation gate (R-4 in Phase 98 will validate AI output before execution). `[VERIFIED: CONTEXT.md:57]`

### R-2: Per-Net Dispatch Logic

**What:** The dispatch logic lives in `DeterministicStrategy.strategize()`. It examines each net's metadata (class, pin count, density, diff-pair flag) and the board's metadata (total nets, layer count, zone presence) to produce a `router_assignment` dict.

**Inputs available (all from existing PcbIR/NativeBoard):**
- Net class: `NativeNetClass.name` (e.g., "Power", "Signal", "Default") `[VERIFIED: pcb_native_types.py:81]`
- Pin count per net: derivable from `PcbIR.get_net_pads(net_name)` `[VERIFIED: pcb_ir.py:280-297]`
- Diff-pair flag: from `RoutingConstraints` or schematic-level annotation
- Board density: `total_nets / board_area` (board bounds from `PcbIR.get_board_bounds()`)
- Zone presence: `len(NativeBoard.zones) > 0` `[VERIFIED: pcb_native_types.py:312]`

**Output:** `router_assignment: dict[str, RouterBackend]` consumed by the orchestrator.

### R-3: Extend InteractiveRoutingSession for Freerouting Output

**What:** Currently `InteractiveRoutingSession._generate_suggestions()` only calls `route_all_nets()` (A*). Add a new method `ingest_freerouting_result(ses_result: SesParseResult, net_filter: set[str] | None = None)` that converts SES wires into `RoutingSuggestion` objects and merges them into `self._suggestions`.

**Conversion logic:**
```python
def ingest_freerouting_result(self, ses_result, net_filter=None):
    for wire in ses_result.wires:
        if net_filter and wire.net not in net_filter:
            continue
        if wire.net not in self._netlist:
            continue
        suggestion = RoutingSuggestion(
            net_name=wire.net,
            path=list(wire.points),      # SES polyline points → path waypoints
            length_mm=_compute_wire_length(wire.points),
            is_differential_pair=wire.net in self._diff_pair_map,
            diff_pair_complement=self._diff_pair_map.get(wire.net, ""),
        )
        self._suggestions[wire.net] = suggestion
```

**Why extend not subclass:** The existing approve/reject/reroute lifecycle works unchanged. Freerouting suggestions enter the same pipeline as A* suggestions. The user cannot tell (nor care) which backend produced a suggestion — they just approve or reject. `[VERIFIED: interactive.py:195-250 — approve/reject are backend-agnostic]`

**Reroute behavior:** When a Freerouting-routed net is rejected, `reroute_rejected()` currently re-runs A*. This is acceptable — the reroute uses a different backend than the original route, which is fine (the user rejected the FR route, so trying A* is a valid fallback). Document this as intentional cross-backend rerouting.

### R-4: Rollback via PersistentUndoStack

**What:** Before routing begins, the orchestrator snapshots the board file content via `PersistentUndoStack.push()`. If a route is rejected (either auto-DRC-fail or user-reject), the orchestrator calls `PersistentUndoStack.pop_undo()` to revert.

**Integration pattern:**
```python
class RoutingOrchestrator:
    def route_board(self, pcb_path: Path, ...) -> RoutingOrchestrationResult:
        undo_stack = PersistentUndoStack(project_dir=pcb_path.parent)
        pre_content = pcb_path.read_text()

        # Snapshot before routing
        undo_stack.push(pcb_path, pre_content, pre_content, "pre_route_snapshot")

        try:
            # ... dispatch + route ...
            pcb_path.write_text(routed_content)
            undo_stack.push(pcb_path, pre_content, routed_content, "post_route")

            # Human approval loop
            for net in awaiting_approval:
                if user_rejects(net):
                    self.rollback_route(pcb_path, undo_stack)
        except RoutingFailure:
            self.full_rollback(pcb_path, undo_stack, pre_content)
```

**Why PersistentUndoStack over in-memory:** File-based snapshots survive process crashes. Phase 70 tested 15 scenarios including atomic writes, manifest corruption, concurrent access, and multi-file isolation. `[VERIFIED: STATE.md:146-151, ops/persistent_undo.py]`

**Critical:** The orchestrator must push BEFORE routing and push AGAIN after routing. The two-push pattern means:
- `pop_undo()` after a reject → reverts to post-route (removes just the rejected net's segments)
- `pop_undo()` again → reverts to pre-route (full rollback)

For per-net rollback (reject one net without reverting all), the orchestrator must surgically remove only that net's segments from the PCB content. This is achievable because `import_ses_into_pcb` tags segments by net name — we can filter them out. `[VERIFIED: freerouting.py:822-845 — segments include (net "name")]`

### R-5: Audit Trail

**What:** Every routing decision logged as a JSONL entry. One file per orchestration run: `<project>/.kicad-agent/audit/routing_<timestamp>.jsonl`.

**Schema:**
```python
@dataclass(frozen=True)
class RoutingAuditEntry:
    timestamp: str          # ISO 8601
    net_name: str
    router_used: RouterBackend  # astar | freerouting | multi_pass
    strategy: str           # "deterministic" | "ai_advisor_v1" (Phase 98)
    dispatch_reason: str    # human-readable why this router was chosen
    result: str             # "success" | "failed" | "rejected" | "approved"
    route_length_mm: float
    via_count: int
    drc_clean: bool
    notes: str              # free-text (e.g., "user rejected: too close to GND")
```

**Why JSONL:** Append-only (no read-modify-write), streaming-friendly (can tail -f), grep-friendly (`grep '"net_name":"VCC"' audit.jsonl`), survives partial writes (one corrupt line doesn't poison the rest). SQLite is overkill for the write-once query-rarely pattern. `[ASSUMED — based on standard observability practices, no external source]`

### R-6: Deterministic Fallback Policy

**What:** `DeterministicStrategy` is the default when no AI strategy is provided. It encodes the dispatch heuristics from Phase 99 baseline (see §Dispatch Policy above). The orchestrator accepts an optional `strategy: RoutingStrategy | None = None` parameter — when `None`, uses `DeterministicStrategy()`.

**Success criterion 5 (CONTEXT.md:42):** "Deterministic mode completes a full board route within Freerouting's baseline ±5% on completion rate." The smd_test_board baseline (50% completion, DRC PASS) is the target. `[VERIFIED: CONTEXT.md:42, 99-03 SUMMARY.md:67]`

### R-7: Batch Orchestration API

**What:** Single method `RoutingOrchestrator.route_board(pcb_path, strategy=None, ...) -> RoutingOrchestrationResult` that:
1. Parses the PCB
2. Extracts netlist + metadata
3. Calls `strategy.strategize()` to get assignments
4. Dispatches each net to its assigned backend
5. Collects results into a unified `RoutingOrchestrationResult`
6. Writes the audit trail
7. Returns per-net results + summary

**Result type:**
```python
@dataclass(frozen=True)
class RoutingOrchestrationResult:
    per_net: dict[str, NetRouteResult]  # net -> result
    audit_path: Path
    total_routed: int
    total_failed: int
    total_rejected: int
    strategy_used: str
    elapsed_seconds: float
```

### CR-01: NativeBoard Immutability Refactor

**What:** Convert 14 dataclasses in `pcb_native_types.py` to `@dataclass(frozen=True)` and migrate 8 mutation sites to `dataclasses.replace()`.

**The 14 dataclasses** `[VERIFIED: pcb_native_types.py:64-319]`:
1. `NativeNet`
2. `NativeNetClass`
3. `NativePad`
4. `NativeFootprint`
5. `NativeSegment`
6. `NativeVia`
7. `NativeZone`
8. `NativeGraphicItem`
9. `NativeBoardOutline`
10. `NativeGeneral`
11. `NativeStackupLayer`
12. `NativeStackup`
13. `NativeSetup`
14. `NativeBoard`

**The 8 mutation sites** `[VERIFIED: STATE.md:532, pcb_ir.py + pcb_native_parser.py grep]`:
1. `PcbIR.add_net` (pcb_ir.py:193) — `self.board.nets.append(net)`
2. `PcbIR.remove_net` (pcb_ir.py:214-227) — mutates `pad.net_name`, `pad.net_number` in place + rebuilds `board.nets` list
3. `PcbIR.rename_net` (pcb_ir.py:243-254) — mutates `n.name`, `pad.net_name` in place
4. `NativeParser._build_board` (pcb_native_parser.py:351-371) — constructs board via field assignment
5. `NativeParser._extract_footprints` (pcb_native_parser.py:538, 606, 614, 623) — `fp.graphic_items.append(gi)`, `pad.net_name = item[1]`
6. `maze_generator.py:231-237, 321-334, 352-354` — `board.nets.append()`, `fp.properties["Reference"] =`, `fp.pads.append()`, `board.footprints.append()`
7. `NativeParser._extract_zones` (pcb_native_parser.py:838) — `zone.polygon_points.append((x, y))`
8. `NativeParser._extract_setup` stackup layer building (pcb_native_parser.py:1084)

**Resolution approach (5-step plan from STATE.md):**

1. **Convert all 14 dataclasses to `frozen=True`.**
   - `list` fields must become `tuple` OR use `dataclasses.replace()` at every append site.
   - `dict` fields (`NativeFootprint.properties`) must become `MappingProxyType` or frozen dict.
   - `[VERIFIED: STATE.md:532 resolution plan step 1]`

2. **Migrate the 8 mutation sites to `dataclasses.replace()`.**
   - Pattern for list appends: `board = replace(board, nets=(*board.nets, new_net))`
   - Pattern for field updates: `pad = replace(pad, net_name="", net_number=0)`
   - Pattern for nested updates (pad within footprint within board): rebuild the chain via replace.
   - `[VERIFIED: STATE.md:532 resolution plan step 2]`

3. **Update downstream consumers that mutate in place.**
   - `maze_generator.py` (6 mutation sites) — this is the biggest consumer. It builds synthetic boards for training data. Must convert to replace-chain pattern.
   - `board_outline.py`, `pcb_ops.py` — audit for mutation patterns (grep showed reads, not mutations).
   - `[VERIFIED: STATE.md:532 resolution plan step 3]`

4. **Run full native parser + IR + routing test suite (321 tests per 99-01 SUMMARY) to catch breakage.**
   - `[VERIFIED: STATE.md:532 resolution plan step 4, 99-01 SUMMARY.md:137]`

5. **The `properties: dict[str, str]` field on `NativeFootprint` is the hardest.**
   - kiutils consumers mutate it directly (e.g., `fp.properties["Reference"] = ...`).
   - Options: (a) `MappingProxyType` (read-only view, raises on mutation), (b) `types.MappingProxyType`, (c) accept a plain dict but document it as "do not mutate" (weakest).
   - Recommendation: use `tuple[tuple[str, str], ...]` internally with a `@property` that returns a dict view. This is frozen-safe.
   - `[VERIFIED: STATE.md:532 resolution plan step 5]`

---

## Runtime State Inventory

> Phase 100 involves a refactor (CR-01 immutability) and new orchestration code. The refactor touches runtime state.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `.kicad-agent/undo/` — PersistentUndoStack JSON entries (pre-existing from Phase 70) | None — undo format unchanged. New entries will coexist. |
| Live service config | None — kicad-agent is a CLI/library, no running services | None |
| OS-registered state | None | None |
| Secrets/env vars | `FREEROUTING_JAR` env var (optional, for Freerouting JAR path) | None — env var consumed by existing `_find_freerouting()`, unchanged. |
| Build artifacts | `src/kicad_agent/routing/__pycache__/*.pyc` — stale after refactor | Auto-regenerated on next run. No action. |

**Nothing found that requires data migration.** The immutability refactor changes in-memory representation only. The on-disk PCB file format is unchanged (raw_content is still a string). PersistentUndoStack stores file content snapshots (strings), not Python objects — so frozen dataclasses don't affect it.

---

## Integration Points (Phase 98 Plug-in Interface Contract)

The `RoutingStrategy` Protocol is the contract Phase 98 must implement. This section defines it precisely so Phase 98 planning can proceed independently.

### Protocol Definition

```python
# src/kicad_agent/routing/strategy.py

from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol
from enum import Enum


class RouterBackend(str, Enum):
    """Available routing backends."""
    ASTAR = "astar"
    FREEROUTING = "freerouting"
    MULTI_PASS = "multi_pass"


@dataclass(frozen=True)
class Keepout:
    """Additional routing keepout beyond board rules."""
    x1: float
    y1: float
    x2: float
    y2: float
    layer: str
    reason: str


@dataclass(frozen=True)
class BoardState:
    """Immutable snapshot of board state for strategy evaluation.

    Phase 98 consumes this — must be pure data, no I/O.
    """
    total_nets: int
    layer_count: int
    has_zones: bool
    board_bounds: tuple[float, float, float, float]
    net_classes: tuple[str, ...]


@dataclass(frozen=True)
class Pin:
    """Pin reference for netlist."""
    footprint_ref: str
    pad_number: str
    x: float
    y: float


@dataclass(frozen=True)
class RoutingStrategyResult:
    """Output of RoutingStrategy.strategize().

    Phase 98 R-4 validation gate will validate this structure before
    the orchestrator executes it.
    """
    net_priorities: tuple[str, ...]
    layer_hints: dict[str, str]
    keepouts: tuple[Keepout, ...]
    router_assignment: dict[str, RouterBackend]
    routing_notes: str


class RoutingStrategy(Protocol):
    """Strategy for deciding how to route each net.

    Phase 98 (AI Routing Strategy Advisor) will implement this with an
    LLM-backed advisor. Phase 100 provides DeterministicStrategy as the
    default/fallback.

    Contract:
    - MUST be pure (no side effects, no I/O)
    - MUST be serializable (result must be JSON-dumpable for audit trail)
    - MUST be validatable (Phase 98 R-4 gate validates before execution)
    """

    def strategize(
        self,
        board_state: BoardState,
        netlist: dict[str, list[Pin]],
    ) -> RoutingStrategyResult:
        """Return a routing plan for the orchestrator to execute."""
        ...
```

### Validation Contract (for Phase 98)

Phase 98's R-4 validation gate will sit at the boundary between `strategize()` output and orchestrator execution. It must verify:

1. Every net in `router_assignment` exists in the netlist
2. Every `RouterBackend` value is a valid enum member
3. `layer_hints` reference valid copper layers for the board
4. `keepouts` have valid coordinates within board bounds
5. `net_priorities` is a permutation of netlist keys (no orphans, no phantoms)

Phase 100 does NOT implement this validation gate — that's Phase 98's job. Phase 100's `DeterministicStrategy` is trusted (deterministic code), but the orchestrator should still validate the result defensively (belt-and-suspenders). `[CITED: CONTEXT.md:59]`

---

## Risk Assessment

### Risk 1: NativeFootprint.properties Immutability (HIGH)

**Risk:** The `properties: dict[str, str]` field is mutated by `maze_generator.py:321-322` and potentially by kiutils-fallback consumers. Converting to frozen breaks these.

**Mitigation:** Use `tuple[tuple[str, str], ...]` internally with a `@property properties` that returns a `dict` view (constructed on access). Consumers that read (`fp.properties.get("Reference")`) work unchanged. Consumers that write (`fp.properties["Reference"] = ...`) break loudly — migrate them to `replace(fp, properties={**fp.properties_dict, "Reference": ...})`.

**Contingency:** If the tuple-of-tuples approach proves too invasive, accept `dict` but wrap accesses in a `@property` setter that raises `AttributeError`. This is weaker (runtime error, not type error) but unblocks the refactor.

### Risk 2: InteractiveRoutingSession Freerouting Integration (MEDIUM)

**Risk:** Freerouting SES output contains wires (polylines) and vias. The existing `RoutingSuggestion` only models paths (waypoints). Viass need separate handling.

**Mitigation:** Add `vias: list[SesVia]` field to `RoutingSuggestion` (default empty). The `approve()` method must lock both the path AND the vias. The `reroute_rejected()` method must add via locations as obstacles too.

**Contingency:** If via handling proves complex, split Freerouting suggestions into two entries (wire + via) and approve/reject them as a unit via a composite key.

### Risk 3: Per-Net Rollback Complexity (MEDIUM)

**Risk:** The user wants to reject one net's route without reverting the entire board. This requires surgically removing only that net's segments from the PCB content — but segments are identified by net name, and multiple nets may share layers.

**Mitigation:** Use the `(net "name")` tag in segment S-expressions to filter. `import_ses_into_pcb` already tags every segment with its net name `[VERIFIED: freerouting.py:843]`. Rollback = remove all `(segment ... (net "REJECTED_NET") ...)` and `(via ... (net "REJECTED_NET") ...)` lines from the PCB content via regex.

**Contingency:** If regex-based removal is fragile, snapshot the full board before each net's route and revert to that snapshot on reject (coarser but simpler — rejects the current net AND any nets routed after it).

### Risk 4: Freerouting Availability in CI (LOW)

**Risk:** Freerouting requires Java + JAR. CI environments may not have it.

**Mitigation:** All Freerouting-dependent tests are already gated behind `is_freerouting_available()` (Phase 99 pattern). `[VERIFIED: freerouting.py:948-954, phase99_baseline.py:269-275]` Tests skip gracefully when Freerouting is absent.

### Risk 5: Audit Trail File Growth (LOW)

**Risk:** JSONL audit files grow unboundedly across runs.

**Mitigation:** One file per run (timestamped). Old files are user-managed (gitignored via `.kicad-agent/`). No auto-rotation needed for v1 — document a manual cleanup command if requested later.

---

## Validation Architecture

> Required by Nyquist dimension 8. `workflow.nyquist_validation: true` in `.planning/config.json`. `[VERIFIED: .planning/config.json:12]`

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (via `.venv/bin/python -m pytest`) |
| Config file | `pytest.ini` (project root) + `conftest.py` files |
| Quick run command | `.venv/bin/python -m pytest tests/test_phase100_*.py -x -q` |
| Full suite command | `.venv/bin/python -m pytest tests/ -x -q` |
| Total existing tests | 6026 (5 collection errors in unrelated playground module — pre-existing) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| R-1 | RoutingStrategy Protocol + DeterministicStrategy | unit | `.venv/bin/python -m pytest tests/test_phase100_strategy.py -x` | Wave 0 |
| R-1 | RoutingOrchestrator construction with default strategy | unit | `.venv/bin/python -m pytest tests/test_phase100_orchestrator.py::test_construct -x` | Wave 0 |
| R-2 | Dispatch: diff pair → A* | unit | `.venv/bin/python -m pytest tests/test_phase100_dispatch.py::test_diff_pair_astar -x` | Wave 0 |
| R-2 | Dispatch: power+zones → A* | unit | `.venv/bin/python -m pytest tests/test_phase100_dispatch.py::test_power_zones_astar -x` | Wave 0 |
| R-2 | Dispatch: simple 2-pin ≤20 nets → Freerouting | unit | `.venv/bin/python -m pytest tests/test_phase100_dispatch.py::test_simple_freerouting -x` | Wave 0 |
| R-2 | Dispatch: high pin count → Freerouting | unit | `.venv/bin/python -m pytest tests/test_phase100_dispatch.py::test_high_pincout_freerouting -x` | Wave 0 |
| R-3 | InteractiveRoutingSession.ingest_freerouting_result | unit | `.venv/bin/python -m pytest tests/test_phase100_session_freerouting.py -x` | Wave 0 |
| R-3 | Approve/reject Freerouting suggestion | unit | `.venv/bin/python -m pytest tests/test_phase100_session_freerouting.py::test_approve_reject -x` | Wave 0 |
| R-4 | Rollback single rejected net | integration | `.venv/bin/python -m pytest tests/test_phase100_rollback.py::test_reject_reverts_net -x` | Wave 0 |
| R-4 | 10-cycle approve/reject no corruption | integration | `.venv/bin/python -m pytest tests/test_phase100_rollback.py::test_10_cycles -x` | Wave 0 |
| R-5 | Audit trail captures all decisions | unit | `.venv/bin/python -m pytest tests/test_phase100_audit.py -x` | Wave 0 |
| R-5 | Audit queryable by net name | unit | `.venv/bin/python -m pytest tests/test_phase100_audit.py::test_query_by_net -x` | Wave 0 |
| R-6 | Deterministic mode matches baseline ±5% | integration (slow) | `.venv/bin/python -m pytest tests/test_phase100_deterministic_baseline.py -x` | Wave 0 |
| R-7 | Batch API routes full board | integration | `.venv/bin/python -m pytest tests/test_phase100_batch.py -x` | Wave 0 |
| CR-01 | 14 dataclasses are frozen | unit | `.venv/bin/python -m pytest tests/test_phase100_cr01_immutability.py::test_all_frozen -x` | Wave 0 |
| CR-01 | PcbIR.add_net uses replace | unit | `.venv/bin/python -m pytest tests/test_phase100_cr01_immutability.py::test_add_net_replace -x` | Wave 0 |
| CR-01 | PcbIR.remove_net uses replace | unit | `.venv/bin/python -m pytest tests/test_phase100_cr01_immutability.py::test_remove_net_replace -x` | Wave 0 |
| CR-01 | PcbIR.rename_net uses replace | unit | `.venv/bin/python -m pytest tests/test_phase100_cr01_immutability.py::test_rename_net_replace -x` | Wave 0 |
| CR-01 | NativeParser._build_board constructs immutably | unit | `.venv/bin/python -m pytest tests/test_phase100_cr01_immutability.py::test_build_board_immutable -x` | Wave 0 |
| CR-01 | maze_generator builds immutably | unit | `.venv/bin/python -m pytest tests/test_phase100_cr01_immutability.py::test_maze_generator_immutable -x` | Wave 0 |
| CR-01 | Regression: 321 native parser/IR/routing tests pass | regression | `.venv/bin/python -m pytest tests/test_phase76_*.py tests/test_native_parser*.py tests/test_routing*.py -x` | Existing |

### Sampling Rate

- **Per task commit:** `.venv/bin/python -m pytest tests/test_phase100_*.py -x -q` (Phase 100 tests only, <30s)
- **Per wave merge:** `.venv/bin/python -m pytest tests/test_phase100_*.py tests/test_phase76_*.py tests/test_native_parser*.py tests/test_routing*.py tests/test_routing_submodules.py tests/test_multi_pass_router.py -x -q` (regression, <60s)
- **Phase gate:** Full suite green before `/gsd-verify-work`: `.venv/bin/python -m pytest tests/ -x -q`

### Wave 0 Gaps

- [ ] `tests/test_phase100_strategy.py` — covers R-1 (Protocol + DeterministicStrategy)
- [ ] `tests/test_phase100_orchestrator.py` — covers R-1, R-7 (orchestrator construction + batch API)
- [ ] `tests/test_phase100_dispatch.py` — covers R-2 (per-net dispatch heuristics)
- [ ] `tests/test_phase100_session_freerouting.py` — covers R-3 (InteractiveRoutingSession Freerouting ingestion)
- [ ] `tests/test_phase100_rollback.py` — covers R-4 (rollback via PersistentUndoStack, 10-cycle test)
- [ ] `tests/test_phase100_audit.py` — covers R-5 (JSONL audit trail)
- [ ] `tests/test_phase100_deterministic_baseline.py` — covers R-6/SC-5 (±5% baseline, slow, Freerouting-gated)
- [ ] `tests/test_phase100_batch.py` — covers R-7 (end-to-end board route)
- [ ] `tests/test_phase100_cr01_immutability.py` — covers CR-01 (frozen dataclasses + replace migration)

**Framework install:** None needed — pytest already installed and configured. `[VERIFIED: .venv/bin/python -m pytest --version]`

---

## Common Pitfalls

### Pitfall 1: Mutating Frozen Dataclass Raises FrozenInstanceError

**What goes wrong:** After converting to `@dataclass(frozen=True)`, any existing code that does `pad.net_name = ""` raises `dataclasses.FrozenInstanceError`.
**Why it happens:** Frozen dataclasses prohibit attribute assignment.
**How to avoid:** Use `dataclasses.replace(pad, net_name="", net_number=0)`. Grep for all `\.net_name\s*=` and `\.name\s*=` patterns in the codebase before the refactor.
**Warning signs:** Test failures with `FrozenInstanceError` in the traceback.

### Pitfall 2: List Default Factory on Frozen Dataclass

**What goes wrong:** `@dataclass(frozen=True)` with `field(default_factory=list)` compiles but the list is mutable — consumers can still `.append()` to it.
**Why it happens:** Frozen prevents reassignment of the field, not mutation of the object the field references.
**How to avoid:** Use `tuple` instead of `list` for collection fields. `pads: tuple[NativePad, ...] = ()` is truly immutable.
**Warning signs:** Tests pass but the immutability guarantee is hollow. Add a test that asserts `FrozenInstanceError` on direct assignment.

### Pitfall 3: Freerouting SES Wires Without Matching PCB Net

**What goes wrong:** `import_ses_into_pcb` skips wires whose net isn't in `extract_pcb_net_names(pcb_content)`. If the PCB uses `(net N "NAME")` form and the regex misses it, routes silently vanish.
**Why it happens:** Phase 99-03 Fix 3 corrected the regex, but edge cases remain (e.g., nets declared only in footprints, not at top level).
**How to avoid:** The orchestrator should log when SES wire count > matched wire count. If the delta is large, abort with a diagnostic.
**Warning signs:** Audit trail shows `result: "success"` but DRC reports `unconnected_items`.

### Pitfall 4: PersistentUndoStack Project Directory

**What goes wrong:** `PersistentUndoStack(project_dir=pcb_path.parent)` — if the PCB is in a temp directory (common in tests), the undo files land in temp.
**Why it happens:** Undo stack uses project_dir, not a global cache.
**How to avoid:** For test fixtures, use `tmp_path` pytest fixture and assert undo files exist in `tmp_path / ".kicad-agent" / "undo"`.
**Warning signs:** Undo tests pass but files pollute the repo.

### Pitfall 5: Audit Trail Not Gitignored

**What goes wrong:** `.kicad-agent/audit/*.jsonl` gets committed to git.
**Why it happens:** `.kicad-agent/` should already be gitignored (Phase 70 added it), but verify.
**How to avoid:** `PersistentUndoStack._ensure_gitignore()` already adds `.kicad-agent/`. The audit trail lives in the same directory. Verify `.gitignore` contains `.kicad-agent/` after orchestrator runs.
**Warning signs:** `git status` shows `.kicad-agent/audit/` files.

---

## Code Examples

### DeterministicStrategy Implementation Pattern

```python
# Source: derived from Phase 99 baseline data [VERIFIED: 99-03 SUMMARY.md:64-73]
# and CONTEXT.md locked schema [VERIFIED: CONTEXT.md:62-77]

from dataclasses import dataclass

@dataclass(frozen=True)
class DeterministicStrategy:
    """Default routing strategy with no AI dependency.

    Encodes dispatch heuristics derived from Phase 99 Freerouting baseline.
    """

    def strategize(
        self,
        board_state: BoardState,
        netlist: dict[str, list[Pin]],
    ) -> RoutingStrategyResult:
        assignment: dict[str, RouterBackend] = {}
        priorities: list[str] = []

        for net_name, pins in netlist.items():
            backend = self._dispatch(net_name, pins, board_state)
            assignment[net_name] = backend
            priorities.append(net_name)

        # Sort priorities: diff pairs first, then power, then signal
        priorities.sort(key=lambda n: self._priority_rank(n, netlist))

        return RoutingStrategyResult(
            net_priorities=tuple(priorities),
            layer_hints={},  # deterministic mode doesn't hint layers
            keepouts=(),
            router_assignment=assignment,
            routing_notes="deterministic: Phase 99 baseline heuristics",
        )

    def _dispatch(
        self, net_name: str, pins: list[Pin], board: BoardState
    ) -> RouterBackend:
        # ... heuristics from §Dispatch Policy ...
```

### Immutability Migration Pattern (PcbIR.remove_net)

```python
# BEFORE (pcb_ir.py:214-227 — mutates in place):
def remove_net(self, net_name: str) -> None:
    for fp in self.board.footprints:
        for pad in fp.pads:
            if pad.net_name == net_name:
                pad.net_name = ""      # MUTATION — breaks after CR-01
                pad.net_number = 0     # MUTATION

# AFTER (immutable — uses dataclasses.replace):
import dataclasses

def remove_net(self, net_name: str) -> None:
    new_footprints = []
    for fp in self.board.footprints:
        new_pads = tuple(
            dataclasses.replace(pad, net_name="", net_number=0)
            if pad.net_name == net_name
            else pad
            for pad in fp.pads
        )
        new_footprints.append(dataclasses.replace(fp, pads=new_pads))

    new_nets = tuple(n for n in self.board.nets if n.name != net_name)
    self._native_board = dataclasses.replace(
        self._native_board,
        footprints=new_footprints,
        nets=new_nets,
    )
    self._record_mutation("remove_net", {"net_name": net_name})
```

### Audit Trail Entry Pattern

```python
import json
from datetime import datetime, timezone
from pathlib import Path

def write_audit_entry(audit_path: Path, entry: RoutingAuditEntry) -> None:
    """Append one JSONL line to the audit log."""
    line = json.dumps({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "net_name": entry.net_name,
        "router_used": entry.router_used.value,
        "strategy": entry.strategy,
        "dispatch_reason": entry.dispatch_reason,
        "result": entry.result,
        "route_length_mm": entry.route_length_mm,
        "via_count": entry.via_count,
        "drc_clean": entry.drc_clean,
        "notes": entry.notes,
    })
    with open(audit_path, "a", encoding="utf-8") as f:
        f.write(line + "\n")
```

---

## Assumptions Log

> List all claims tagged `[ASSUMED]` in this research. The planner and discuss-phase use this section to identify decisions that need user confirmation before execution.

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | JSONL is the right audit format (vs SQLite) | R-5 Audit Trail | Low — can migrate later. SQLite adds query power but JSONL is simpler for v1. |
| A2 | Dispatch heuristics (pin count >10 → FR, ≤20 nets → FR, etc.) | Dispatch Policy | Medium — thresholds from Phase 99 baseline on 3 fixtures may not generalize. Planner can adjust. |
| A3 | Per-net rollback via regex net-name filtering is robust | R-4 Rollback | Medium — if segments lack `(net "name")` tags, rollback fails. Verified they do have tags. |
| A4 | `tuple[tuple[str, str], ...]` is the right frozen representation for properties dict | CR-01 Risk 1 | Medium — adds indirection. Alternative: MappingProxyType with runtime enforcement. |
| A5 | Cross-backend rerouting (reject FR → reroute with A*) is acceptable UX | R-3 | Low — user rejected the route anyway; trying a different backend is reasonable. |
| A6 | Strategy Protocol (not ABC) is the right interface for Phase 98 | R-1 | Low — Protocol enables duck typing but loses runtime isinstance checks. Phase 98 can use ABC if preferred. |

**If this table is empty:** All claims in this research were verified or cited — no user confirmation needed.

---

## Open Questions

### 1. Should the orchestrator route nets sequentially or in parallel?

- **What we know:** A* routing is CPU-bound and could parallelize. Freerouting is a single Java subprocess (sequential by nature). The existing `route_all_nets` routes sequentially (shortest first).
- **What's unclear:** Whether dispatching independent A* nets in parallel via `concurrent.futures.ThreadPoolExecutor` is worth the complexity for v1.
- **Recommendation:** Start sequential. The bottleneck is Freerouting (single subprocess), not A*. Parallelism can be added later if benchmarks show A* is the bottleneck. Document this as a future optimization.

### 2. Should the audit trail capture per-net DRC results or only the final board DRC?

- **What we know:** Running `kicad-cli pcb drc` per net is expensive (~2-10s per invocation). Running it once at the end is fast but loses per-net attribution.
- **What's unclear:** Whether the user needs per-net DRC in the audit trail for debugging, or if the final board DRC is sufficient.
- **Recommendation:** Capture final board DRC only (R-5 says "every routing decision logged" — DRC per decision is not required). Add a `drc_clean: bool` field to the final summary entry. If per-net DRC is needed later, add an optional `--per-net-drc` flag.

### 3. How should the orchestrator handle Freerouting failures mid-batch?

- **What we know:** Freerouting can fail on specific boards (RaspberryPi-uHAT 3.2% completion, synthetic 4-layer NPE crash). `[VERIFIED: 99-03 SUMMARY.md:66-75]`
- **What's unclear:** When Freerouting fails on the whole board (not per-net), should the orchestrator fall back to A* for all dispatched nets, or just mark them as failed?
- **Recommendation:** Fall back to A* for nets dispatched to Freerouting when Freerouting returns `success=False`. Log the fallback in the audit trail (`dispatch_reason: "freerouting_failed_fallback_astar"`). This maximizes completion rate.

### 4. Should CR-01 be a separate plan or integrated into the orchestrator plan?

- **What we know:** CONTEXT.md estimates "2 plans, ~10 days." CR-01 is substantial (14 dataclasses, 8 mutation sites, 321 regression tests).
- **What's unclear:** Whether CR-01 fits in Plan 1 (before orchestrator) or needs its own plan.
- **Recommendation:** CR-01 = Plan 1. Orchestrator = Plan 2. This ordering ensures the orchestrator builds on immutable foundations. If CR-01 proves larger than expected, split into Plan 1a (dataclass freeze) + Plan 1b (mutation site migration).

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.11 | All code | ✓ | 3.11.11 (`.venv`) | — |
| pytest | Test framework | ✓ | pre-installed in `.venv` | — |
| Freerouting JAR | R-2 dispatch to Freerouting, R-6 baseline test | ✓ | `~/.kicad-agent/tools/freerouting.jar` (sha1: 4a2a586f) | Tests skip via `is_freerouting_available()` |
| Java runtime | Freerouting subprocess | ✓ | system java | Tests skip if absent |
| kicad-cli | DRC validation (R-4 rollback test) | ✓ | 10.0.1 | DRC-dependent tests skip |
| networkx | A* pathfinding | ✓ | pre-installed | — |
| shapely | Spatial queries (existing) | ✓ | pre-installed | — |

**Missing dependencies with no fallback:** None.

**Missing dependencies with fallback:** None — all required tools are available.

---

## Sources

### Primary (HIGH confidence)

- **Codebase inspection** — all file paths cited inline. Read during this research session.
- **Phase 99 SUMMARY files** (99-01, 99-02, 99-03) — baseline metrics, bug fixes, deferred items.
- **CONTEXT.md** (Phase 100) — locked decisions, requirements R-1 through R-7, RoutingStrategy schema sketch.
- **STATE.md** — CR-01 deferral details, 5-step resolution plan.
- **`.planning/config.json`** — `nyquist_validation: true` (Validation Architecture section required).

### Secondary (MEDIUM confidence)

- **Phase 99 baseline script** (`scripts/phase99_baseline.py`) — dispatch policy data source.
- **Python `typing.Protocol` docs** — Protocol vs ABC choice for RoutingStrategy interface.
- **Python `dataclasses` docs** — `frozen=True` behavior, `replace()` pattern.

### Tertiary (LOW confidence)

- **JSONL vs SQLite for audit** — `[ASSUMED]` based on general observability practices, no specific source cited.

---

## Metadata

**Confidence breakdown:**
- Standard stack (existing infrastructure): HIGH — all components inspected in codebase, line counts verified.
- Architecture (orchestrator + strategy pattern): HIGH — CONTEXT.md locks the schema; Phase 99 provides baseline data.
- CR-01 immutability refactor: HIGH — STATE.md documents the 5-step plan; mutation sites verified via grep.
- Dispatch heuristics: MEDIUM — thresholds derived from 3-fixture baseline, may not generalize to all boards. Tagged `[ASSUMED]`.
- Pitfalls: HIGH — based on Python dataclass semantics and Phase 99 documented bug fixes.

**Research date:** 2026-06-25
**Valid until:** 2026-07-25 (30 days — stable codebase, no fast-moving external dependencies)
