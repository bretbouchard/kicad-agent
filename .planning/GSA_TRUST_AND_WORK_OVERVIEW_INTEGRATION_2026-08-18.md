# Volta × GSA Trust Chain & Work Overview Integration

**Created**: 2026-08-18
**Source specs**: gsa-platform `docs/gsa/gsa_33-identity-and-provenance.md`,
`gsa_34-provenance-and-trust-chain.md`, `gsa_32-work-overview.md` (all Feature Locked)
**Status**: Planning — fold into the VoltaGSA Phase 2 path (bead `volta-htr`,
commit e439567 foundation wave)
**Depends on**: gsa-platform M1.6 (beads `gsa-platform-rl9`, `gsa-platform-00t`, `gsa-platform-27s`)

## Why This Matters Here

Volta's outputs go to fabricators. A gerber package that cannot prove its
lineage — which PCB object, which governed change, which DRC verification
evidence produced it — is exactly the failure mode gsa_33/gsa_34 exist to
prevent. Manufacturing handoff is the canonical TRUST-T005 distribution
scenario: the package that leaves this machine must arrive verifiable.

## Requirements Imported

### R1: DAIDs on manufacturing outputs (gsa_33, IDENT-T002)

| Volta artifact | Becomes |
|---|---|
| Gerber exports | DAID (one per board revision export) |
| BOM | DAID |
| Pick-and-place / centroid | DAID |
| Manufacturing package (zip) | DAID — distribution identity |
| Schematic exports | DAID |

Board WorldObjectID → export DAIDs; a re-export after a governed change
mints a new DAID with the prior export as parent — revision lineage.

### R2: Manifests + signed handoff (gsa_34, TRUST-T001..T005)

- Manufacturing package manifest: toolchain (KiCad version, exporter
  settings), inputs (board object, change references), output hashes,
  author principal, evidence references (DRC/ERC verification evidence —
  the native ERC/DRC engines already produce this).
- Fabricator-facing verification: package integrity, signature validity,
  provenance continuity, required evidence (DRC pass present).
- Tampered gerbers fail hash verification (TRUST-T003).

### R3: AI attribution (gsa_33 AI Outputs)

- LLM-driven layout suggestions / AST mutations that reach a board record
  model identity + version, governing change, human review status,
  verification outcome. The intent-JSON → AST pipeline is the natural
  capture point.

### R4: Work Overview contribution (gsa_32)

- Volta's governed work state (gap-closure phases, verification
  obligations, blocked items) feeds `remainingWork(scope)`.
- Status surfaces in the macOS app derive from the canonical projection.

## Proposed Sequencing

1. **VO-TRUST-1**: After gsa-platform M1.6 TRUST-A lands — mint DAIDs +
   manifests in the gerber/BOM export path; manifests reference the board
   object, governing change, and DRC/ERC evidence.
2. **VO-TRUST-2**: Signed manufacturing packages (fabricator verification
   story — TRUST-T005).
3. **VO-TRUST-3**: AI attribution on LLM-driven mutations.
4. **VO-WO-1**: Work state feeds the Work Overview projection.

## Acceptance (Volta side)

- Any gerber/BOM/package export produces a DAID + manifest.
- A manufacturing package verifies end-to-end (integrity, signature,
  provenance, DRC evidence present).
- Board revision history reconstructs via DAID lineage.
- Volta rows in the program Work Overview roll up from governed state.
