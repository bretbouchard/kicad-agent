# Foundation Models Rick — Manufacturing Layer AI Review

**Phase:** 209 (v7.0 Vendor-Neutral Manufacturing Layer)
**Reviewer:** Foundation Models Rick (Tier 2, Gamma wave)
**Reviewed:** 2026-07-11
**Scope:** On-device AI / Foundation Models integration opportunities in the manufacturing layer

---

## Verdict: The manufacturing layer ships ZERO AI, and that is a missed opportunity — but not a blocking one.

The v7.0 manufacturing layer is a deterministic, well-architected, Python-side system. BoardSpec, Build, vendor DRC, handoff export — all correct, all pure-Python, all verifiable. There is nothing *broken* from a Foundation Models perspective because there is nothing *present*. The question is what is **possible** and what the existing infrastructure already half-supports.

The critical finding: **the Swift app already has the AI scaffolding designed for exactly this use case, but the Python manufacturing layer never calls it.** `KCTaskType.boardAnalysis` exists with the description "Explaining ERC/DRC findings, BOM summaries" and routes to `AppleLocalProvider`. The `SemanticJudge` protocol proves the pattern for LLM-judgment-on-deterministic-results. Neither is wired to the manufacturing layer.

---

## 1. Could the manufacturing layer benefit from on-device AI? YES — five concrete wins.

The on-device model (`SystemLanguageModel.default`, ~3B params, Neural Engine, 0.6ms TTFT) is purpose-built for the kind of short-form classification, summarization, and explanation that the manufacturing layer needs. Every candidate below is **on-device, free, private, offline-capable** — no cloud, no API keys, no quota.

| Use case | Model | Why on-device | Estimated tokens |
|---|---|---|---|
| Vendor DRC violation explanation | `SystemLanguageModel.default` | Board geometry is proprietary; violations are short structured data | ~200 in / ~150 out |
| AI-enhanced handoff readme | `SystemLanguageModel(useCase: .contentTagging)` | Board specs are user data; readme is short-form generation | ~400 in / ~300 out |
| Vendor recommendation from BoardSpec | `SystemLanguageModel.default` | BoardSpec is a small structured object; recommendation is classification | ~150 in / ~100 out |
| BOM supply-chain risk flag | `SystemLanguageModel.default` | BOM rows are structured; risk tagging is classification | scales with BOM size |
| Build diff narrative | `SystemLanguageModel.default` | BuildDiff is a small structured diff; narrative is summarization | ~200 in / ~100 out |

None of these require the server model (`PrivateCloudComputeLanguageModel`). They are all short-form, low-latency, classification/explanation tasks — exactly what the on-device model is for. The architecture decision guide in my profile maps every one of these to `SystemLanguageModel`.

---

## 2. Is the handoff readme a candidate for @Generable? YES — but with a boundary.

The current `_generate_readme` (`handoff.py:123-246`) is 120 lines of f-string interpolation producing static markdown. It is correct and deterministic, but it produces identical readmes for identical inputs — no board-specific manufacturing guidance, no vendor-specific advice, no interpretation of the validation results.

**@Generable candidate — an "AI readme section" struct:**

```swift
@Generable
struct AIHandoffNotes {
    @Guide(description: "One-paragraph board summary for the fab house")
    var boardSummary: String

    @Guide(description: "Manufacturing notes specific to this board's specs and vendor")
    var manufacturingNotes: [String]

    @Guide(description: "Suggested fabrication stackup given layer count and impedance requirements")
    var suggestedStackup: String

    @Guide(description: "Risk callouts — anything the fab house should watch for", .count(0...5))
    var riskCallouts: [String]
}
```

This is a flat struct (higher model compliance than nested types), uses `@Guide` hints on every field, and constrains the array length. The model returns typed Swift — no JSON parsing, no malformed-output risk.

**Critical boundary:** The AI section should be an *addendum* to the deterministic readme, not a replacement. The current `_generate_readme` produces the ground-truth spec table, validation results, and artifacts table. Those MUST stay deterministic (they are the legal/provenance record). The AI section is appended below — clearly labeled "AI-Generated Notes" — and is advisory, not authoritative. TM-4 (readme is data, not executable) still holds.

**The data flow:** Python `export_handoff` runs as-is → produces `HandoffResult` → Swift app receives it via MCP → Swift constructs an `AIHandoffNotes` via `LanguageModelSession.respond(schema:)` → appends to the readme before final display/save. The Python side stays deterministic and AI-free; the Swift side adds intelligence.

