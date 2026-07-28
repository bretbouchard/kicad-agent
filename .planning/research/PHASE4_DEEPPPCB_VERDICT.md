---
title: "Phase 4 — DeepPCB Cloud Routing Verdict"
tags: [phase-4, routing, cloud, deeppcb, research-verdict]
status: complete
created: 2026-07-28
sources: [https://deeppcb.ai/, https://deeppcb.ai/api (404), https://docs.deeppcb.ai/]
---

# Phase 4 — DeepPCB Cloud Routing Verdict

**Verdict:** **DEFERRED — adapter out of scope for indie ISV.** Trigger conditions documented below.

---

## TL;DR

DeepPCB has an API and supports KiCad natively, but the API is gated to **Enterprise tier ($900 USD)** with **no public REST endpoint documentation**, **no self-serve signup**, and **no published authentication flow**. This matches the SiliconExpert / SnapMagic dead-end pattern: enterprise sales contact required.

For Volta PCB's indie-ISV target market (App Store, one-time purchase, zero support overhead), a $900/month + sales-contact cloud router is **not shippable** behind the same plugin registry pattern as Freerouting and KiCad-native. Three different access tiers in one registry would confuse users.

**Action:** Task 4 ships as a **research verdict** (this document). No `DeepPCBProvider` adapter in Phase 4. Trigger condition documented for re-evaluation when access opens up.

---

## Evidence (collected 2026-07-28)

| Question | Evidence | Verdict |
|----------|----------|---------|
| Public API exists? | deeppcb.ai homepage says "Integrate with our tools using our API and MCP" — framed as **Enterprise tier** offering only | Exists but gated |
| REST endpoint docs? | `docs.deeppcb.ai/api` returns **404**; no Swagger / OpenAPI spec published; no authentication, endpoint, or rate-limit docs visible | Not publicly documented |
| File format support | "Native support for Zuken and KiCad" — KiCad import/export explicitly confirmed. Other EDA tools also supported (EasyEDA, Eagle, Proteus, Altium) | KiCad ✅ confirmed |
| Pricing | Pro tier $95 USD, Enterprise tier $900 USD. "Pay as you go" model — no subscription. Per-route transaction cost not disclosed | Enterprise required for API |
| Self-serve signup | Generic "Get Started" → `app.deeppcb.ai`. **No API-account-specific signup** — Enterprise requires contact sales | Gated behind sales contact |
| Authentication | Not documented anywhere reachable | Unknown |
| Quality vs Freerouting | Marketing claims (2026-07-27 research): "smarter routing, cleaner results, minutes not hours". Independent benchmarks not yet published | Unverified marketing claims |

## Sources

- [DeepPCB homepage](https://deeppcb.ai/) — pricing tiers ($95 Pro, $900 Enterprise), API/MCP "Enterprise-only" framing, KiCad native support claim
- [DeepPCB API page](https://deeppcb.ai/api) — returns 404 (page exists in nav but no content)
- [DeepPCB docs](https://docs.deeppcb.ai/) — Mintlify docs site present, but no API reference section reachable; login-gated content beyond marketing

## Why This Kills the Cloud Adapter in Phase 4

Phase 1-3 followed a **plugin-registry-mirror** pattern: every `RoutingProvider` adapter must be installable by an indie developer without enterprise sales contracts. Digi-Key, Mouser, easyeda2kicad, KiCad native, Freerouting — all self-serve. DeepPCB Enterprise breaks the pattern.

If we shipped a `DeepPCBProvider`:
- Users would see it as an option, click "Configure"
- They'd hit a paywall / sales-contact wall
- That's worse than not shipping the adapter at all (silent breakage ≠ SLC)

So: **drop the DeepPCB adapter for now**, ship the research verdict, set the trigger condition.

## Trigger Condition for Re-Evaluation

Re-evaluate DeepPCB integration when **any** of the following becomes true:

1. DeepPCB publishes a self-serve API tier (Pro or below) with public REST docs at `docs.deeppcb.ai/`
2. DeepPCB's standard `app.deeppcb.ai` flow exposes an API key after signup (even Enterprise — at least then the access path is productized)
3. Volta PCB's market positioning changes (e.g., B2B / enterprise tier added to the indie App Store product)
4. A **different** cloud router emerges with: KiCad native + self-serve API + published docs + indie-friendly pricing (≤$50/month OR per-route ≤$1.00)

Until then: no code.

## Architecture Implication

`RoutingProviderRegistry` ships with **two adapters** in Phase 4:
- `FreeroutingProvider` — open-source Java CLI shell-out
- `KiCadNativeRouterProvider` — wraps KiCad's built-in interactive router via CLI

The cloud-router slot in the registry stays empty, ready for a future adapter when any trigger above fires.

## Phase 4 Final Shape (post-verdict)

| Task | Status | Deliverable |
|------|--------|-------------|
| Task 1: RoutingProvider protocol + registry | In scope | New code |
| Task 2: Freerouting adapter | In scope | New code |
| Task 3: KiCad native router | In scope | New code |
| Task 4: Cloud routing research | **Complete (this verdict)** | Research deliverable, no code |
| Task 5: Routing settings UI | In scope | New code |

**Net scope:** 4 tasks of code + 1 research verdict. Phase 4 is now lean and shippable end-to-end.

---

*Research executed: 2026-07-28*
*Verdict applied to: `phases/4-routing-plugin-system/PLAN.md` Task 4*
*Verdict applied to: `RESEARCH/CLOUD_ROUTING_EVALUATION.md` (marked complete)*
*Verdict NOT applied to: actual adapter code, intentionally deferred per trigger conditions above*
