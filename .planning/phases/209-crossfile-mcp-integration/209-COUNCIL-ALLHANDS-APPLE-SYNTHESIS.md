# Council of Ricks — All-Hands Apple Specialist Review (v7.0 Milestone)

**Date:** 2026-07-11
**Scope:** Full v7.0 Vendor-Neutral Manufacturing Layer milestone (Phases 205-209)
**Specialists:** Apple Elitist Rick, Foundation Models Rick, SwiftUI Liquid Glass, Swift Concurrency Expert, Metal 4 Rick, VisionOS Rick
**Context:** Phase 211 (Volta PCB Chat → Router → Stream Pipeline) is PLANNED but not yet built. The app has been rebranded to "Volta PCB" with a Gemma 4 12B LoRA adapter trained.

---

## Verdict: APPROVE with REQUIRED FOLLOW-UPS

The v7.0 Python manufacturing layer is architecturally sound, secure, and complete. The gap is not in what was built — it's in what connects it to the Mac app. Phase 211 is the natural home for the wiring work.

---

## Severity Summary

| Severity | Count | Blocking? |
|----------|-------|-----------|
| CRITICAL | 2 | No — Phase 211 hasn't shipped yet, so these are pre-wiring fixes, not regressions |
| HIGH | 4 | No — track for Phase 211 / v7.1 |
| MEDIUM | 6 | No |
| LOW | 5 | No |

---

## CRITICAL Findings

### CRITICAL-1: IntentGate catalog missing all manufacturing ops (Apple Elitist Rick)

The Mac app's `IntentGate.validate` (`macos-app/Sources/Volta/Governance/IntentGate.swift`) has a hardcoded 23-op catalog. None of the 10 v7.0 manufacturing ops are in it. Any governed call from the Mac app to `build_handoff_export`, `drc_vendor`, etc. will throw `unknownOp` before reaching the daemon.

**Fix:** Add the 10 manufacturing ops to the catalog — read-only ops under `GOV-11`, mutating ops under a new `MFG-01` requirement. ~6-line Swift patch. This is Phase 211 work since that's when the Mac app starts calling these ops.

### CRITICAL-2: App sandbox blocks handoff workflow (Apple Elitist Rick)

`Volta.entitlements` grants only `files.user-selected.read-write`. But `handoff.py` does `mkdir(project_dir / "builds")` and `board_spec.py` writes a sidecar next to the PCB — both outside the user-selected-file grant. The PyInstaller daemon subprocess has even fewer entitlements.

