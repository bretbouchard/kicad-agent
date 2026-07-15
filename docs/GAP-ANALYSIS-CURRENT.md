# volta — Current Gap Analysis

**v6.0 · 2026-07-14 · based on actual code review**

This is the **honest** gap list. It compares what the codebase says it does (per the feature inventory) against what users will ask for. Each gap has: a category, evidence (where in code the gap shows up), a proposed fix, an effort estimate, and a priority.

**Priority scale:**
- **P0** — blocks basic usefulness or App Store submission
- **P1** — blocks serious hobbyist use
- **P2** — blocks pro/specialist use
- **P3** — nice-to-have

**Effort scale:** XS (hours), S (1-2 days), M (1-2 weeks), L (1-2 months), XL (quarter)

---

## A. Shipped-but-broken gaps

Things that exist but don't work right. Fix these first — they're the worst signal for new users.

### A1. No tests for the 268-op Volta registry

| Field | Value |
|---|---|
| **Category** | Quality |
| **Evidence** | `macos-app/Tests/VoltaTests/` has no Volta op tests; `tests/ops/` covers some Python-side ops but not Swift parity |
| **Impact** | Every time we add an op, we risk breaking existing ones silently. Council reviews catch the obvious ones; regressions in routing or PCB nets only show when a user runs a real board. |
| **Fix** | Property-test every op: pick a real `.kicad_sch`, apply op, parse result, assert invariants. Use swift-snapshot-testing for IR diffs. |
| **Effort** | M |
| **Priority** | P0 |

### A2. `safe_sync_pcb_from_schematic` is a stub

| Field | Value |
|---|---|
| **Category** | Core flow |
| **Evidence** | `VoltaEngineRemaining.swift` — the op returns a placeholder message instead of doing the sync |
| **Impact** | Users CANNOT iterate. The chat generates a schematic; if they tweak a ref or value, the PCB stays stale. This kills the entire "describe → refine → ship" loop. |
| **Fix** | Either wire to the Python daemon's working implementation, or implement the diff-and-replay logic in Swift. The Python side has `update_pcb_from_schematic` and `repopulate_pcb_from_schematic` that work — call those. |
| **Effort** | S (wire to Python) / M (Swift impl) |
| **Priority** | P0 |

### A3. `fix_net_short` and `fix_pin_type_mismatches` return a message, not a fix

| Field | Value |
|---|---|
| **Category** | Validation / repair |
| **Evidence** | `VoltaEngineRemaining.swift` — both return a string message rather than performing the repair |
| **Impact** | A user with a real net short sees "this is a short" but cannot auto-fix it. They have to drop into KiCad and do it by hand. |
| **Fix** | Move the fix logic from the LLM-emitted JSON into a deterministic algorithm in Swift. The Python `fix_shorted_nets` and `fix_pin_type_mismatches` ops have working logic — port them. |
| **Effort** | M |
| **Priority** | P1 |

### A4. `SchematicPreviewView` and `PCBPreviewView` are mock-only

| Field | Value |
|---|---|
| **Category** | UI |
| **Evidence** | `InlineRendering/SchematicPreviewView.swift`, `PCBPreviewView.swift` — both render from a mock IR, not from real `.kicad_sch` / `.kicad_pcb` files |
| **Impact** | The "inline preview" feature advertised in the App Store description is non-functional for real projects. Users will discover this the first time they try to view their generated schematic in the chat. |
| **Fix** | `SwiftSVGRenderer` is real (150 LOC). Wire `SchematicPreviewView` to read a `.kicad_sch`, run the kicad-cli SVG export (or the Swift parser → SVG emitter), and display the result. Same for `PCBPreviewView` with the kicad-cli PNG export. |
| **Effort** | M |
| **Priority** | P0 (App Store claim) |

### A5. Image attachment UI not wired (Phase 196 pending)

| Field | Value |
|---|---|
| **Category** | Chat input |
| **Evidence** | `ImageAttachmentView.swift` exists; `ChatView.swift` does not include the attachment button / paste handler |
| **Impact** | Users cannot attach reference images. The model supports vision (Gemma 4 12B V2) but the UI doesn't expose it. |
| **Fix** | Add attachment button to `ChatView` compose bar; wire `NSOpenPanel` + image paste handler; call `ImageAttachmentValidator` before sending. |
| **Effort** | S |
| **Priority** | P1 |

### A6. `KiCadInstallView` is orphaned

