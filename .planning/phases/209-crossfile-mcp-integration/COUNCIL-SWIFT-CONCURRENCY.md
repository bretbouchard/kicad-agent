---
phase: 209-crossfile-mcp-integration
role: swift-concurrency-expert
reviewed: 2026-07-10
verdict: APPROVE-WITH-REQUIRED-FOLLOWUPS
---

# Phase 209 Cross-File / MCP Integration — Swift Concurrency Review

**Reviewer:** Swift Concurrency Expert
**Scope:** The async boundary between the Swift Mac app (`@MainActor` daemon layer, Phase 162/167/169/170) and the v7.0 manufacturing ops (`build_handoff_export`, `build_create`, etc.) that now auto-expose as MCP tools.
**Verdict: APPROVE WITH REQUIRED FOLLOW-UPS** — Phase 209 itself changes zero Swift code (it is integration-only on the Python side), so there is nothing to block. However, **the moment the Mac app actually calls `build_handoff_export` from a `@MainActor` context, three concrete concurrency defects will surface.** They are documented below as required follow-ups, not blockers for 209.

## Architecture As Reviewed

The control flow for a manufacturing op called from Swift:

```
SwiftUI view (@MainActor)
  → MCPClient.governedCall("tools/call", params:[name:"build_handoff_export", ...])
    → VerificationLoop.run(...) (@MainActor)        // checkpoint → pre-op
      → MCPClient.callRaw(...)                       // hops via continuation
        → DaemonMessenger.call(method, params)       // writes JSON-RPC line to stdin
          ╶╶ [stdio pipe] ╶╶
            daemon_entry.py: dispatch() → loop.run_in_executor(None, handler)
              handlers/build.py: _handle_build_handoff_export
                manufacturing/handoff.py: export_handoff()   // SYNCHRONOUS, 11 steps, multi-second
```

Key facts that drive every finding below:

1. **`export_handoff` is fully synchronous Python** (`handoff.py:254`) — it shells out to `kicad-cli` up to 7+ times (gerber, drill, cpl, bom, netlist, step, pdfs). Each `kicad-cli` invocation is a blocking `subprocess.run`.
2. **The daemon dispatches via `loop.run_in_executor(None, handler)`** (`daemon_entry.py:206`) — so the blocking op runs on the default `ThreadPoolExecutor`, not the asyncio event loop. The loop stays responsive and the heartbeat task keeps firing. This is **correct** and is what makes the call safe to await from Swift.
3. **The Swift side is uniformly `@MainActor`**: `ProcessManager`, `DaemonMessenger`, `MCPClient`, and all Phase 169/170 governance (`WorkflowStateMachine`, `IntentGate`, `OpJournal`, `VerificationLoop`). `ProcessManager.swift:67` and `DaemonMessenger.swift:62` both carry explicit `@MainActor`.
4. **`MCPClient.requestTimeout = .seconds(30)`** (`MCPClient.swift:51`) and `ProcessManager.watchdogTimeout = .seconds(30)` (`ProcessManager.swift:74`) are the same value.

## Findings — By Review Question

### Q1. Is `build_handoff_export` safe to call from a `@MainActor` context?

**Safe in the sense that matters, but the 30s timeout is a latent bug.**

Because `export_handoff` is offloaded to `run_in_executor` on the Python side, the asyncio loop never blocks, and the heartbeat keeps the Swift watchdog fed. The Swift `callRaw` continuation suspends (it does not spin the main thread) — so the UI thread is free. **There is no main-thread stall.** Good.

**The problem is duration.** A handoff with STEP export + schematic PDF + PCB PDF render can easily exceed 30s (STEP 3D model export alone is routinely 10–40s for a populated board). Both timers fire at 30s:

- `MCPClient.callRaw`'s timeout arm (`MCPClient.swift:153`) resumes with `.timeout` and cancels the call task.
- `ProcessManager`'s watchdog (`ProcessManager.swift:371`) — although the heartbeat should keep resetting it, see Q5: the daemon's heartbeat is on a 10s cadence and *only emits between requests* if `read_requests` is idle. While a long handler runs, `read_requests` is `await`ing `dispatch()`, so the opportunistic `maybe_heartbeat()` on line 276 does **not** run. Only the dedicated `heartbeat_loop` (10s interval) emits. So the watchdog *should* survive — but the margin is thin (10s heartbeat vs 30s watchdog) and the per-request RPC timeout will kill it first regardless.

