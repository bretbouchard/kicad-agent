# Council Findings vs Phase 211-217 Roadmap — Cross-Reference

**Date:** 2026-07-11
**Purpose:** Map the 6 Apple specialist council findings against the other team's Phase 211-217 plan

---

## What the Other Team Has Shipped

### Phase 211 (SHIPPED — commit 93a0f6f)
Chat → Router → Stream pipeline. `RouterStreamProvider` bridges `KiCadModelRouter` to `ChatStreamProvider`. User types → conversation created → LLM streams response → saved to SwiftData. 3 files, 164 LOC.

### Phase 212 (SHIPPED — commit 83990e8)
Daemon operations from chat. `OperationExecutor` parses LLM responses for JSON code blocks with `op_type`, sends them via `MCPClient.callRaw("tools/call", ...)`, results appear as system messages. 3 files, 129 LOC.

### Phase 213 (PLANNED — not started)
Lets users open real KiCad files.

### Phase 214 (PLANNED — not started)
Visual feedback after operations.

### Phase 215 (PLANNED — lower priority)
Collaboration.

### Phase 216 (PLANNED — not started)
ERC/DRC validation.

### Phase 217 (PLANNED — not started)
Honesty pass (docs/tests).

---

## Council Findings Mapped to Phases

### CRITICAL-1: IntentGate catalog missing manufacturing ops

**Status: BYPASSED by Phase 212, but not safely.**

Phase 212's `OperationExecutor` calls `client.callRaw("tools/call", ...)` directly — it does NOT go through `governedCall`. This means it **bypasses IntentGate entirely**. The LLM can emit any operation JSON and it executes without governance validation.

This is actually why CRITICAL-1 doesn't block Phase 211/212 — they sidestep the governed path. But it creates a **new security concern**: the LLM's output is executed unsanitized via `callRaw`. If the LLM hallucinates a destructive op (e.g., `remove_all_footprints`), there's no IntentGate to block it.