| Field | Value |
|---|---|
| **Category** | Code hygiene |
| **Evidence** | `Views/Onboarding/KiCadInstallView.swift` exists on disk but Phase 220 removed the install path; the view is no longer referenced anywhere |
| **Impact** | Dead code; potentially confusing to new contributors; build warnings. |
| **Fix** | Delete the file. |
| **Effort** | XS |
| **Priority** | P3 |

### A7. SwiftUI view tests only cover the banner

| Field | Value |
|---|---|
| **Category** | Quality |
| **Evidence** | `macos-app/Tests/VoltaTests/ProviderBannerTests.swift` is the only view test; ~40 other views have no test coverage |
| **Impact** | Refactoring a view (e.g. Liquid Glass shell) is high-risk. Visual regressions ship. |
| **Fix** | swift-snapshot-testing for each top-level view; accessibility tests for chat; interaction tests for validation panel. |
| **Effort** | M |
| **Priority** | P1 |

### A8. Streaming chat pipeline has no end-to-end test

| Field | Value |
|---|---|
| **Category** | Quality |
| **Evidence** | `tests/` has no chat-related test; the streaming path (router → provider → ChatView → bubble render) is untested |
| **Impact** | Token timing, echo stripping, chunking, and cost callbacks all can silently break. The bug that triggered this conversation (echo at start of stream) is exactly the kind of regression this gap allows. |
| **Fix** | Integration test that runs `NoopChatStream` → `RouterStreamProvider` → `MessageBubbleView` and asserts the final rendered text matches expectations. Include a "model echoes the prompt" canned input. |
| **Effort** | S |
| **Priority** | P0 |

---

## B. Visible-but-missing gaps

Things the user reasonably expects but the app doesn't have. Fix in priority order.

### B1. Camera → schematic (vision input)

| Field | Value |
|---|---|
| **Category** | Core flow |
| **Evidence** | `Phase 236` is on the roadmap but not built. MLX vision adapter is trained. |
| **Impact** | "Snap a photo of a breadboard, get a schematic" is the killer demo for non-engineers. Without it, the value prop reduces to "KiCad with extra steps." |
| **Fix** | Add `CameraCaptureView` to `LiquidGlassShell` toolbar; route captured image to `ImageAttachment`; pass through the vision-aware provider (Gemma 4 12B V2) with a schematic-extraction prompt. |
| **Effort** | L |
| **Priority** | P0 |

### B2. Real-time multi-user collaboration

| Field | Value |
|---|---|
| **Category** | Collaboration |
| **Evidence** | `ProjectGenealogyView` and `CollaborationActivityFeed` are scaffolded; `Models/Collaboration/` types exist; no live sync engine |
| **Impact** | Two engineers cannot co-edit a board. CloudKit sync is partial. For a 2026 desktop app, this is a real gap. |
| **Fix** | NSPersistentCloudKitContainer for the SwiftData layer + CRDT-style merge for the op journal. CloudKit has good free tier; this isn't a backend-engineering problem, it's a CRDT-design problem. |
| **Effort** | XL |
| **Priority** | P2 |

### B3. Auto-routing beyond Manhattan

| Field | Value |
|---|---|
| **Category** | PCB layout |
| **Evidence** | `auto_route_manhattan` is star topology; `auto_route_freerouting` shells out to Freerouting; no A* / neural / topographical router in-process |
| **Impact** | Freerouting handles complex jobs but is slow, hard to install, and not portable. The "in-app" auto-router is OK for trivial nets only. |
| **Fix** | Port or write an A* router that respects net classes + keepouts. The Python `routing/` directory has A* code; port to Swift. Or buy a license to TopoR / AdvancedPCB and shell out. |
| **Effort** | L |
| **Priority** | P1 |

### B4. Live distributor pricing in BOM

| Field | Value |
|---|---|
| **Category** | Manufacturing |
| **Evidence** | `Phase 210` (vendor API adapters) is DEFERRED. BOM exports are static CSVs. |
| **Impact** | Users cannot answer "what will this cost me?" at JLCPCB / LCSC / Digi-Key / Mouser. Cost is the #1 question for hobbyists. |
| **Fix** | Add `distributor_pricing/` op. Pluggable provider interface; first-party adapters for JLCPCB (parts API), LCSC (EasyEDA API), Digi-Key (API requires approval). |
| **Effort** | M |
| **Priority** | P1 |

### B5. High-speed design rules

| Field | Value |
|---|---|
| **Category** | PCB layout |
| **Evidence** | No impedance calc, no length matching beyond reporting skew, no eye diagram, no SI simulation |
| **Impact** | DDR / PCIe / HDMI / SerDes users cannot use volta. We're stuck at "audio + slow digital" boards. |
| **Fix** | Calc service: trace width for target impedance (microstrip / stripline / coplanar waveguide), length matching engine that actually does the routing (not just reports skew), optional integration with Simbeor / Ansys. |
| **Effort** | XL |
| **Priority** | P2 |

