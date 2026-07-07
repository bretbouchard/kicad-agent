# kicad-agent

## What This Is

A full-stack KiCad automation agent — a GSD Skill backed by a Python library that enables AI-safe, structural editing of KiCad schematic, PCB, symbol library, and footprint library files. Works across any KiCad 10+ project.

The LLM never touches raw S-expressions. It emits structured intents (JSON operations), and the Python tool layer mutates the AST, serializes valid KiCad files, and validates via ERC/DRC gates.

## Core Value

**LLM → intent JSON → AST mutation → valid KiCad file.** Zero corruption, every time.

If the AI can't produce structurally valid KiCad files through the tool layer, nothing else matters.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Parse all KiCad 10+ file types (.kicad_sch, .kicad_pcb, .kicad_sym, .kicad_mod) into structured AST
- [ ] Component operations: duplicate, replicate, array components/sections
- [ ] Net operations: add/remove/reroute nets, bus operations
- [ ] Footprint management: assign, swap, validate footprints
- [ ] Reference management: renumber, validate, cross-reference checks
- [ ] ERC/DRC validation gates via kicad-cli after every edit
- [ ] Integrity checks: UUID integrity, symbol existence verification
- [ ] Net consistency: verify netlist consistency between schematic and PCB
- [ ] Structural diffs: syntax-aware diffs for S-expressions
- [ ] Round-trip fidelity: parse → modify → serialize produces valid KiCad files
- [ ] GSD Skill integration: invoke from any KiCad project via /kicad-agent
- [ ] Operation schema: well-defined JSON operation format for AI-to-tool communication

### Out of Scope

- KiCad 8.x/9.x backward compatibility — targeting 10+ only
- Direct GUI/editor integration — CLI and skill interface only
- Auto-routing — routing-rick agent handles that separately
- Simulation/SPICE integration — separate concern
- 3D model manipulation — out of scope for v1

## Context

- KiCad files are structured S-expressions with deep nesting, ordering constraints, fragile UUID/symbol references, and implicit electrical relationships
- Generic LLMs fail on KiCad files because: parentheses nesting is deep, ordering matters, UUIDs/symbol references are fragile, tiny syntax mistakes corrupt the file, semantic relationships are implicit, diffs become noisy
- The fix is constrained structural editing — the LLM emits operations, never raw text
- This tool integrates with the existing GSD/AI stack (Council of Ricks, kicad-rick agent, etc.)
- Existing tools: kiutils (Python), sexpdata (Python), kicad-cli for validation, difftastic for diffs
- The tool lives at ~/apps/kicad-agent/ (Python backend) with a skill definition at ~/.claude/skills/kicad-agent/

## Current Milestone: v4.1 Stage-Safe PCB Flow

**Goal:** Enforce a credible schematic-to-manufacturing PCB workflow where each stage has deterministic readiness gates, explicit constraints, and verified artifacts. 10 phases (85-94), 14 plans.

**What this adds:**
- Unified gate architecture: DesignStage enum, GateResult model, GateRunner orchestrator
- Schematic intent completeness gate: footprint, pin-map, metadata, net intent checks
- Verified schematic-to-PCB transfer contract: symbols → footprints → pads → nets
- Constraint capture and propagation: electrical, mechanical, fab constraints → .kicad_dru
- Placement readiness gate: bounds, clearance, decoupling, thermal, routability
- Routing readiness and quality gate: prerequisites, post-route DRC, diff pair rules
- Manufacturing readiness gate: DRC/DFM pass, artifact validation, manifest with hashes
- AI boundary and repair loop: proposals validated before application, audit trail
- 6 golden end-to-end boards proving full flow
- Documentation: stage-gate getting started, repair examples, guarantees vs suggestions
- Phase 95: Dual Knowledge Base Integration — Cognee ingestion + section injection for local model prompts (73 tests)
- Phase 99: Freerouting Integration Hardening — NativeBoard-backed DSN generator (R-1 courtyards, R-2 net classes, R-3 zones, R-4 stackup vias, R-5 snap_angle, R-6 SES multilayer bridge, R-7 comment sweep). SC-3 DRC PASS, SC-4 baseline on 3 fixtures, SC-5 xfail (Freerouting v2.2.4 ignores snap_angle in batch). 52 tests, Council APPROVE Round 4.

**Previous:** v3.0 Full-Stack EDA shipped 2026-06-01. All 54 phases across 10 milestones complete.

## Current State

**Shipped:** v2.2 Complete-Ops (2026-06-26)

Complete routing stack production-ready:
- **Phase 99** Freerouting Integration Hardening — NativeBoard-backed DSN, courtyard obstacles, net classes, zones, via padstacks, SES multi-layer bridge. SC-3 DRC PASS.
- **Phase 100** RoutingOrchestrator + Human Approval Loop — Intelligent dispatch (A* vs Freerouting), JSONL audit trail, UUID-based rollback. Closed CR-01 immutability refactor (14 frozen dataclasses).
- **Phase 98** AI Routing Strategy Advisor — Gemma 4 12B V2 vision LoRA via RoutingStrategy Protocol. StrategyValidator + R-6 graceful fallback. Real model verified.
- **Phase 101** Schematic Ops Bug Fixes — 5 P0/P1 bugs closed for analog-ecosystem backplane cleanup (update_symbols crash, place_missing_units collision, erc_auto_fix data loss, place_no_connects positions, remove_dangling_wires criteria).