---

## 3. Could the vendor DRC evaluator use Foundation Models to explain violations? YES — this is the biggest single win.

`vendor_drc.py` produces `Violation` dataclasses with mechanically-generated descriptions:

```python
f"Track width {width}mm below {profile.name} minimum {limit}mm"
```

This is accurate but unhelpful. A fab engineer reading "Track width 0.094mm below JLCPCB minimum 0.127mm" knows *what* failed but not *why it matters* or *how to fix it*. An on-device LLM turn that structured violation into a natural-language explanation is the textbook use case for `boardAnalysis`.

**This is already architected — it's just not connected.** `KCTaskType.boardAnalysis` exists with `roleDescription: "Explaining ERC/DRC findings, BOM summaries."` and routes to `AppleLocalProvider`. The `SemanticJudge` protocol in `PostOpGate.swift:72` proves the exact pattern: a minimal `Sendable` protocol that takes structured results and returns an LLM judgment.

**Concrete proposal — a `DRCExplainer` protocol mirroring `SemanticJudge`:**

```swift
protocol DRCExplainer: Sendable {
    /// Explain a list of vendor DRC violations in natural language.
    /// Returns nil if the model is unavailable or the explanation is indeterminate.
    func explain(violations: [KCViolation], vendor: String) async -> String?
}
```

The implementation calls `LanguageModelSession` with the violations serialized as a prompt and returns a paragraph. The on-device model handles this in ~150 output tokens — sub-second on the Neural Engine.

**IMPORTANT — do NOT let the LLM gate the handoff.** The deterministic `run_vendor_drc` decides pass/fail. The LLM only explains. This mirrors the existing `PostOpGate` architecture: deterministic check gates, semantic check advises. The `VendorDrcResult.passed` field stays the source of truth; the LLM explanation is display-only.

---

## 4. Should the ManufacturerClient ABC have an AI-powered "recommend vendor" method? YES — but not on the ABC itself.

The current `ManufacturerClient` (`manufacturer_client.py:83-105`) is a clean ABC: `quote`, `place_order`, `get_status`. Adding `recommend_vendor` to the ABC would force every future adapter (PCBWay, MacroFab, JLCPCB) to implement an AI method — wrong. A vendor adapter talks to a vendor API; it does not recommend itself.

**Correct architecture — a separate `VendorRecommender` that consumes the ABC's outputs:**

```swift
@Generable
struct VendorRecommendation {
    @Guide(description: "Recommended vendor key from the available profiles")
    var vendor: String

    @Guide(description: "Confidence in this recommendation, 0.0 to 1.0", .range(0.0...1.0))
    var confidence: Double

    @Guide(description: "Why this vendor fits this board", .count(1...4))
    var reasons: [String]

    @Guide(description: "What might disqualify this vendor for this board")
    var caveats: String
}
```

The recommender takes a `BoardSpec` + `board_stats` + the list of available `ManufacturerProfile` limits, and returns a `VendorRecommendation`. This is on-device classification: the board specs are small structured data, the vendor capabilities are small structured data, and the output is a typed struct. The on-device model sees the board (private, proprietary) and the public vendor specs — no data leaves the device.

**Why this matters:** The current flow requires the user to know which vendor to pick (`--vendor jlcpcb`). An AI recommender could auto-suggest: "Your 0.094mm traces are below JLCPCB's 0.127mm minimum but above PCBWay's 0.1mm — PCBWay is recommended, or widen traces to 0.127mm for JLCPCB." That is a real design decision that the deterministic layer cannot make because it requires comparing the board against ALL vendor profiles and reasoning about trade-offs.

**The `list_vendor_drc_profiles` op already returns the data** (`VendorDrcProfileInfo` with all numeric limits). The recommender just needs to consume that plus the `BoardSpec`.

---

## 5. How would a LanguageModelSession Tool wrapping build_handoff_export look?

The goal: let the conversational agent in the Swift app trigger a manufacturing handoff via natural language ("export the handoff package for JLCPCB") by exposing `build_handoff_export` as a `Tool` the model can call.

**Tool implementation:**

