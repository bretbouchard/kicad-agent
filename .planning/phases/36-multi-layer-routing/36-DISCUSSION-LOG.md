# Phase 36: Multi-Layer Routing - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-31
**Phase:** 36-Multi-Layer Routing
**Areas discussed:** Routing algorithm, Impedance calculation, Length matching, Operation schema

---

## Routing Algorithm Approach

| Option | Description | Selected |
|--------|-------------|----------|
| 3D graph (Recommended) | Nodes become (x, y, layer), single A* call | ✓ |
| Layer-by-layer with via cost | A* per layer, via cost at transitions | |
| Claude's discretion | Planner decides | |

**User's choice:** 3D graph — natural extension of existing 2D RoutingGraph. 160k nodes for typical 4-layer board is well under max_nodes cap.

---

## Impedance Calculation Scope

| Option | Description | Selected |
|--------|-------------|----------|
| Microstrip + stripline (Recommended) | IPC-2141 closed-form, covers 90% of designs | ✓ |
| Microstrip + stripline + CPW | Add coplanar waveguide for RF sections | |
| Microstrip only | Minimal, add more later | |

**User's choice:** Microstrip + stripline using IPC-2141 equations. No external dependencies needed.

---

## Length Matching Patterns

| Option | Description | Selected |
|--------|-------------|----------|
| Accordion + sawtooth, mm tolerance (Recommended) | Add sawtooth to existing serpentine | ✓ |
| Accordion + sawtooth + ps tolerance | Time-based tolerance for high-speed | |
| Just add sawtooth | Minimal extension | |

**User's choice:** Accordion + sawtooth with mm tolerance. Aligns with existing DiffPairResult.mismatch_mm.

---

## Operation Schema Design

| Option | Description | Selected |
|--------|-------------|----------|
| Extend AutoRouteOp (Recommended) | Add layers, impedance_target, length_match_pairs | ✓ |
| New separate operations | RouteImpedanceOp, LengthMatchOp | |
| Claude's discretion | Planner decides | |

**User's choice:** Extend existing AutoRouteOp with new fields. Single operation, simpler MCP API.

---

## Claude's Discretion

- Via cost model weighting
- Grid resolution per layer
- Impedance validation threshold
- Sawtooth amplitude/spacing constraints

## Deferred Ideas

- Coplanar waveguide (CPW) — for RF routing phase
- Picosecond length tolerance — needs propagation speed from Er
- Freerouting multi-layer integration — bridge.py exists but out of scope
- Auto-length-match detection — identify nets needing matching from net class