**Fix:** Make the `.kicadagent` bundle (Phase 190's `KicadAgentDocument: FileDocument`) own the `builds/` directory. Opening the bundle grants directory-scoped access. Track for Phase 211 or a dedicated sandbox-hardening phase.

---

## HIGH Findings

### HIGH-1: Zero Mac app UI for manufacturing (SwiftUI Liquid Glass)

A grep for `manufactur|boardspec|handoff|vendordrc` across all 33 Swift view files returns nothing. The entire manufacturing feature surface is invisible to the Mac user. The Python layer is data-complete; the SwiftUI layer doesn't exist.

**Priority P0 for Phase 211+:** `HandoffWizardView` (4-step sheet: vendor → validation → readme → package) and `VendorDrcResultsView` (violation list with severity badges). The existing design system (`LiquidGlassModifiers.swift` — `.liquidGlassPanel/Hero/Toolbar`) covers ~80% of component needs. Main new work: Codable data-bridge mirroring Python dataclasses (`KCBoardSpec`, `KCViolation`, `KCHandoffResult`).

### HIGH-2: 30s daemon timeout too short for handoff exports (Swift Concurrency)

`MCPClient.callRaw` and the ProcessManager watchdog both default to 30s. A handoff with STEP + PDFs routinely exceeds that. `governedCall` hardcodes the timeout. `governedCallRaw` has no timeout at all.

**Fix:** Thread `timeout` parameter through `governedCall` (RF-1). Add timeout to `governedCallRaw` (RF-2). Add `$/cancelRequest` wire-level cancellation (RF-3). Track as "Manufacturing Call Hardening" — needed before Phase 211 wires the export button.

### HIGH-3: BoardSpec persistence mismatch (Apple Elitist Rick)

The sidecar `.kicad_build_spec.json` lives in a third location neither SwiftData `Project` nor the `.kicadagent` bundle knows about. Guaranteed data divergence once a UI exists.

**Fix:** Unify BoardSpec storage — either inside the `.kicadagent` bundle or as a SwiftData entity, not as a loose sidecar file that SwiftData doesn't track.

### HIGH-4: DRC violation coordinates dropped (VisionOS Rick + Metal 4 Rick)

`vendor_drc.py` computes coordinates for every violation but DROPS them when constructing `Violation` records. The clearance check has full X,Y coords of both segments but records only `{layer, actual_gap_mm, required_mm, net_a, net_b}`.

**Fix:** Add coordinate fields to the violation items dict (ENRICH-1). Trivial 4-field addition. Benefits macOS (click-to-zoom in future board viewer), enables visionOS spatial annotations, and unlocks 3D DRC heat maps. Recommended for v7.1.

---

## MEDIUM Findings

### MEDIUM-1: AI integration missing (Foundation Models Rick)

The codebase has `KCTaskType.boardAnalysis` with routing to `AppleLocalProvider`, and the `SemanticJudge` protocol proves the integration pattern — but nothing in the manufacturing layer calls it. Vendor DRC violations are mechanically worded ("Track width 0.094mm below JLCPCB minimum 0.127mm") — accurate but unhelpful.

**Recommendation:** Add an on-device explanation pass for DRC violations in the Swift layer (not Python — preserves testability, privacy, offline operation). Mirror the `SemanticJudge` pattern. Add `KCTaskType.manufacturing` case. Phase 211+ work.

### MEDIUM-2: `include_render` is a no-op stub (Metal 4 Rick)

The `include_render` flag in `handoff.py:522-524` exists but does nothing. Build history has no visual thumbnails.

**Fix:** Wire the render call (kicad-cli pcb render → PNG thumbnail). Add `thumbnail_path` to `Build` dataclass. Low effort, high UX value.

### MEDIUM-3: SceneKit 3D inspector opportunity (Metal 4 Rick)

The handoff package already produces a STEP file. A SceneKit view can load it via ModelIO (`MDLAsset` → `SCNGeometry`) for free orbit/zoom. No custom Metal 4 mesh shaders needed — PCB is thousands of components, well within SceneKit's comfort zone.

**Recommendation:** Add `BoardInspectorView` (SceneKit) loading the STEP from `builds/handoff_{ts}/`. Seed for v7.1.

### MEDIUM-4: O(n²) clearance check is the strongest GPU-compute win (Metal 4 Rick)

`_check_clearance` in `vendor_drc.py` is embarrassingly parallel pairwise geometry — the textbook Metal compute kernel shape. The AABB pre-filter already makes typical boards fast enough, but dense BGA layers would benefit.

**Recommendation:** Seed for v7.1 with a segment-count threshold (e.g., >5000 segments → GPU path). Needs architecture decision on Python-vs-Swift GPU ownership.

### MEDIUM-5: Concurrent manufacturing exports ungated (Swift Concurrency)

Manufacturing ops are registered `is_readonly: True` and bypass the `WorkflowStateMachine`. Two concurrent `build_handoff_export` calls would race on the same `builds/` directory.

**Fix:** Either serialize via a manufacturing queue, or use unique timestamp-based directory names (already done — `handoff_{timestamp}`). Low risk but worth documenting.

### MEDIUM-6: Validation failure is a normal RPC, not an error (Swift Concurrency)

`build_handoff_export` returns `{success: false, error_message: "..."}` as a normal successful RPC, not a throw. The Mac app should handle it as a decoded value, not an error, to avoid skewing OpJournal/EscalationLadder.

**Fix:** Document this in the Swift API contract. Phase 211 wiring work.

---

## LOW Findings

| # | Specialist | Finding |
|---|-----------|---------|
| LOW-1 | Swift Concurrency | `watchdogTimeout` must stay ≥ 3× `HEARTBEAT_INTERVAL_S` — undocumented invariant |
| LOW-2 | SwiftUI | Readme preview needs GFM table pre-processing for `AttributedString(markdown:)` |
| LOW-3 | SwiftUI | 7 accessibility concerns (color-encoded swatches, tri-state labels, mm pronunciation, lazy-loading 500+ violations) |
| LOW-4 | VisionOS | BoardSpec editor mostly stays flat — only impedance requirements are spatial-native |
| LOW-5 | Foundation Models | `ManufacturerClient` ABC should NOT get AI methods — separate `VendorRecommender` is correct separation |

---

## Cross-Cutting Themes

### 1. The Python layer is done; the Swift layer doesn't exist yet
Every specialist independently arrived at this conclusion. The v7.0 Python manufacturing layer is well-architected, secure, frozen-dataclass-clean, and MCP-auto-exposed. But there is zero SwiftUI code that touches it. Phase 211 (chat → router → stream) is the natural bridge.

### 2. AI belongs in Swift, not Python
Foundation Models Rick and Architecture Rick agree: the Python manufacturing layer should stay AI-free. All AI opportunities (DRC violation explanations, vendor recommendations, readme improvements) belong in the Swift layer consuming structured MCP results. This preserves testability, privacy, and offline operation.

### 3. The `.kicadagent` bundle should own manufacturing artifacts
Apple Elitist Rick and SwiftUI Liquid Glass both identify the storage problem: BoardSpec sidecar, builds/ directory, and handoff zips all live in locations the SwiftData model and app sandbox don't know about. The `.kicadagent` document bundle (Phase 190) should be the single container.

### 4. DRC coordinates are the highest-leverage missing data
Both VisionOS Rick and Metal 4 Rick independently identified that violation coordinates are computed but dropped. This trivial fix (4 fields) benefits macOS (click-to-zoom), enables visionOS (spatial annotations), and unlocks GPU visualization (3D heat maps).

### 5. Phase 211 is the critical path
The other team's planned Phase 211 (chat → router → stream pipeline) is exactly what's needed to make the manufacturing layer accessible. A user should be able to say "prepare this board for JLCPCB" and have the chat → router → `build_handoff_export` pipeline fire. The IntentGate catalog fix (CRITICAL-1) is a prerequisite.

---

## Recommended Phase 211 Scope Additions

Based on the 6 specialist reviews, Phase 211 should include:

1. **IntentGate catalog update** — Add all 10 manufacturing ops (CRITICAL-1, ~6 lines)
2. **Daemon timeout extension** — Thread `timeout` through `governedCall` for long-running exports (HIGH-2)
3. **Codable data bridge** — `KCBoardSpec`, `KCViolation`, `KCHandoffResult` Swift DTOs (HIGH-1)
4. **Validation-as-value contract** — Document that `success: false` is a normal RPC result, not an error (MEDIUM-6)

## Recommended v7.1 Scope

1. **Manufacturing UI** — HandoffWizardView, VendorDrcResultsView, BuildHistoryView (HIGH-1)
2. **DRC violation coordinates** — Add coordinate fields to Violation items (HIGH-4)
3. **AI DRC explanations** — On-device LanguageModelSession pass for violation descriptions (MEDIUM-1)
4. **SceneKit 3D inspector** — Load STEP file for interactive board review (MEDIUM-3)
5. **Render thumbnails** — Wire `include_render` flag, add `thumbnail_path` to Build (MEDIUM-2)
6. **Sandbox hardening** — `.kicadagent` bundle owns `builds/` directory (CRITICAL-2)
7. **BoardSpec storage unification** — Move sidecar into bundle or SwiftData (HIGH-3)

## Recommended v8.0+ (Future)

1. **visionOS manufacturing review companion** — Spatial DRC annotations on 3D board (VisionOS Rick)
2. **Metal 4 GPU clearance check** — Compute kernel for dense boards (Metal 4 Rick)
3. **Vendor API adapters** — Phase 210 activated with API credentials (already deferred)

---

## Individual Review Files

| Specialist | File |
|-----------|------|
| Apple Elitist Rick | `.planning/phases/209-crossfile-mcp-integration/COUNCIL-APPLE-ELITIST-RICK.md` |
| Foundation Models Rick | `.planning/phases/209-crossfile-mcp-integration/COUNCIL-FOUNDATION-MODELS-RICK.md` |
| SwiftUI Liquid Glass | `.planning/phases/209-crossfile-mcp-integration/COUNCIL-SWIFTUI-LIQUID-GLASS.md` |
| Swift Concurrency Expert | `.planning/phases/209-crossfile-mcp-integration/COUNCIL-SWIFT-CONCURRENCY.md` |
| Metal 4 Rick | `.planning/phases/209-crossfile-mcp-integration/COUNCIL-METAL-4-RICK.md` |
| VisionOS Rick | `.planning/phases/209-crossfile-mcp-integration/COUNCIL-VISIONOS-RICK.md` |

---

**Overall Verdict:** The v7.0 Python manufacturing layer is COMPLETE and SOUND. The Apple platform integration gap is real but expected — Phase 211 is the planned bridge. The 2 CRITICALs are pre-wiring fixes (IntentGate catalog + sandbox), not regressions. APPROVE the v7.0 milestone as complete; track the follow-ups for Phase 211 and v7.1.