**Recommendation for Phase 212 follow-up or Phase 217 (honesty pass):**
- Switch `OperationExecutor` from `callRaw` to `governedCall` (or at minimum `governedCallRaw`)
- Add the 10 manufacturing ops to IntentGate's catalog
- Add a whitelist of allowed ops for LLM-initiated execution (don't allow the LLM to run ANY op — only safe ones)

### CRITICAL-2: App sandbox blocks handoff workflow

**Status: NOT YET RELEVANT — Phase 213 (open KiCad files) will surface this.**

Phase 213 is when users open real `.kicad_pcb` files. At that point, the sandbox entitlements (`files.user-selected.read-write`) grant access to the opened file, but NOT to creating a `builds/` directory next to it or writing `.kicad_build_spec.json` sidecars.

**Recommendation for Phase 213:** Use the `.kicadagent` document bundle (Phase 190) as the container. When the user opens a KiCad project, wrap it in a `.kicadagent` bundle that owns the `builds/` directory. This gives sandbox-safe directory-scoped access.

### HIGH-1: Zero Mac app UI for manufacturing

**Status: DEFERRED — not in the 211-217 plan.**

The 211-217 roadmap focuses on making the app respond (chat), execute ops (daemon), open files (213), show visual feedback (214), and validate (216). Manufacturing UI (BoardSpec editor, handoff wizard, vendor DRC results, build history) is NOT in scope.

**This is correct sequencing.** You can't show a handoff wizard before the app can even open files (Phase 213) or show visual feedback (Phase 214). Manufacturing UI should come after 213-216 are shipped — likely a v7.1 or post-217 phase.

**However:** Once Phase 212 is in place, a user CAN type "prepare this board for JLCPCB manufacturing" in the chat, and if the LLM emits a `build_handoff_export` op JSON, it will execute via `callRaw`. The result will appear as a system message. No UI needed — it's conversational. This is actually a great interim UX.

### HIGH-2: 30s daemon timeout too short for handoff exports

**Status: WILL HIT when Phase 212 + manufacturing ops meet.**

`callRaw` has `timeout: Duration = MCPClient.requestTimeout` which is `.seconds(30)`. A handoff with STEP export takes 60-120s. The first time a user types "prepare for manufacturing" in the chat, it will timeout.

**Recommendation for Phase 212 follow-up:** `OperationExecutor` should pass a longer timeout for known long-running ops. Or better: add a `timeout` field to `OpMeta` in the Python registry so the Swift side knows which ops need extended timeouts.

```swift
// In OperationExecutor.execute():
let timeout: Duration = switch op.opType {
case "build_handoff_export": .seconds(300)
case "drc_vendor": .seconds(120)
default: MCPClient.requestTimeout
}
let result = try await client.callRaw("tools/call", params: ["name": op.opType, "arguments": op.arguments], timeout: timeout)
```

### HIGH-3: BoardSpec persistence mismatch

**Status: NOT YET RELEVANT — surfaces when manufacturing UI is built (post-217).**

The sidecar `.kicad_build_spec.json` lives next to the PCB file. SwiftData `Project` doesn't know about it. This only matters when a UI tries to read/write BoardSpec — which is post-217 work.

**Recommendation for Phase 213:** When the `.kicadagent` bundle wraps a KiCad project, include the `.kicad_build_spec.json` inside the bundle. SwiftData can track it as a bundle resource.

### HIGH-4: DRC violation coordinates dropped

**Status: NOT YET RELEVANT — surfaces when DRC results are displayed (Phase 216).**

Phase 216 will show ERC/DRC validation results. If it shows vendor DRC results too, the violations will lack coordinates — meaning no "click to zoom" on the violating feature.

**Recommendation for Phase 216:** Add coordinate fields to the violation items dict in `vendor_drc.py` BEFORE building the DRC results UI. This is the trivial 4-field fix VisionOS Rick and Metal 4 Rick both recommended. It benefits the macOS display immediately and enables future visionOS/GPU work.

---

## What the Council Adds to the 211-217 Roadmap

| Phase | Council Impact | Action |
|-------|---------------|--------|
| **211** (shipped) | No impact — chat streaming works fine | None needed |
| **212** (shipped) | **Bypasses IntentGate via callRaw** — security concern | Switch to governedCall, add op whitelist for LLM-initiated ops, add per-op timeout |
| **213** (planned) | **Sandbox will block builds/ directory** | Use .kicadagent bundle as container; include .kicad_build_spec.json inside |
| **214** (planned) | No direct impact — visual feedback for ops is good | None needed, but consider showing handoff progress (long-running op) |
| **215** (planned) | No impact — collaboration is independent | None needed |
| **216** (planned) | **Add DRC coordinates before building DRC results UI** | Fix vendor_drc.py violation items to include x/y coordinates |
| **217** (planned) | **Honesty pass should cover the callRaw→governedCall gap** | Include the OperationExecutor governance fix in the honesty pass |

---

## The Good News

The other team's sequencing is **correct**. They're building the foundation (chat → daemon → file access → visual feedback → validation) before the manufacturing UI. The council's #1 finding (zero Mac app UI) is expected at this stage — you build the plumbing before the fixtures.

The conversational path is already live: a user can type "run DRC against JLCPCB rules on this board" and if the LLM emits the right JSON, `OperationExecutor` will fire `drc_vendor` via the daemon. No UI needed. This is the fastest path to value.

## The Warning

**Phase 212's `callRaw` bypass is a ticking bomb.** The LLM can execute ANY operation unsanitized. Before Phase 213 (opening real files) or Phase 216 (validation), `OperationExecutor` must switch to `governedCall` with an op whitelist. The first time a user opens a real board and the LLM hallucinates a destructive op, the lack of IntentGate will hurt.

---

## Priority Actions for the Other Team

1. **Phase 212 follow-up (NOW):** Switch `OperationExecutor` from `callRaw` to `governedCallRaw`. Add manufacturing ops to IntentGate catalog. Add per-op timeout for long-running ops.
2. **Phase 213:** Use `.kicadagent` bundle for sandbox-safe file access.
3. **Phase 216:** Add DRC violation coordinates to `vendor_drc.py` before building DRC results UI.
4. **Phase 217:** Include the governance gap fix in the honesty pass.
5. **Post-217:** Manufacturing UI phase (BoardSpec editor, handoff wizard, vendor DRC results, build history).