### B6. Altium / Eagle / KiCad 5 / gEDA import

| Field | Value |
|---|---|
| **Category** | Interop |
| **Evidence** | Parser only handles KiCad 6+ S-expressions |
| **Impact** | Users with existing Altium / Eagle libraries cannot migrate. The prosumer segment is gated. |
| **Fix** | Altium is .NET binary; not worth implementing. Eagle is XML — feasible but heavy. KiCad 5 is old S-expr; trivial. gEDA is retired. Pick one: Eagle is highest ROI. |
| **Effort** | L (Eagle), XL (Altium) |
| **Priority** | P2 |

### B7. Settings sheet tab "Memory" and "Collaboration" are placeholders

| Field | Value |
|---|---|
| **Category** | UI |
| **Evidence** | `LiquidGlassShell.swift:684-731` defines these tab views with no real content |
| **Impact** | Users tap these and see nothing. Looks unfinished. |
| **Fix** | Either fill them with real settings (decay policy, retention, collaboration toggles) or remove the tabs. |
| **Effort** | S |
| **Priority** | P2 |

### B8. No live Swift SVGRenderer → schematic preview

| Field | Value |
|---|---|
| **Category** | Preview |
| **Evidence** | `SwiftSVGRenderer.swift` is real; `SchematicPreviewView.swift` only renders mock data |
| **Impact** | See A4. This is the same gap from the preview side. |
| **Fix** | Wire `SchematicPreviewView` to `SwiftSVGRenderer` reading from real `.kicad_sch` files via the kicad-cli SVG export or a Swift-side emitter. |
| **Effort** | M |
| **Priority** | P0 (App Store claim) |

---

## C. Test coverage gaps

### C1. SpatialHash parity test

| Field | Value |
|---|---|
| **Category** | Quality |
| **Evidence** | Phase 232 ships SpatialHash but there's no test file verifying it against kicad-cli DRC on real boards |
| **Impact** | We claim O(n log n) but unverified against ground truth. Could be silently wrong on edge cases. |
| **Fix** | Build a 100-board test corpus (corpus parity driver from Phase 234A/234B is the right pattern) and run both engines. |
| **Effort** | S |
| **Priority** | P1 |

### C2. SKIDL → KiCad round-trip test

| Field | Value |
|---|---|
| **Category** | Quality |
| **Evidence** | L1 vs L2 emitter is tested individually but not in a full round-trip: SKIDL → .kicad_sch → SKIDL and assert equality |
| **Impact** | Model emits SKIDL → we generate schematic → if we ever re-emit, the re-emit could differ. Lossy round-trip is a real risk. |
| **Fix** | Property test: pick a SKIDL script, emit KiCad, re-parse, assert equivalence under a canonicalization pass. |
| **Effort** | M |
| **Priority** | P1 |

### C3. Phase 234A/234B corpus parity not done

| Field | Value |
|---|---|
| **Category** | Validation |
| **Evidence** | Plan exists in `.planning/phases/234a-*/`, not yet executed |
| **Impact** | We don't have empirical evidence that NativeERC/NativeDRC match kicad-cli at scale. The 50/50 unit test is small-sample. |
| **Fix** | Run the plan. |
| **Effort** | M (already planned) |
| **Priority** | P0 (currently the next phase) |

---

## D. Roadmap / aspirational gaps

Things mentioned in product copy that aren't real yet, or are far off.

### D1. "Iterate on the design" loop

| Field | Value |
|---|---|
| **Category** | Core flow |
| **Evidence** | App Store description says "describe → get schematic → edit in KiCad". This implies a clean handoff but: (a) chat edits to the schematic don't sync to PCB (A2), (b) there's no way to compare versions, (c) no A/B of "what if I used a 10k vs 4.7k feedback resistor" |
| **Impact** | The handoff to KiCad is a wall, not a loop. |
| **Fix** | Phase A2 fix + add a "what-if" panel that simulates the value change in SPICE without modifying the schematic. |
| **Effort** | M |
| **Priority** | P1 |

### D2. "No learning curve" promise is over-claimed

| Field | Value |
|---|---|
| **Category** | Marketing |
| **Evidence** | App Store description says "no learning curve." But the user needs to understand: schematic vs PCB, ERC vs DRC, vendor profiles, ground pours, stitching vias. This is not "no curve." |
| **Impact** | Users hit the curve anyway and feel misled. Reviews suffer. |
| **Fix** | Tone down the copy, OR add a guided tutorial that covers these concepts in 5 minutes with the user's own project. |
| **Effort** | M (tutorial) / XS (copy) |
| **Priority** | P1 |