```swift
import FoundationModels

struct ExportHandoffTool: Tool {
    let name = "exportManufacturingHandoff"
    let description = "Export a complete manufacturer handoff zip from a KiCad PCB"

    @Generable
    struct Arguments {
        @Guide(description: "Absolute path to the .kicad_pcb file")
        let pcbPath: String

        @Guide(description: "Vendor key: jlcpcb, pcbway, oshpark, etc. Omit for generic.")
        let vendor: String?

        @Guide(description: "Include STEP 3D model (default true)")
        let includeStep: Bool?

        @Guide(description: "Skip DRC/ERC validation gate (default false)")
        let skipValidation: Bool?
    }

    nonisolated func call(arguments: Arguments) async throws -> String {
        // Build the MCP op dict and send via MCPClient.governedCall
        let op: [String: Any] = [
            "op": "build_handoff_export",
            "target_file": arguments.pcbPath,
            "vendor": arguments.vendor ?? "",
            "include_step": arguments.includeStep ?? true,
            "skip_validation": arguments.skipValidation ?? false
        ]
        let result = try await mcpClient.call(op: op)
        // Return a compact summary for the model — not the full manifest
        return "Handoff \(result.success ? "succeeded" : "failed"): "
             + "zip=\(result.zip_path), "
             + "drc=\(result.validation.drc_passed ?? "n/a"), "
             + "vendor_drc=\(result.validation.vendor_drc_passed ?? "n/a")"
    }
}
```

**Session wiring:**

```swift
let session = LanguageModelSession(
    model: SystemLanguageModel.default,
    tools: [ExportHandoffTool(mcpClient: client)],
    instructions: """
    You help with PCB manufacturing. Use exportManufacturingHandoff to produce
    handoff packages. Explain the validation results after export.
    """
)
```

**Key points from my checklist:**
- The tool has a short `description` (single phrase, not a paragraph) — saves context tokens.
- `Arguments` uses `@Generable` with `@Guide` hints on every field.
- The tool is `Sendable` (struct, `nonisolated func`).
- The return is a compact string summary, not the full manifest JSON — the model doesn't need 200 lines of artifact hashes.
- Only ONE tool here — the `ExportHandoffTool`. Do not bundle `build_create`, `build_list`, `build_show`, `drc_vendor` into the same session. That is 5 tools eating context. Split across sessions: one for export actions, one for query actions.

**Governance integration:** The tool should go through `MCPClient.governedCall` (Phase 169-170), not raw `MCPClient.call`. The IntentGate, DriftDetector, and WorkflowStateMachine must validate the op even when the model initiates it. An AI-triggered handoff is still a governed call.

---

## 6. Missed opportunities for Foundation Models integration

Beyond the four above, here are the gaps I see:

### 6a. BOM supply-chain analysis (MEDIUM priority)
`export_bom_profile` produces a BOM but nobody analyzes it. An on-device pass could flag: parts with single-source risk, parts near end-of-life, parts with long lead times. The BOM rows are structured data; risk tagging is classification. This routes to `boardAnalysis` → `AppleLocalProvider`. **Note:** real-time part availability requires network/cloud — keep that out of the on-device pass. The on-device pass is "given the BOM, which parts *look* risky based on component type/value heuristics."

### 6b. Build diff narrative (LOW priority)
`diff_builds` (`build.py:187-206`) returns a `BuildDiff` struct (files added/removed, status changed, git_sha_changed). It is machine-readable but not human-readable. An on-device summarization pass could produce: "Build B added 2 source files and advanced from DRAFT to VALIDATED. Git HEAD moved forward 3 commits." This is a `quickReply` task — sub-100-token generation. Low value but nearly free.

### 6c. DRC profile selection assistant (MEDIUM priority)
The `list_vendor_drc_profiles` op returns 10 profiles with numeric limits. A user staring at this list has to manually compare their board against each. An on-device assistant could take the board stats + specs and rank the profiles by compatibility. This is the same data as the vendor recommender (§4) but presented as a ranked list rather than a single pick.

### 6d. Pre-handoff validation explainer (HIGH priority — the flip side of §3)
When `export_handoff` fails validation (`HandoffResult.success == False`), the `error_message` is a terse string: `"pre-handoff validation failed: DRC, vendor DRC"`. An on-device explanation pass could turn this into: "Your board has 3 DRC violations and 7 vendor-specific violations for JLCPCB. The vendor violations are mostly track-width related — widen traces to at least 0.127mm or switch to PCBWay (0.1mm minimum). See the violation list for details." This is the same `DRCExplainer` from §3, just called on the failure path instead of the success path.

