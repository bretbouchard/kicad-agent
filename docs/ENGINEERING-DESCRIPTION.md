# kicad-agent — Engineering Description

**For engineering teams evaluating kicad-agent as a tool, integration target, or contribution base.**

Version: v6.0 (2026-07-14)
Repository: `kicad-agent` (monorepo)
Audience: EDA-tooling engineers, ML engineers, IDE/UI engineers, PCB designers with software interests.

---

## What kicad-agent is

A **dual-layer system** that turns natural-language circuit intent into validated KiCad schematics, then hands the schematic off to a human for placement/routing and a fab house for manufacturing.

```
┌─────────────────────────────────────────────────────────────────────┐
│                      macOS App (Swift 6.2)                            │
│                                                                       │
│  ┌────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────┐   │
│  │ SwiftUI    │  │  Chat        │  │  Validation  │  │ Inline   │   │
│  │ Views      │  │  Pipeline    │  │  Panel       │  │ Preview  │   │
│  │ (Liquid    │  │  (Router +   │  │  (NativeERC/ │  │ Renderer │   │
│  │  Glass)    │  │  Stream)     │  │   NativeDRC) │  │ (SVG/PNG)│   │
│  └─────┬──────┘  └──────┬───────┘  └──────┬───────┘  └────┬─────┘   │
│        └────────────────┴─────────────────┴───────────────┘          │
│                              │ Swift IPC (DaemonMessenger)            │
└──────────────────────────────┼──────────────────────────────────────┘
                               │ JSON-lines over stdio
┌──────────────────────────────┼──────────────────────────────────────┐
│                      Python Daemon (3.11+)                            │
│                                                                       │
│  ┌────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────┐   │
│  │  IPC       │  │  Operation   │  │  Validation  │  │ Routing  │   │
│  │  Handler   │→ │  Registry    │  │  Engines     │  │ Engine   │   │
│  │ (Pydantic) │  │  (268 ops)   │  │  (NativeERC/ │  │ (A*/Free)│   │
│  └────────────┘  └──────┬───────┘  │   NativeDRC) │  └──────────┘   │
│                         │           └──────────────┘                  │
│  ┌────────────┐  ┌──────┴───────┐  ┌──────────────┐  ┌──────────┐   │
│  │  KiCad     │  │  SKIDL       │  │  SPICE       │  │ Vendor   │   │
│  │  Parser    │  │  Converter   │  │  Bridge      │  │ DRC      │   │
│  │  (S-expr)  │  │  (L1/L2)     │  │  (ngspice)   │  │ Profiles │   │
│  └────────────┘  └──────────────┘  └──────────────┘  └──────────┘   │
└───────────────────────────────────────────────────────────────────────┘
                               │
                               │ subprocess / kicad-cli
                               ▼
                       KiCad 10 (when installed)
```

**Key architectural principle:** Python daemon is the source of truth for all file mutations. The macOS app is a UI; it never writes `.kicad_sch` / `.kicad_pcb` directly. Every mutation goes through a versioned operation with rollback.

---

## Why this shape

### Why a Python daemon and not a Swift-only app?

1. **Library reuse.** KiCad parsing, SKIDL, ngspice bindings, Pydantic schemas — all are mature Python. Rewriting in Swift is years of work and continuous maintenance against KiCad's evolving S-expression format.
2. **ML ecosystem.** HuggingFace transformers, PEFT, Optuna, scikit-learn — all Python. The training pipeline is Python.
3. **Distribution.** Code-signing a Swift app is hard; distributing a Python `py2app`/`nuitka` bundle with a hardened runtime is tractable on macOS 26.

The Swift layer exists for:
- SwiftUI / Liquid Glass (best in class on Apple platforms)
- MLX Swift (the fastest path to local inference on Apple Silicon)
- Native validation (zero-allocation parsing, instant results)
- Cost ledger for cloud providers (typed, persistent, no IPC)

### Why SKIDL as the "thinking language"?

SKIDL is a Python library that produces netlists from imperative code:

```python
from skidl import Part, Net

vcc = Net('VCC'); gnd = Net('GND')
r1 = Part('Device', 'R', value='10k', footprint='Resistor_SMD:R_0805')
r2 = Part('Device', 'R', value='47k', footprint='Resistor_SMD:R_0805')
op = Part('Amplifier_Operational', 'TL072', footprint='SOIC-8')
r1[1] += vcc; r1[2] += op.p[3]
r2[1] += op.p[2]; r2[2] += op.p[3]  # feedback
op.p[3] += vcc; op.p[4] += gnd
generate_netlist()
```

This is **trainable**: the v3 training corpus is 21,347 SKIDL scripts. Models trained on this corpus generalize better than models trained on raw KiCad S-expressions (proven in SchGen paper, replicated in our internal evals: 82% pin-correct vs 32% for raw KiCad training).

SKIDL also gives us a **bidirectional** bridge to KiCad — we can parse any `.kicad_sch`, emit SKIDL, run the model's edits in SKIDL space, and convert back. This avoids the model accidentally breaking KiCad file invariants.

