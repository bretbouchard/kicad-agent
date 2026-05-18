# Phase 2 Discussion Log

**Phase:** 02 — Operation Schema and IR Layer
**Date:** 2026-05-18
**Mode:** discuss (4 gray areas)
**Duration:** ~15 minutes

## Gray Areas Identified

1. Operation schema design
2. IR layer architecture
3. Transaction and rollback
4. Deterministic serialization

---

## Area 1: Operation Schema Design

| ID | Question | Options Presented | Selected |
|----|----------|-------------------|----------|
| Q1 | Schema structure | One model per op / Generic dict / Polymorphic union | **One model per op** |
| Q2 | Operation granularity | Atomic / Compound | **Atomic** |
| Q3 | File targeting | Single file / Multi-file | **Single file** |
| Q4 | Schema export | Full JSON Schema / No export / Per-type only | **Full JSON Schema** |

---

## Area 2: IR Layer Architecture

| ID | Question | Options Presented | Selected |
|----|----------|-------------------|----------|
| Q5 | IR wrapping strategy | Thin wrapper / Deep copy / No IR (direct kiutils) | **Thin wrapper** |
| Q6 | IR state tracking | Mutation + rollback + UUID / Mutation only / Full snapshot | **Mutation + rollback + UUID** |
| Q7 | IR class structure | Per-file-type / Generic / Flat namespace | **Per-file-type** |

---

## Area 3: Transaction and Rollback

| ID | Question | Options Presented | Selected |
|----|----------|-------------------|----------|
| Q8 | Snapshot scope | File-level / Per-object / No snapshot | **File-level** |
| Q9 | Rollback triggers | Auto on failure/exception/manual / Manual only / Configurable | **Auto on all** |
| Q10 | Snapshot method | Full file copy / Delta / Copy-on-write | **Full file copy** |

---

## Area 4: Deterministic Serialization

| ID | Question | Options Presented | Selected |
|----|----------|-------------------|----------|
| Q11 | Property ordering | KiCad-native / Alphabetic / kiutils as-is | **KiCad-native** |
| Q12 | Whitespace strategy | Match KiCad / Normalized / Compact | **Match KiCad** |
| Q13 | kiutils quirks | Post-process / Accept / Diff-patch | **Post-process** |
| Q14 | SCM diff strategy | Round-trip stability / Byte-identical / Semantic diff | **Byte-identical** |

---

## Summary

- 14 decisions captured across 4 areas
- All recommended options selected (user approved all defaults)
- No disagreements or alternative proposals
- Scope: Phase 2 only (no scope creep detected)

## Context File

Decisions written to: `02-CONTEXT.md`