**Stats:** 4 phases, 12 plans, 138 commits, 145 files changed, 29K+ insertions, 270+ tests added, 280+ green. All 4 Council exec reviews APPROVED. 18 follow-up findings resolved.

**Next milestone:** TBD via `/gsd-new-milestone`

## Previous Milestone: v2.3 mcp-server

**Goal:** Expose all 57 kicad-agent operations as MCP tools so any AI agent (Claude, Cursor, etc.) can invoke KiCad file edits directly.

**What exists:** Component-search MCP server (4 tools, stdio transport) — only covers JLCPCB search, not file editing.

**Target features:**
- New MCP server exposing execute/analyze/status as tools
- Dynamic tool generation from the 57-operation Pydantic schema
- Project resources (ERC/DRC results, board analysis) as MCP resources
- stdio transport, registered as CLI entry point
- Schema discovery tool for dynamic operation introspection

## Constraints

- **Tech Stack**: Python 3.11+, kiutils, sexpdata, networkx for graph analysis — **Why: KiCad-native parsing, not regex hacks
- **KiCad Version**: 10+ only — **Why**: Current production version, no backward compat burden
- **AI Interface**: JSON operation schema, never raw text — **Why**: Prevents file corruption
- **Validation**: Every edit must pass ERC/DRC before commit — **Why**: Catch errors before they compound
- **Architecture**: LLM → intent → AST mutation → serializer → validated file — **Why**: Deterministic, diffable, testable, repairable

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| GSD Skill + Python backend | Integrates with existing stack, Python has best KiCad library ecosystem | — Pending |
| kiutils as primary parser | KiCad-specific AST manipulation, not generic S-expression | — Pending |
| Operation/intent JSON schema | LLM never touches raw files, structural safety | — Pending |
| kicad-cli for validation | Official KiCad validation, not reimplemented checks | — Pending |
| difftastic for diffs | Syntax-aware, handles deeply nested parens well | — Pending |
| Full stack in v1 | All file types, all ops, all validation layers | — Pending |
| KnowledgeManager uses H2 section chunking | KiCad docs have natural header hierarchy; H2 = top-level sections | Valid |
| CORE_RULES injected unsanitized | Project-authored rules are trusted; only external doc content sanitized | Valid |
| Two-tier token budget (800 per-section + 2000 combined) | Prevents any single doc section from dominating the prompt while allowing multi-section coverage | Valid |
| Cognee ingestion as standalone script | Separation of concerns: ingestion is infra, KnowledgeManager is runtime | Valid |
| Thread-safe singleton for KnowledgeManager | InferenceWrapper uses ThreadPoolExecutor; concurrent access requires locking | Valid |


## Previous Milestone: v5.0 Skidl-Native Design Pipeline (Absorbed into v6.0)

**Goal:** Build a bidirectional KiCad↔SKIDL bridge, floor planner, SPICE simulation pipeline, and AI training data generator. Enables: natural language → circuit → simulation → floor plan → PCB → routing → manufacturing.

**Status (2026-07-07):** Roadmap defined (Phases 156-160), but unshipped. Absorbed into v6.0 as inputs to the generative transform pipeline. SKIDL becomes the canonical IR consumed by the v6.0 Mac app's conversation-coupled generative layer. SKIDL/SPICE/training work continues but as part of v6.0's Track F (Generative).

**What this adds (now feeds v6.0):**
- SKIDL converter (read any .kicad_sch → Python code, and back) — consumed by v6.0 generative pipeline
- Floor planning (placement spec → zoned PCB, not blind placement) — inputs to v6.0 PCB generation
- SPICE validation (ngspice simulation as circuit quality gate) — quality gate in v6.0 verification loop
- Training data generation (SKIDL + NL pairs from 71K repos) — fine-tunes for v6.0 MLXProvider
- Natural-language circuit generation (LLM → SKIDL → KiCad) — v6.0 GSD Conversation Engine consumes this

**Target phases:** 156-160 (continues from analog-ecosystem numbering for cross-repo clarity)

**Key decisions:**
- SKIDL is the intermediate representation for all circuit operations (validated by Microsoft SchGen paper)
- Two-model architecture: Qwen text model for circuit generation, Gemma vision model for routing
- SPICE results as reward signal for AI training (not just DRC pass/fail)
- Floor planner encodes engineering knowledge (signal flow zones, decoupling proximity, power isolation)
- Full pipeline advantage: SchGen/pcbGPT stop at schematic, we go to manufacturing