### Why atomic operations, not compound transactions?

Each op (e.g. `add_wire`, `set_property`, `move_footprint`) is a single mutation. Compound intents ("add a decoupling cap near U1") are broken into a sequence of atomic ops by the OperationExecutor. This gives us:

- **Rollback granularity** — undo one op, not a multi-minute transaction
- **Validation** — each op validates its own preconditions
- **Audit trail** — every op is journaled with diff, who, when, why
- **Concurrency safety** — ops are serialized through a per-project lock

The cost is verbosity (the LLM emits multi-op JSON), but models handle this well in practice and the audit is gold for debugging.

---

## What's actually shipped (v6.0)

### macOS app

- **Liquid Glass shell** (`Views/LiquidGlassShell.swift:1-562`) — chat-first main window
- **Project sidebar** (`Views/ProjectSidebar.swift`) — create / delete / select
- **Chat pipeline** — streaming via `RouterStreamProvider` (echo stripping, sentence/paragraph chunking)
- **Operation executor** — runs LLM-emitted JSON op sequences with rollback on error
- **Validation panel** — runs NativeERC + NativeDRC, displays results
- **Inline preview** — SVG/PNG render of generated schematics/PCBs
- **Settings** — provider routing, BYOK keys, external MCP servers
- **Cost tracking** — per-message token + USD estimate
- **Image attachments** — model-side: supports image inputs; UI: Phase 196 pending

### Python daemon

- **268 atomic operations** in three Swift files (`VoltaEngine.swift` 27, `VoltaEngineGenerated.swift` 163, `VoltaEngineRemaining.swift` 78) — see `FEATURE-INVENTORY.md` for the table
- **Native validation** — Swift + Python both ship full ERC/DRC
  - Pin-type compatibility (11x11 matrix)
  - Power net validation
  - No-connect validation
  - Dangling wire detection
  - Copper spacing (O(n log n) via SpatialHash, Phase 232)
  - Annular ring verification
  - Courtyard overlap (shapely)
  - Hole-to-hole clearance
- **SKIDL ↔ KiCad converter** — bidirectional, L1 (pin-level) and L2 (component-level)
- **SPICE bridge** — `skidl.generate_netlist()` → ngspice batch mode → Bode plots, BOM extraction
- **Freerouting integration** — DSN/SES exchange for serious routing jobs
- **Vendor DRC profiles** — JLCPCB, PCBWay, AISLER (2/4/6/8L), OSH Park, Advanced Circuits, General
- **Manufacturer handoff** — single `build_handoff_export(vendor=...)` produces complete zip
- **MCP server** — exposes `kicad-component-search` and `kicad-agent-edit` for IDE integration
- **CLI** — 26 subcommands, see `FEATURE-INVENTORY.md` §5.1

### Models

- **Local MLX** — Qwen 2.5 0.5B (bundled), Gemma 4 12B V2 (when downloaded), custom adapters
- **Cloud** — Anthropic, OpenAI-compatible, Gemini, Ollama (any provider speaking the OpenAI streaming protocol)
- **BYOK** — keys stored in macOS Keychain, never sent to kicad-agent
- **Cost ledger** — per-message token count + estimated USD, persisted in SwiftData

### Training infrastructure

- **Volta v5 adapter** — 47K multi-task, loss 0.10, A100 80GB, 19.2h, completed
- **Volta v2 12B adapter** — in training (Vast.ai, instance 44774137, step 2773/3000 at last check, ETA ~1h 26m)
- **Corpus** — 21,347 SKIDL scripts (Microsoft SchGen 8,396 + crawled KiCad repos 6,287 + synthetic 5,600 + hand-curated 13 + maze routing 1,000)
- **Curator** — `corpus_curator.py` handles dedup, deep-normalization to canonical L1 form
- **Converters** — `schgen_to_skidl` (AST-driven), `kicad_repo_to_skidl` (regex-driven with pin-union-find)

---

## What's NOT shipped (gap honesty)

We do not currently ship:

| Capability | Status | Why |
|---|---|---|
| Full auto-routing (A* / neural) | Stub | Freerouting does the heavy lifting; in-app router is Manhattan-only |
| Vision input (camera → schematic) | Adapter trained, UI pending | Phase 236 |
| Real-time collaboration | Scaffolded | CloudKit sync code exists, live cursors not |
| Altium / Eagle import | Not started | No customer demand to justify the lift |
| High-speed SI (impedance, eye, crosstalk) | Not started | Prosumer/Pro tier feature |
| IPC compliance (IPC-2221, IPC-7351) | Not started | See `GAP-ANALYSIS-CURRENT.md` |
| iOS / iPadOS | Not started | Liquid Glass needs macOS first |
| Linux / Windows daemon | Not started | All Apple Silicon focus |
| Safety certs (IEC 61010, IEC 60601) | Not started | We don't ship medical / industrial |

---

## Integration paths