### D3. "Real-time cost tracking" only shows in chat footer

| Field | Value |
|---|---|
| **Category** | UX |
| **Evidence** | `KCCostLedger` exists but is only visible per-message in the chat footer; no project-level cost rollup, no budget alerts |
| **Impact** | Users don't know what they've spent until they look at the per-message numbers. |
| **Fix** | Add a "Cost" panel showing per-project, per-day, per-provider totals. |
| **Effort** | S |
| **Priority** | P2 |

### D4. No collaborative "review" of a model-emitted design

| Field | Value |
|---|---|
| **Category** | Workflow |
| **Evidence** | `review_schematic` and `critique_sch` ops exist; no UI to show the review inline; the user has to ask "review this" in chat |
| **Impact** | Low discoverability of a high-value feature. |
| **Fix** | Add a "Review" button in the validation panel that runs `review_schematic` and shows the diff inline. |
| **Effort** | S |
| **Priority** | P1 |

### D5. No version-bump / change-log for projects

| Field | Value |
|---|---|
| **Category** | Workflow |
| **Evidence** | `OpJournal` records every op but there's no "what changed in this project since last week" view |
| **Impact** | Users can't easily roll back a sequence of bad edits or summarize their work. |
| **Fix** | Add a project history view: grouped by day, with one-line summary per change. |
| **Effort** | M |
| **Priority** | P2 |

---

## E. Architecture / technical debt

Less visible to users but slows us down. Fix opportunistically.

### E1. No image data path from chat to model

| Field | Value |
|---|---|
| **Category** | Architecture |
| **Evidence** | `RouterStreamProvider.swift:118-126` — comment explicitly says "Image attachments from the chat UI are NOT yet bridged into KCAttachment here" |
| **Impact** | Even if the UI wires up attachments, the provider can't see them. |
| **Fix** | When the buildKCPrompt helper constructs the prompt, read `ImageAttachment.url` bytes and attach as `KCAttachment`. |
| **Effort** | S |
| **Priority** | P1 |

### E2. Three Swift op files, no central registry

| Field | Value |
|---|---|
| **Category** | Architecture |
| **Evidence** | `VoltaEngine.swift` (27 ops), `VoltaEngineGenerated.swift` (163), `VoltaEngineRemaining.swift` (78) — three separate enums / dispatch tables |
| **Impact** | Adding an op requires editing one of three files; risk of double-registration; no central validation of op names. |
| **Fix** | Code-generate from a single YAML manifest (the kind we used for SKIDL), produce the three enums + dispatch + tests. |
| **Effort** | M |
| **Priority** | P2 |

### E3. Python daemon is per-process, not per-project

| Field | Value |
|---|---|
| **Category** | Architecture |
| **Evidence** | One daemon handles all projects; per-project mutex is the only isolation |
| **Impact** | Large projects can starve small ones; no way to scope a daemon to a project for team / CI use. |
| **Fix** | Optional `--per-project` mode that spawns one daemon per project, with a thin supervisor. |
| **Effort** | M |
| **Priority** | P3 |

### E4. No graceful fallback when a cloud provider is rate-limited

| Field | Value |
|---|---|
| **Category** | Resilience |
| **Evidence** | `KiCadModelRouter` does fallback to a different provider on certain errors but rate-limit (429) handling is best-effort |
| **Impact** | A rate-limited Anthropic request may block a user mid-stream with a hard error. |
| **Fix** | Detect 429, exponential backoff, automatic fallback to the next provider in the chain. Show a "switched to Qwen 0.5B due to rate limit" toast. |
| **Effort** | S |
| **Priority** | P1 |

---

## F. Distribution gaps

### F1. App Store distribution requires a working Swift-only fallback for everything

| Field | Value |
|---|---|
| **Category** | Distribution |
| **Evidence** | Python daemon is allowed on macOS App Store with hardened runtime + code signing (Scripts/resign_kicad_daemon.sh), but the App Store submission guidelines discourage shipping a Python interpreter if not strictly needed. We need a "Python optional" mode. |
| **Impact** | Apple's review may push back. If we want to ship without Python, every Python-only op needs a Swift parity. |
| **Fix** | Track which ops are Swift-only vs Python-only. Add a banner in app: "X features disabled because Python daemon not installed." |
| **Effort** | S (audit) / L (parity) |
| **Priority** | P1 |

### F2. No notarized build artifact