### 6e. Missing: no `KCTaskType.manufacturing` task type
The `KCTaskType` enum (`KCTask.swift:69-166`) has 10 cases — `quickReply`, `complexReasoning`, `vision`, `privacySensitive`, `circuitGeneration`, `pcbRouting`, `boardAnalysis`, `conversationHistory`, `circuitTheory`, `spiceSimulation`. **There is no `manufacturing` case.** Manufacturing AI tasks currently map to `boardAnalysis` (which routes to AppleLocal — correct), but a dedicated `manufacturing` case would let users set a distinct provider preference for manufacturing queries (e.g., route to MLX if they have a manufacturing-fine-tuned adapter). This is a one-enum-case addition with a `displayName` and `roleDescription`.

---

## Architecture Recommendation: Where the AI lives

The manufacturing layer is Python (daemon). The AI layer is Swift (app). **The Python side should stay AI-free.** Every AI opportunity above belongs in the Swift app, consuming the structured results the Python daemon returns via MCP. This preserves:

1. **Testability** — Python tests stay deterministic, no LLM mocking needed.
2. **Privacy** — Board specs and geometry never leave the device for cloud; on-device model sees them locally.
3. **Offline operation** — The Python daemon works offline; the AI layer adds intelligence when Apple Intelligence is available, degrades gracefully when not (via `SystemLanguageModel.availability`).
4. **The existing `SemanticJudge` pattern** — The proven integration shape is "Python does deterministic work, Swift protocol abstracts the LLM judgment." Manufacturing AI should follow this exact pattern.

The `SemanticJudge` protocol (`PostOpGate.swift:72`) is the template. A `DRCExplainer`, `VendorRecommender`, or `HandoffNotesGenerator` protocol mirroring that shape — `Sendable`, minimal method signature, `NoXxx` default that returns nil — is the correct architecture for every opportunity above.

---

## What is NOT a Foundation Models job

To be clear about boundaries:

- **Picking the pass/fail result** — `VendorDrcResult.passed` is deterministic. The LLM never decides this.
- **Generating artifact hashes** — SHA256 is a hash function, not a language model.
- **File path resolution / traversal checks** — Pure Python logic (TM-1 through TM-6).
- **Zip creation** — `zipfile.ZipFile`, not a model.
- **Vendor API calls** — `ManufacturerClient.quote/place_order/get_status` are HTTP, not LLM.

The LLM's job in the manufacturing layer is **explanation, recommendation, and narrative** — turning structured machine output into human-actionable guidance. Nothing more.

---

## Summary Table

| Opportunity | Priority | Model | Existing infra | Effort |
|---|---|---|---|---|
| Vendor DRC violation explanation (§3) | HIGH | On-device | `boardAnalysis` task type + `SemanticJudge` pattern exist | Medium — new `DRCExplainer` protocol + wiring |
| Pre-handoff failure explainer (§6d) | HIGH | On-device | Same as §3 | Low — reuse `DRCExplainer` on failure path |
| Vendor recommendation (§4) | HIGH | On-device | `list_vendor_drc_profiles` returns the data | Medium — new `VendorRecommender` + `@Generable` struct |
| Handoff readme AI notes (§2) | MEDIUM | On-device (.contentTagging) | `_generate_readme` produces the base | Medium — new `@Generable` struct + appends section |
| BOM supply-chain flag (§6a) | MEDIUM | On-device | BOM export exists | Medium — new analysis pass |
| Tool wrapping build_handoff_export (§5) | MEDIUM | On-device | MCP op exists, `governedCall` exists | Low-Medium — one `Tool` struct |
| `KCTaskType.manufacturing` case (§6e) | LOW | N/A (enum only) | `KCTaskType` enum | Trivial — one enum case |
| Build diff narrative (§6b) | LOW | On-device | `diff_builds` exists | Low — summarization pass |
| DRC profile ranking (§6c) | LOW | On-device | `list_drc_profiles` returns data | Low — reuse vendor recommender logic |

**Bottom line:** The v7.0 manufacturing layer is a solid deterministic foundation. The v7.1 (or a parallel AI-integration phase) should layer Foundation Models on top via the Swift app, following the existing `SemanticJudge` pattern. The single highest-value addition is a `DRCExplainer` protocol that turns `VendorDrcResult.violations` into natural-language guidance — the infrastructure for it (`boardAnalysis` task type, on-device routing, `SemanticJudge` precedent) already exists.