### For EDA tooling engineers

```python
# Spawn the daemon from any Python tool
from kicad_agent.daemon import DaemonClient

with DaemonClient() as daemon:
    result = daemon.op("add_wire", {
        "project": "my_board",
        "start": [100, 50],
        "end": [200, 50]
    })
    print(result)  # {'op': 'add_wire', 'wire_uuid': '...', 'diff': '...'}
```

Or via the MCP server:

```json
{
  "mcpServers": {
    "kicad-agent": {
      "command": "kicad-agent",
      "args": ["component-search"]
    }
  }
}
```

### For ML engineers

```python
# Training loop with our SFT trainer
from kicad_agent.training import VoltaSFT, load_corpus

corpus = load_corpus("volta-v3", split="train", level="L1")
model = VoltaSFT(base="google/gemma-4-12b-it", rank=64, alpha=128)
model.fit(corpus, epochs=3, batch_size=4, lr=2e-4)
```

The trained adapter converts to MLX via `convert_peft_to_mlx.py` for local deployment.

### For IDE / editor plugin authors

The daemon exposes a JSON-lines IPC channel. A minimal client is ~80 LOC in any language. Example clients: VS Code extension (Python, in tree), Zed plugin (Rust, planned), and the Swift macOS app.

---

## Performance characteristics

| Operation | Latency | Notes |
|---|---|---|
| Project create | <100 ms | Empty schematic + PCB |
| `list_components` (100 parts) | 1-2 ms | In-memory parse |
| `add_component` | 2-5 ms | Mutate + journal |
| `run_native_erc` (100 parts) | 10-20 ms | Swift, single-pass |
| `run_native_drc` (1000 traces) | 50-200 ms | Python + SpatialHash |
| Chat stream (first token) | 200-800 ms | Qwen 0.5B local; 1-3s for Gemma 4 12B |
| Chat stream (subsequent tokens) | 15-40 ms/token | MLX on M2 Pro |
| Handoff zip (full board) | 5-30 s | Depends on board complexity |

---

## Testing posture

- **Python:** 6,317 tests passing as of v6.0 (see `tests/`). Coverage: 84% on core, 71% overall. Heavy on parsing/validation, lighter on routing/MCP.
- **Swift:** Tests for providers, daemon bridge, validation engines, state machine. **Gap:** no test file for the operations registry, no visual regression for Liquid Glass views.
- **Gaps:** No E2E browser-style tests (the macOS app is desktop). No load tests for the daemon. No adversarial prompt tests for cloud providers.

---

## Repo layout

```
kicad-agent/
├── macos-app/                    # Swift 6.2 / SwiftUI app
│   ├── Sources/KiCadAgent/
│   │   ├── Views/                # SwiftUI views
│   │   ├── Parsing/              # Volta engine (op registry)
│   │   ├── Validation/           # NativeERC, NativeDRC
│   │   ├── Models/Providers/     # LLM providers
│   │   ├── IPC/                  # DaemonMessenger
│   │   └── State/                # SwiftData persistence
│   └── Tests/                    # Swift tests
├── kicad-agent-0.1.0/            # Python daemon + training
│   ├── src/kicad_agent/
│   │   ├── handler.py            # IPC dispatcher
│   │   ├── ops/                  # Operation implementations
│   │   ├── validation/           # native_erc.py, native_drc.py
│   │   ├── routing/              # A* / Freerouting
│   │   ├── spice/                # ngspice bridge
│   │   ├── training/             # Corpus, SFT/GRPO trainers
│   │   └── cli.py                # All CLI subcommands
│   └── tests/                    # 6,317 tests
├── Scripts/                      # Build, sign, ship, train
├── specs/                        # Legacy specifications
├── docs/                         # Documentation (this file)
└── .planning/                    # GSD project state
```

---

## Contributing

- **Bug reports:** GitHub Issues with `repro:` block (input schematic + expected vs actual)
- **Feature requests:** Open an issue with a use case (community, not just "wouldn't it be cool if...")
- **Pull requests:** TDD expected. New ops need: a handler, a Pydantic schema, a journal entry, and a Python test + Swift parity check
- **Council review:** All PRs that touch validation, IPC, or persistence are reviewed by the `council-of-ricks` agent

---

## Open questions for engineering teams

If you're evaluating kicad-agent, these are the questions we can't answer for you:

1. **What's your typical board complexity?** (component count, layer count, signal speed) — tells you whether our DRC/ERC rules are sufficient.
2. **What fab house?** — we have first-class profiles for JLCPCB/PCBWay/AISLER/OSH Park; others use the General profile.
3. **What's your model policy?** — local MLX is private but slower; cloud is faster but your prompts go to Anthropic/OpenAI.
4. **What's your team size?** — multi-user collaboration is not yet shipped; we recommend per-developer local installs.
5. **What's your EDA baseline?** — if you already pay for Altium, kicad-agent is a sketching tool, not a replacement. If you're on KiCad, kicad-agent is an accelerator.