**Required follow-up (RF-1):** `build_handoff_export` (and only that op) must be called with an explicit, extended timeout. Do **not** raise the global `MCPClient.requestTimeout` — that would weaken safety for every op. Instead:

```swift
// Manufacturing calls pass an op-specific timeout.
let result = try await client.governedCall(
    "tools/call",
    params: ["name": "build_handoff_export", "arguments": args],
    as: HandoffResultDTO.self,
    timeout: .seconds(180)   // STEP + renders can take minutes
)
```

This requires threading `timeout` through `governedCall` → `callRaw` (it currently hardcodes `MCPClient.requestTimeout` inside `governedCall` at line 370). `governedCallRaw` already ignores timeout entirely (line 523) — that path has **no** timeout at all, which is its own defect (RF-2).

### Q2. Should the daemon expose async cancellation for handoff operations?

**Yes — this is a real gap.** Currently:

- When Swift cancels the `callRaw` task (timeout or user cancel), the Swift-side continuation is resumed but **the Python handler keeps running to completion** in the executor. There is no wire-level cancel. The orphaned `export_handoff` continues shelling out to `kicad-cli`, writing files, and eventually emits a JSON-RPC response that `DaemonMessenger` drops (no matching pending id — logged as "resume for unknown id").
- The orphaned subprocess children (`kicad-cli`) are not killed. On a large board this can leave multi-hundred-MB temp files and a lingering `kicad-cli` consuming CPU.

**Required follow-up (RF-3):** Add a JSON-RPC `$/cancelRequest` (the spec-defined method) or a custom `cancel` notification from Swift → daemon. The daemon must:
1. Track the `Future` returned by `loop.run_in_executor` keyed by request id.
2. On cancel, the executor task can't be hard-killed (Python threads aren't cancellable), but the daemon can set a cancel flag that `export_handoff` polls between export steps, and/or kill the active `kicad-cli` child via a process group.

On the Swift side, `Task.cancel()` must trigger the cancel notification. The cleanest hook is in `MCPClient.callRaw`'s timeout/cancel arm (`MCPClient.swift:159`): `callTask.cancel()` currently does nothing on the wire. Wire it to fire a `notify("$/cancelRequest", params:["id": id])`.

**Lower priority but recommended:** even without full cancel, the build-dir cleanup path in `handoff.py` (`_fail_with_cleanup`, line 632) already `rmtree`s on failure — so at least no partial build dir survives a Python-side exception. But an orphaned-by-cancel run is not an exception; it completes "successfully" into the void. The cleanup guarantee does not cover it.

### Q3. Are there Sendable concerns with passing `Build`/`BoardSpec` data across actor boundaries?

**No concern at the Python↔Swift boundary. The data is JSON-serialized on the wire.** `DaemonMessenger.call` takes `[String: Any]` params (line 138), JSON-encodes them, and the result comes back as a JSON `Any` wrapped in `SendableBox` (`DaemonMessenger.swift:212`). So nothing crosses actor boundaries as a live object — it's all value-type JSON by the time Swift sees it.

**The real Sendable concern is on the Swift decoding side, and it is already correctly handled:**

- `MCPClient.call<T: Decodable>` re-serializes the `SendableBox.value` to `Data` and decodes into `T` (line 87). If you define Swift DTOs for the manufacturing results, **they must be `Sendable`** to satisfy `governedCall`'s `<T: Decodable & Sendable & Equatable>` constraint (line 296).
- `governedCall` requires `T: ... & Sendable`. So any `HandoffResultDTO`, `BuildDTO`, etc. must conform. For value-type structs of `let` properties this is free. **Do not** define them as `class`es without justification, and do not use `@unchecked Sendable` on them — the JSON origin guarantees pure value types.

```swift
// Correct shape for a manufacturing result DTO:
struct HandoffResultDTO: Decodable, Sendable, Equatable {
    let success: Bool
    let zipPath: String?
    let artifactCount: Int
    let buildId: String?
    // ...mirror the dict shape from build.py:350-363
}
```