**Dependencies:**
- Phases 108-111 (autolayout + conventions) provide the schematic generation foundation
- Analog-ecosystem boards (mono blade, base board, ADSR, etc.) are the proving ground
- jlcparts database (5GB) provides manufacturing-ready part numbers

## Current Milestone: v6.0 KiCad Agent — The Closed Box

**Goal:** Ship a native Mac+iPhone app that delivers closed-box conversational hardware design — user types intent, app does the rest, with generative schematics/PCBs coupled to conversation state, event-sourced memory with project genealogy, Apple-native real-time collaboration, zero infrastructure, and militant 100% test coverage.

**What this adds (8 tracks, 42 phases, ~25-26 weeks):**

- **Track A — Foundation:** macOS 26+ SwiftUI app shell (Liquid Glass), bundled Python daemon (PyInstaller subprocess), bundled kicad-cli + minimal libs
- **Track B — Models:** `KiCadModelProvider` protocol wrapping Swift AI SDK + FoundationModels + MLX-Swift. BYOK with Keychain storage. Provider router (task-aware, cost-aware, privacy-aware). HF Hub model downloads (zero dev infra).
- **Track C — Governance:** stdio MCP daemon (no HTTP by default), Python daemon exposes 142+ ops as MCP tools, Obdurate Runtime wraps executor (state machine, op journal, verification gates, escalation ladder, four-state resolution).
- **Track D — UI Surfaces:** inline schematic (SVG) / PCB (PNG) rendering, live pipeline view, GSD Conversation Engine (questioning → spec → roadmap → execute → verify, all visual), approval gates UI.
- **Track E — Memory:** SwiftData + CloudKit (auto-sync Mac↔iPhone), event-sourced decisions/values, Decision Timeline UI, time-travel (snapshot any point, scrub, diff, restore), run-on conversations with chapter segmentation.
- **Track F — Generative:** Conversation state IS source of truth. `.kicad_sch` and `.kicad_pcb` are derived artifacts (regenerable from journal). Hash-based gold master tests on generation. Couples v5.0 SKIDL/SPICE/training work into runtime.
- **Track G — Collaboration:** Project genealogy (family tree, branches, false starts, snapshots), `.kicadagent` iCloud Drive bundle, CKShare for collaborator invitations, Group Activities v1 (live sessions, 4-participant cap).
- **Track H — Quality:** swift-testing framework, SwiftCheck property-based testing, 4-variant snapshot tests per view (light/dark/XXXL/high-contrast), mull-xcode mutation testing (>90% score), a11y by default (SwiftLint custom rules), 100% line+branch coverage enforced in CI gate, gold master on generative outputs.

**Key decisions (locked 2026-07-07):**
- **macOS 26+ required** (FoundationModels dependency, clean break)
- **Daemon: app-spawned subprocess** (not LaunchAgent)
- **stdio MCP** for in-app daemon (no HTTP by default); HTTP MCP opt-in for external clients (Claude Code, Cursor)
- **MLX-Swift direct** (in-process, Metal-accelerated, no mlx-server)
- **Bundle FoundationModels default** (free, built-in); HF Hub for power-user fine-tunes (zero infra)
- **iCloud Keychain sync: on by default** (opt-out); device-local fallback always available
- **External HTTP MCP: off by default** (opt-in)
- **Files: iCloud Drive** (`.kicadagent` bundle document type)
- **Default collaborator permission: view** (user explicitly upgrades)
- **Conflict resolution: LWW with prompts** for value changes
- **Forked projects: include full conversation history**
- **Group Activities: v1, 4-participant cap** (raise later if needed)
- **Snapshots: hybrid** (auto on decisions, manual anytime)
- **Pure BYOK** — no proxy, no developer AI bill liability
- **Generative source of truth** — conversation state IS source, KiCad files are derived (compiler model: source vs binary)
- **Militant testing** — swift-testing, 100% line+branch, 4 snapshot variants, hash gold master, mutation >90%, pytest+100%+mutation on Python daemon
- **Mac+iPhone SLC v1** — Windows/web deferred to v7+

**Target phases:** 161-202 (continues from v5.0 phase 160)

**Critical path:** Foundation (A) → Models (B) → Governance (C) → UI Surfaces (D) → Memory (E) → Generative (F) → Collaboration (G). Quality (H) runs parallel from phase 0.

**Biggest risks:** Track E (event-sourced memory + time-travel) and Track F (generative transform correctness). Both are differentiators — if they fail, the app is just another chat UI.

**Dependencies:**
- Existing kicad-agent Python library (142 ops) — bundled as daemon
- Existing Obdurate Runtime design (extending `routing/audit.py` app-wide)
- v5.0 SKIDL/SPICE/training work — feeds Track F generative pipeline
- Existing routing stack (Phases 98-101) — exposed via MCP tools
- Apple ecosystem: FoundationModels, CloudKit, CKShare, Group Activities, iCloud Drive, MLX-Swift, Swift AI SDK

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-07-07 — v6.0 KiCad Agent — The Closed Box milestone started. v5.0 Skidl-Native absorbed as Track F inputs.*