| Field | Value |
|---|---|
| **Category** | Distribution |
| **Evidence** | No `.app.zip`, `.dmg`, or TestFlight export in the repo (search shows no build artifact) |
| **Impact** | Can't ship outside local development. |
| **Fix** | fastlane is in the stack (per memory) but not wired. Add a `fastlane/macos` lane: build, sign, notarize, dmg, TestFlight upload. |
| **Effort** | S |
| **Priority** | P0 (if we want to ship v6) |

### F3. No first-run experience

| Field | Value |
|---|---|
| **Category** | UX |
| **Evidence** | App opens to a blank project sidebar with no guidance |
| **Impact** | First-time users don't know what to do. |
| **Fix** | Onboarding: pick a starter project (LED blinker, ESP32 breakout, op-amp preamp), walk through the chat, show the result, suggest opening in KiCad. |
| **Effort** | M |
| **Priority** | P1 |

---

## G. Closing the gaps — proposed sequence

If we have one engineering quarter to close the worst gaps, the order is:

### Quarter plan (P0 + most P1)

| Week | Phase | What ships | Gaps closed |
|---|---|---|---|
| 1-2 | Test infrastructure | Volta op tests, chat pipeline E2E, view snapshots | A1, A7, A8 |
| 3 | Sync repair | `safe_sync_pcb_from_schematic` wired to Python; LLM → Python diff-and-replay | A2, D1 |
| 4 | Preview wiring | `SchematicPreviewView` + `PCBPreviewView` real IR | A4, B8 |
| 5-6 | Image path | UI attachment button + provider bridge | A5, E1 |
| 7 | Vendor pricing | JLCPCB + LCSC adapters | B4 |
| 8 | Polish | Tab removal/fill, rate-limit fallback, orphaned view delete | A6, B7, E4 |
| 9-10 | Corpus parity | Phase 234A/234B execution + report | C3 |
| 11-12 | App Store readiness | fastlane lane, notarization, first-run onboarding, "Python optional" audit | F1, F2, F3 |

### Quarter plan (stretch — P2 + P3)

| Quarter | Phase | What ships |
|---|---|---|
| Next | Camera → schematic | B1 |
| Next | Real-time collab (CloudKit) | B2 |
| Next | A* router in Swift | B3 |
| Next | Altium / Eagle interop | B6 |
| Later | High-speed design rules | B5 |
| Later | Time-travel + decision timeline (real impl) | B7 (full) |

---

## H. What we explicitly DO NOT close

These are scope decisions, not gaps. We are NOT going to do them in v6/v7.

| Gap | Reason |
|---|---|
| Altium / Cadence / Zuken parity | They're $5K+/seat tools. We're not in that market. |
| Real-time, multi-region collaboration | Engineering effort vs market demand doesn't pencil out. |
| IPC-2221 / IPC-7351 / IEC 61010 / IEC 60601 | Requires deep regulatory + standards knowledge. Prosumer/Pro tier feature. |
| Linux / Windows | All Apple Silicon focus, by deliberate decision. |
| iOS / iPadOS | Liquid Glass shell needs macOS first; tablet UI is a separate product. |
| Fully automated PCB layout (no human) | The human is the bottleneck AND the safety check. We will not ship a "press go, get a board" mode. |
| Replace Altium for the EE-at-a-company | Different product for different buyer. Out of scope. |

---

## I. Summary scorecard

| Area | Status | Coverage |
|---|---|---|
| **Schematic capture** | 🟢 | 85% of use cases |
| **Validation (ERC/DRC)** | 🟢 | Parity with kicad-cli for the checks we ship |
| **Manufacturing handoff** | 🟢 | Production-grade for 6 vendors |
| **SPICE simulation** | 🟢 | Closed-box demos work |
| **AI / inference** | 🟢 | 6 providers + local MLX + cost ledger |
| **PCB auto-routing** | 🟡 | Basic only; Freerouting fallback works |
| **Vision input** | 🔴 | Adapter trained, UI missing |
| **Real-time collaboration** | 🔴 | Scaffolded only |
| **High-speed design** | 🔴 | Not in v6 |
| **Standards compliance (IPC, IEC)** | 🔴 | Not in v6 |
| **Tests** | 🟡 | Python 84% core, Swift sparse, ops untested |
| **Distribution** | 🔴 | Not notarized, no App Store build yet |
| **Onboarding** | 🔴 | No first-run experience |
| **Pricing intel** | 🟡 | Deferred (Phase 210) |

**Overall v6 posture:** Strong on schematic + validation + handoff. Weak on PCB layout, vision, and distribution. The big wins for v7 are: A1-A8 (quality), B1 (vision), and F2-F3 (ship to App Store).