Note the existing code passes `params: [String: Any]` into `governedCall`, which is **not Sendable** — this works only because `governedCall` is `@MainActor`-isolated and the `[String: Any]` never actually crosses an actor boundary (it's built and consumed on the main actor). This is a pre-existing smell (the `Any` dictionary escapes Sendable checking entirely) but it is not made worse by Phase 209, and tightening it would be a separate refactor (RF-4: introduce a `SendableParams`/`AnyCodable`-based params type).

### Q4. Should the manufacturing ops use Swift's `AsyncSequence` for progress reporting?

**They should, but this is a v7.1 enhancement, not a 209 blocker.** The infrastructure is half-built:

- `MCPResponseStream` (`MCPClient.swift:711`) is an `AsyncSequence` scaffold that currently returns `nil` immediately (`next()` at line 731). It is explicitly stubbed "Phase 168 will wire this."
- The daemon already emits unsolicited notifications (heartbeats via `make_notification`, `protocol.py:92`). The JSON-RPC notification channel exists; `DaemonMessenger.ingest` routes id-less `heartbeat` messages (line 99) but **drops all other notifications** with a warning (line 108).

A handoff export is the canonical use case for streaming progress (gerbers done → drill done → step 40% → zipping...). The design would be:

1. Python: `export_handoff` emits `notifications/progress` lines between steps (it already has natural checkpoints at each `_record_export` call).
2. `DaemonMessenger.ingest`: route `method == "notifications/progress"` into a buffered `AsyncStream` rather than dropping it.
3. `MCPResponseStream`: back the iterator with that buffer.

**Recommendation:** Defer to v7.1 alongside the cancel support (RF-3) — they are the same feature surface (long-running op UX). For v7.0, the indeterminate-progress spinner driven by `governedCall`'s await is acceptable.

### Q5. Is the JSON-RPC protocol adequate for streaming export progress, or does it need a callback mechanism?

**The protocol is adequate; the implementation is not yet wired.** JSON-RPC 2.0 explicitly supports server-initiated notifications (no `id`), and the daemon already uses this for heartbeats. Progress streaming is just "heartbeat with a payload + correlation to the originating request id."

**One caveat that affects Q1's watchdog analysis:** the daemon has *two* heartbeat paths and they behave differently under load:

- `heartbeat_loop` (`daemon_entry.py:290`): independent `asyncio.create_task`, 1s sleep, emits every 10s. **Keeps running while a handler is in the executor.** This is what saves the watchdog.
- `read_requests` opportunistic `maybe_heartbeat()` (line 276): only runs between fully-processed requests. **Stalls during a long `dispatch()` await.**

So during a 60s handoff, only `heartbeat_loop` feeds the watchdog. It emits every 10s; the watchdog is 30s. Margin is fine *today*. But if someone later raises `HEARTBEAT_INTERVAL_S` or lowers the watchdog, this breaks silently. **RF-5:** Document this invariant in `ProcessManager.swift` near `watchdogTimeout` — the watchdog timeout must remain ≥ 3× `HEARTBEAT_INTERVAL_S`.

For progress specifically: a `notifications/progress` with `params: {request_id, step, total_steps, message}` is the right callback shape. It does not require a protocol change, only a routing change in `DaemonMessenger.ingest`. This ties directly to Q4.

### Q6. Any data race risks if multiple manufacturing ops run concurrently?

**Yes — two distinct risks.**

**Risk A (filesystem, Python-side — real):** Two concurrent `build_create` or `build_handoff_export` calls targeting the same `project_dir` race on the `builds/` directory. The code mitigates this with `mkdir(parents=True, exist_ok=False)` and a uuid-suffixed retry on `FileExistsError` (`build.py:99-104`, `handoff.py:394-400`). So directory creation is atomic-by-rename-semantics and collision-safe. **But:** the `build_list`/`build_show` readers (`build.py:231`) glob and `json.loads` concurrently with writers. A `Build.load()` mid-write could read a half-flushed `build.json`. The `atomic_write` helper (`io/atomic_write`) is used by `Build.save` (line 116) and `manifest.save`, so the *content* is atomic — but a reader could still see the file absent between `mkdir` and `save`. The `build_list` handler tolerates this (skips corrupt dirs, line 238). **Acceptable for v7.0.**

**Risk B (Swift-side concurrency — real, pre-existing, made reachable by 209):** `DaemonMessenger` is `@MainActor` and routes replies by id via `self.pending: [String: CheckedContinuation]`. Because it's `@MainActor`, all `ingest`/`call`/`resume` mutations are serialized. **No data race on the map.** Good. The concern is *semantic* concurrency: nothing in `MCPClient` or `governedCall` prevents the UI from firing two `build_handoff_export` calls simultaneously. They'd both run on the Python executor (default pool, ~min(32, cpu+4) threads), both write to `builds/`, both shell out to `kicad-cli`. The `WorkflowStateMachine` guard in `governedCall` (line 339) requires `.executing` state for mutating ops — **but `build_*` ops are registered as read-only** (`build.py:7-10`), so they bypass the state machine entirely. Two concurrent handoffs are therefore not gated.

**RF-6:** The Mac app should serialize manufacturing exports at the call site (e.g., a per-project `AsyncSemaphore` or a simple "export in progress" flag in the view model). The Python side is collision-safe but the UX of two simultaneous exports is confusing and doubles `kicad-cli` load. Do not rely on the state machine for this since these ops are deliberately read-only.

### Q7. Should the build directory creation be atomic from the Swift side's perspective?

**It already is, from Swift's perspective, because Swift never sees the directory until the RPC returns.** `build_create` returns the full result (success or error dict) atomically — `build.py:162-170` rmtree's the partial dir on any exception before returning. So Swift observes a binary outcome: either a valid `build_dir` path in the result, or `success: false` with no directory. There is no intermediate observable state.

**The one nuance:** `build_handoff_export` creates the build dir (`handoff.py:393`) *before* running exports, and only `rmtree`s on failure (`_fail_with_cleanup`, line 632). Between `mkdir` and the final `rmtree`/success, the directory exists on disk with partial contents. If the user (via Finder) or another tool inspects `builds/` mid-export, they see a partial handoff dir. This is a **Python-side** concern, not a Swift-concurrency concern, and the atomic-write + rmtree-on-failure pattern is the standard mitigation. From Swift's actor-isolation perspective there is nothing to do — Swift holds no reference to the path until the RPC resolves.

**No action required.** If a future phase wants to hide partial dirs from the filesystem view, the Python-side fix is to build into a `.tmp` dir and rename on success — but that's a `handoff.py` change, out of scope for a concurrency review.

### Q8. How should the Mac app handle the "validation failed" case from a concurrency perspective?

**`validation failed` is not an error at the concurrency layer — it's a successful RPC returning `success: false`.** This is the critical distinction:

- `export_handoff` returns a `HandoffResult(success=False, ...)` **normally** (`handoff.py:377, 613`). It does not raise.
- The daemon wraps it as a JSON-RPC **result** (`make_result`, `daemon_entry.py:219`), not an error.
- Swift's `DaemonMessenger.ingest` routes it through the success path (`DaemonMessenger.swift:125`), and `MCPClient.callRaw` returns it as `Any`.

So from Swift's `@MainActor` perspective, a validation failure is a **normal awaited return value**, decoded into the DTO with `success == false`. No continuation is leaked, no error propagates, no watchdog trips. The governance layer (`VerificationLoop`) sees the op "succeed" at the transport level (the RPC completed) — which is correct, because the *manufacturing validation* failed, not the *operation execution*.

**The subtlety is in `governedCall`'s post-op gate.** `VerificationLoop.run` (Phase 170) runs ERC/DRC *after* the op completes (`MCPClient.swift:363`). For `build_handoff_export`, the op already ran DRC/ERC internally (step 3, `handoff.py:333`) and returned `success=false` if they failed. The post-op gate then re-runs ERC/DRC on the (unchanged) PCB. For a read-only op that didn't modify the PCB, this is redundant but harmless — the PCB state is identical, so pre-op and post-op checks agree. **No data race; just wasted cycles.**

**Recommended handling in the view layer (not a concurrency defect):**

```swift
let outcome = try await client.governedCall(..., as: HandoffResultDTO.self)
// governedCall returns normally here — no throw.
if !outcome.value.success {
    // Show validation failures from outcome.value.validation.
    // This is a . MainActor UI update — safe.
    presentValidationFailures(outcome.value.validation)
} else {
    presentHandoffPackage(outcome.value.zipPath)
}
```

Do **not** treat validation failure as a Swift `throws` — that would conflate transport failure with business failure and skew the `OpJournal`/`EscalationLadder` (Phase 169 would record a "failed" op when the op actually succeeded at its job of *detecting* un-manufacturability). The journal should record `success` with `verification=passed`; the *handoff* failed, the *operation* did not.

## Summary of Required Follow-Ups

All are **post-209** (Phase 209 ships zero Swift changes and is correctly approved). They become live the moment the Mac app wires a real "Export Handoff" button.

| ID | Severity | Finding | Location |
|----|----------|---------|----------|
| RF-1 | **High** | `build_handoff_export` needs an op-specific extended timeout (≥120s); the default 30s will fire mid-export. Thread `timeout` through `governedCall`. | `MCPClient.swift:370` (hardcoded timeout in governed call) |
| RF-2 | **High** | `governedCallRaw` has **no timeout at all** (line 523) — an op that hangs via this path hangs forever (watchdog eventually kills the daemon, but the Swift task is unbounded). | `MCPClient.swift:523` |
| RF-3 | **High** | No wire-level cancellation. Swift `Task.cancel()` does not stop the Python handler or its `kicad-cli` children. Orphans run to completion. Add `$/cancelRequest`. | `MCPClient.swift:159`, `daemon_entry.py:206` |
| RF-4 | Medium | `[String: Any]` params escape Sendable checking (pre-existing). Acceptable while everything is `@MainActor`, but blocks any future off-main-actor call path. | `MCPClient.swift:76`, `DaemonMessenger.swift:138` |
| RF-5 | Medium | Undocumented invariant: `watchdogTimeout` (30s) must stay ≥ 3× `HEARTBEAT_INTERVAL_S` (10s) or long ops false-positive the watchdog. | `ProcessManager.swift:74`, `daemon_entry.py:131` |
| RF-6 | Medium | Concurrent manufacturing exports are ungated (ops are read-only → bypass `WorkflowStateMachine`). Serialize at the call site. | New: per-project `AsyncSemaphore` in the view model |

## What Phase 209 Got Right (Concurrency-Wise)

- **Zero Swift changes**, so zero new data-race surface. The integration is entirely Python-side (CLI/MCP wiring) and the MCP auto-exposure path is verified-only.
- The existing `@MainActor` isolation on the entire daemon layer (`ProcessManager`, `DaemonMessenger`, `MCPClient`, governance) is **correct and consistent**. All mutable state (pending continuations, watchdog task, crash timestamps, process handle) lives on the main actor. No locks are needed in Swift because there's a single accessor.
- `LineBuffer: @unchecked Sendable` (`ProcessManager.swift:461`) is a **justified** `@unchecked` — it's backed by an `NSLock` and all access is serialized through `append()`. This is the correct pattern for a buffer captured in a readability handler.
- `SendableBox: @unchecked Sendable` (`DaemonMessenger.swift:212`) is **justified** — it only ever wraps `JSONSerialization` output (value types). The comment correctly notes the caller's responsibility.
- The `run_in_executor` dispatch on the Python side is the right call — it keeps the asyncio loop responsive so heartbeats flow and the Swift watchdog stays fed during long exports.

## Verdict

**APPROVE WITH REQUIRED FOLLOW-UPS.** Phase 209 is concurrency-clean because it touches no Swift. RF-1/RF-2/RF-3 are the three issues that **must** be resolved before the Mac app exposes a real manufacturing-export button — they are defects in the *existing* Phase 162/167 daemon layer that v7.0's long-running ops make reachable for the first time. Track them as a follow-up phase (suggested: "Phase 211 — Manufacturing Call Hardening") rather than blocking the v7.0 milestone.
