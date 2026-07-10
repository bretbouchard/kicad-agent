---
phase: 173-gsd-conversation-engine
plan: 01
status: complete
shipped_at: 2026-07-08
---

# Phase 173 — GSD Conversation Engine: Summary

## What Shipped

| File | Role | LOC |
|------|------|-----|
| `Views/GSDConversation/GSDModels.swift` | ProjectSpec, ProjectRoadmap, RoadmapPhase, CompletionSummary, ExportArtifact, SpecValidator, ForkLimiter | 200 |
| `Views/GSDConversation/QuestioningView.swift` | 3-question clarifying flow, validation, defaults skip | 115 |
| `Views/GSDConversation/SpecView.swift` | Editable DisclosureGroup spec card with all fields | 145 |
| `Views/GSDConversation/RoadmapView.swift` | Horizontal timeline with phase nodes + detail sheet | 140 |
| `Views/GSDConversation/ExecuteView.swift` | PipelineStatusView embed + control row + failure banner | 80 |
| `Views/GSDConversation/VerifyView.swift` | Completion summary with renders/exports/decisions/duration | 125 |
| `Models/Conversation.swift` | Extended with parentConversationId, forkedFromMessageId, makeFork() | +35 |
| `Tests/GSDConversationEngineTests.swift` | 16 tests: sanitization, fork limits, duration, 5 views, conversation fork | 215 |

## Requirements Closed

- **GSD-01** — Questioning phase (clarifying questions)
- **GSD-02** — Spec phase (editable card)
- **GSD-03** — Roadmap phase (timeline visualization)
- **GSD-04** — Execute phase (live progress)
- **GSD-08** — Verify phase (completion summary)
- **CHAT-08** — Conversation forking (edit + re-submit)
- **GEN-01** — Generative pipeline entry point

## Threat Mitigations

- **T-173-01** (Spoofing — LLM-generated spec): SpecValidator.sanitize() strips script tags + event handlers. Length cap 1000 chars.
- **T-173-02** (Tampering — user-edited spec): length validation on every binding write; rejected writes don't update spec.
- **T-173-03** (Info Disclosure — Decision events): accepted, local-only SwiftData.
- **T-173-04** (DoS — fork spam): ForkLimiter enforces 100-fork cap per conversation with 80-fork warning threshold.

## Test Results

- 16 new tests, all passing
- Full suite: 212/213

## Architectural Decisions

1. **Value types for GSD models** — ProjectSpec, RoadmapPhase are value types (structs). The SwiftData @Model layer (Project, Conversation, Decision) stays separate. This keeps view-layer testable without SwiftData container setup.

2. **Defaults skip path** — `ProjectSpec.defaultSpec` and `ProjectRoadmap.defaultRoadmap` provide a one-click "skip questioning" path that's still safe and structured.

3. **Conversation fork via parentConversationId** — not full event-sourced yet (Phase 180 lands that). For now, fork creates a new Conversation with `parentConversationId` set; the new conversation re-appends messages up to the fork point in Phase 175.

4. **No LLM wired yet** — views take closures for `onApprove`/`onRefine`/`onUseDefaults`. Phase 175 chat interface wires these to ProviderRouter. View-model separation enables tests to pass without daemon.

5. **Spec sanitization in two places** — sanitize-on-write (bindings) and sanitize-on-display (defensive). Belt + suspenders for XSS.

## What's Next

- **Phase 174** — Approval Gates UI surfaces GSD transitions as user decisions
- **Phase 175** — Chat Interface wires QuestioningView/SpecView/RoadmapView to LLM via ProviderRouter
