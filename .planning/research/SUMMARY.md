# Research Summary — v7.0 Vendor-Neutral Manufacturing Layer

## Overview

v7.0 adds a vendor-neutral manufacturing layer to volta: DRC pre-flight profiles for any fab, a versioned build/handoff system, and (deferred) opt-in vendor API adapters. **Zero new dependencies** — built entirely on the existing KiCad CLI + Python + Pydantic stack. The codebase already has significant primitives (`ManufacturerProfile`, `ManufacturingManifest`, `ManufacturingReadinessGate`, export wrappers) that v7.0 assembles and completes.

## Stack Additions

**None.** All required technologies are already installed:
- kicad-cli 10.0.1 — DRC with `--custom-rules`, all export formats
- Pydantic 2.x — schema models (BoardSpec, Build record)
- stdlib zipfile/hashlib/json — bundling, hashing, serialization
- kiutils — S-expression parsing for title_block

**Explicitly avoided:** HTTP libraries (deferred to P6), PDF generation libs (Markdown + kicad-cli PDFs), cloud storage SDKs (local builds/).

## Feature Table Stakes

| Category | Must-Have | Notes |
|----------|-----------|-------|
| Board Metadata | title_block parse/write + BoardSpec model (finish, color, stackup) | Foundation — unblocks versioning |
| DRC Profiles | PCBWay/JLCPCB/AISLER `.kicad_dru` files + `drc_vendor` op | Files exist; wiring is the work |
| Versioned Builds | Build record + serialized manifest + build_create/list/show | Extends existing ManufacturingManifest |
| Handoff Package | Full export orchestration → zip + readme + manifest | Universal fallback for ALL vendors |
| Integration | MCP auto-exposure + CLI subcommands + ProjectContext | Largely automatic |

## Key Differentiators

1. **Universal handoff package** — works with every fab (3 with APIs, 10+ without). No vendor lock-in.
2. **Versioned builds** — git SHA + board rev + artifact hashes link a build to exact source state
3. **Vendor-neutral design** — API adapters are opt-in accelerators, not requirements
4. **DRC profiles cost nothing to extend** — drop a `.kicad_dru` file = support a new vendor

## Architecture Highlights

- **3 new modules** in `src/volta/manufacturing/`: drc_profiles/ (data), board_spec.py, build.py, manifest.py, handoff.py
- **~8 new operations** following the existing pattern (schema → registry → handler → auto-MCP)
- **Build directory structure**: `builds/v{rev}_{timestamp}/` with manifest.json, readme.md, handoff.zip
- **BoardSpec sidecar**: `.kicad_build_spec.json` alongside the project (finish, color, stackup, impedance)

## Watch Out For

| Pitfall | Severity | Phase | Prevention |
|---------|----------|-------|------------|
| Stale DRC values (PCBWay annular ring) | Medium | P2 | Cross-check vs current capabilities; update to 0.15mm |
| title_block parsing fragility | High | P1 | Follow NativeStackup pattern; test round-trip; handle KiCad 10 quoting |
| Vendor lock-in via hard-coded formatting | High | P4 | Profile-driven BOM/output formatter, not direct export_jlcpcb_bom calls |
| Build dir git pollution | Low | P3 | Add `builds/` to .gitignore |
| Manifest false confidence | High | P3+P4 | Reuse ManufacturingReadinessGate as hard gate; validate required artifacts |
| Profile licensing/attribution | Low | P2 | Prefer Cimos (MIT); add attribution comments |
| API adapter scope creep | Medium | P6 (DEFERRED) | Define ABC in P5; defer adapters to separate milestone |

## Build Order

```
P1 Metadata Foundation → P3 Builds → P4 Handoff → P5 Integration → P6 API (DEFERRED)
                      ↗
P2 DRC Profiles ──────┘
```

P1 and P2 are the foundation. P3 depends on P1. P4 depends on P1+P2+P3. P5 integrates. P6 is deferred.

## Vendor Landscape Summary

| Vendor | DRC file? | API? | v7.0 Coverage |
|--------|-----------|------|---------------|
| PCBWay | ✅ official | ✅ Partner API (gated) | DRC + handoff (P1-P5); API adapter deferred (P6) |
| JLCPCB | ✅ community (MIT) | ✅ Online API | DRC + handoff; API adapter deferred |
| AISLER | ✅ official (5 stackups) | ❌ | DRC + handoff |
| OSH Park | ⚠️ author from specs | ❌ | DRC + handoff |
| MacroFab (US, ITAR) | ❌ | ✅ Cloud API v2 | Handoff only; API adapter deferred |
| Advanced Circuits (US, ITAR) | ❌ | ❌ (FreeDFM) | Handoff only |
| All others | ❌ | ❌ | Handoff only |

**Key insight:** The handoff package is the universal path. Only 3 vendors have APIs, and even those can use the handoff path. API adapters are accelerators on top of a complete vendor-neutral foundation.

## Confidence

- **HIGH:** DRC files exist and are verifiable (PCBWay official repo, AISLER official repo, Cimos MIT aggregator)
- **HIGH:** kicad-cli supports `--custom-rules` flag (documented, tested in KiCad 9/10)
- **HIGH:** Existing codebase primitives (ManufacturerProfile, ManufacturingManifest, export wrappers) — verified via codebase mapping
- **MEDIUM:** title_block field format in KiCad 10 (may have quoting variations — needs testing)
- **MEDIUM:** MacroFab API endpoint details (gated behind authenticated portal)
- **DEFERRED:** All API adapter implementation (no code until credentials obtained)
