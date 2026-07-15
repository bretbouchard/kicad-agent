---
phase: 247
type: context
status: pending-planning
gathered: 2026-07-15
source: manual
---

# Phase 247 Context — Gap closure against docs/GAP-ANALYSIS-CURRENT.md

## Phase Boundary

Triage all open gaps in `docs/GAP-ANALYSIS-CURRENT.md`, apply the four-state
resolution taxonomy to each, and either implement, add-as-phase, supersede, or
defer with a named target. No silent dismissal.

## Locked Decisions (preliminary)

- **Source of gaps**: `docs/GAP-ANALYSIS-CURRENT.md` (read first; if it doesn't exist, create from a scan of the codebase)
- **Taxonomy**: Four-state from bureaucracy.md §7
  1. IMPLEMENTED — fixed in this phase
  2. ADDED-AS-PHASE — enters current milestone (this phase or another)
  3. SUPERSEDED-BY-ALTERNATIVE — need met differently, with evidence
  4. DEFERRED-TO-NAMED-TARGET — named future milestone or trigger condition
- **P0/P1 rule**: Cannot end phase in state 3 or 4 (auto-downgrade to ADDED-AS-PHASE)
- **Known gap from Phase 245**: MLXLLM `TODO(245)` in `MLXLocalProvider.swift` — graceful degradation when LoRA-load API is unavailable. Must be triaged.

## Process

1. Read `docs/GAP-ANALYSIS-CURRENT.md` (or create it from codebase scan)
2. For each gap, assign one of the four states with evidence
3. Implement the IMPLEMENTED gaps
4. Create new phases for ADDED-AS-PHASE gaps (or fold into existing phases)
5. Document SUPERSEDED-BY-ALTERNATIVE and DEFERRED gaps with named targets
6. Update `docs/GAP-ANALYSIS-CURRENT.md` with a status column
7. Re-run verifier to confirm closure

## Known gap candidates (to be confirmed by reading the actual file)

- **MLXLLM TODO(245)** — graceful LoRA fallback. Resolution: IMPLEMENTED if MLXLLM >= 0.21 with public LoRA API; otherwise ADDED-AS-PHASE 248 (mlx-upgrade)
- **iOS adapter** — `bretbouchard/volta-pcb-ios-4b-adapter` not yet trained. ADDED-AS-PHASE 248+
- **Vision adapter** — `kicad-vision-v2-peft` not yet trained. ADDED-AS-PHASE
- **Real inference E2E test** — needs M-series Mac. DEFERRED-TO-NAMED-TARGET (when eval harness phase 246 establishes a quality baseline)

## Out of scope

- New feature work unrelated to existing gaps
- Refactors that don't close a specific gap
- Performance optimization (unless a gap is "performance is bad")

## Open Questions

1. **Does docs/GAP-ANALYSIS-CURRENT.md exist?** Need to read it first.
2. **What gaps are P0 vs P1 vs P2?** Some gaps may have been prioritized already; we honor that.
3. **Is there a notion of "gap owner"?** If so, we route gaps to the right specialist.

---

*Phase: 247-gap-closure-vol11*
*Context gathered: 2026-07-15 — pending detailed planning*
