# volta Strategic Expansion Plan

**Date:** 2026-05-31
**Status:** DRAFT
**Scope:** 10/10 roadmap, multi-format expansion, professional market viability

---

## Part 1: Scorecard to 10/10

### Current State

| Dimension | Score | Gap | Root Cause |
|-----------|-------|-----|------------|
| File Parsing | 10/10 | 0 | Complete — all KiCad formats, S-expression + JSON round-trip |
| Operations | 9/10 | 1 | 74 ops, missing schematic routing engine (Phase 38) |
| Validation | 7/10 | 3 | ERC auto-fix works, but no root cause analysis or smart classification |
| Training Corpus | 8/10 | 2 | 1,392+ tests, but no adversarial/edge-case generation pipeline |
| Evaluation Benchmarks | 2/10 | 8 | No standardized benchmark suite, no PCB MMLU, no circuit QA dataset |
| Domain Intelligence | 2/10 | 8 | No circuit semantics — agent edits symbols without understanding function |
| Workflow Integration | 9/10 | 1 | CLI + MCP + hooks complete, missing IDE integration beyond Claude Code |
| Demo Quality | 6/10 | 4 | Works but requires setup; no one-command demo, no visual output showcase |

### Phase Plan to 10/10

#### Tier 1: Critical Gaps (Score ≤ 3) — Priority Investment

**Evaluation Benchmarks: 2 → 10**

| Phase | Name | Target Score | Deliverable |
|-------|------|-------------|-------------|
| 41 | PCB MMLU Benchmark | 5/10 | 500+ multi-choice circuit analysis questions across 8 categories |
| 42 | Circuit QA Dataset | 7/10 | 2000+ question-answer pairs from real schematics with ground truth |
| 43 | Regression Benchmark Suite | 9/10 | Automated benchmark runner with regression detection, CI integration |
| 44 | Adversarial Test Generation | 10/10 | Automated generation of edge cases, mutation testing, coverage analysis |

Phase 41 details:
- Categories: component selection, topology recognition, signal flow, power design, DFM, SI/PI, EMC, manufacturing
- Source: THAT4301 datasheets, CD4066BE application notes, NE5532 reference designs (already in corpus)
- Format: JSON with question, choices, answer, explanation, difficulty, category
- Baseline: Run Qwen2.5-0.5B LoRA against benchmark, measure accuracy
- Target: >70% accuracy on circuit analysis after fine-tuning

Phase 42 details:
- Extract Q&A from 55 hardware modules in analog-ecosystem
- Generate from ERC reports: "What violation does this schematic have?" with ground truth
- Generate from netlists: "What is the signal flow from input to output?"
- Generate from BOMs: "What component values need to change for a different gain stage?"

Phase 43 details:
- CI pipeline: every PR runs benchmark suite, reports delta
- Regression: if benchmark score drops, PR is blocked
- Historical: track scores over time, detect model degradation

Phase 44 details:
- Mutation testing: deliberately break schematics, test if agent detects the break
- Property-based testing: generate random valid circuits, verify agent doesn't corrupt them
- Fuzzing: random S-expression mutations, verify parser doesn't crash

**Domain Intelligence: 2 → 10**

| Phase | Name | Target Score | Deliverable |
|-------|------|-------------|-------------|
| 45 | Circuit Topology Graph | 4/10 | Net-to-component graph with signal flow direction inference |
| 46 | Component Function Recognition | 6/10 | Classify subcircuits: amplifier, filter, oscillator, power supply, etc. |
| 47 | Circuit Intent Inference | 8/10 | Given a schematic, infer designer intent and suggest improvements |
| 48 | Design Rule Intelligence | 10/10 | Domain-specific DRC: impedance matching, thermal relief, bypass cap placement |

Phase 45 details:
- Build graph: component → pin → net → pin → component
- Infer direction: output pins drive nets, input pins receive, bidirectional for passives
- Classify nets: power, ground, signal, control, feedback
- Output: JSON graph suitable for circuit analysis and ML training

Phase 46 details:
- Train classifier on analog-ecosystem's 55 modules (labeled by module name)
- Features: component types, net topology, power connections, feedback loops
- Categories: preamp, compressor, EQ, filter, VCA, envelope, LFO, mixer, output stage
- Target: >85% classification accuracy on held-out schematics

Phase 47 details:
- "This is a THAT4301-based compressor. The sidechain filter is missing C47."
- "R55/R56 overlap creates an unintended short. The bypass switch function is compromised."
- Requires combining topology graph + component recognition + design rules

Phase 48 details:
- Beyond KiCad DRC: check bypass cap proximity, feedback loop stability, thermal via adequacy
- Domain rules: "opamp inputs should have matched impedance", "decoupling caps within 5mm"
- Configurable: allow project-specific design rules

#### Tier 2: Moderate Gaps (Score 5-7) — Steady Improvement

**Validation: 7 → 10**

| Phase | Name | Target Score | Deliverable |
|-------|------|-------------|-------------|
| 38 | Schematic Routing Engine | 8/10 | `connect_pins`, `batch_connect`, `regenerate_wiring` (already planned) |
| 39 | Schematic Intelligence | 9/10 | Net extraction, conflict detection, auto-naming (already planned) |
| 40 | ERC Root Cause Analysis | 10/10 | Classify violations, diagnose root causes, targeted fixes (already planned) |

Phases 38-40 are already planned and will lift Validation to 10/10.

**Demo Quality: 6 → 10**

| Phase | Name | Target Score | Deliverable |
|-------|------|-------------|-------------|
| 49 | One-Command Demo | 8/10 | `npx volta demo` → generates, validates, and renders a schematic |
| 50 | Visual Output Showcase | 9/10 | Auto-generate SVG renders of before/after, annotated ERC reports |
| 51 | Interactive Playground | 10/10 | Web-based playground for exploring operations without setup |

Phase 49 details:
- Pipeline: create schematic → add components → wire → run ERC → fix violations → render SVG
- Uses existing THAT4301 compressor circuit as demo
- Output: before/after SVGs, ERC report, operation log

Phase 50 details:
- SVG generation: `kicad-cli sch export svg` already works
- Annotate ERC violations on the SVG (red circles, numbered)
- Generate comparison: "Here's what the AI fixed" with highlighted changes

Phase 51 details:
- Web UI with operation palette
- Drag-and-drop KiCad files
- Real-time operation execution with visual feedback
- Hosted at volta.dev (or similar)

#### Tier 3: Near-Complete (Score ≥ 8) — Polish

**Operations: 9 → 10**

Already at 9. Phase 38 (routing engine) fills the last gap. No additional phases needed.

**Training Corpus: 8 → 10**

| Phase | Name | Target Score | Deliverable |
|-------|------|-------------|-------------|
| 52 | Synthetic Circuit Generation | 9/10 | Procedural generation of valid circuits for training diversity |
| 53 | Real-World Corpus Expansion | 10/10 | Curate 50+ real KiCad projects from open-source hardware community |

Phase 52 details:
- Generate valid circuits from templates: common-emitter amp, Sallen-Key filter, etc.
- Vary component values within valid ranges
- Generate corresponding ERC reports for training
- Target: 10,000+ synthetic training examples

Phase 53 details:
- Source: KiCad project library, GitHub KiCad repos, Hackaday.io projects
- Curation: filter for quality, correct ERC status, complete BOMs
- Format: standardized JSON with metadata (complexity, category, ERC status)
- License: track per-project license for commercial use considerations

**Workflow Integration: 9 → 10**

| Phase | Name | Target Score | Deliverable |
|-------|------|-------------|-------------|
| 54 | VS Code Extension | 10/10 | KiCad file editing with AI assistance directly in VS Code |

Phase 54 details:
- Leverage existing MCP server for VS Code extension
- Features: right-click → "Fix ERC violations", "Suggest improvements", "Auto-wire"
- Uses Language Server Protocol for KiCad file awareness
- Could partner with existing KiCad VS Code extensions

### Investment Allocation

Based on Pertama Partners data: successful AI projects spend **47% of budget on foundations**.

| Category | Phases | % of Effort | Rationale |
|----------|--------|-------------|-----------|
| **Foundations** (benchmarks + domain intelligence) | 41-48 | 47% | Highest leverage — lifts 2/10 scores to competitive levels |
| **Core features** (routing + validation + training) | 38-40, 52-53 | 30% | Already planned, completes existing work |
| **Presentation** (demo + showcase + playground) | 49-51 | 15% | Critical for adoption but secondary to substance |
| **Integration** (VS Code) | 54 | 8% | Polish, not foundational |

### Timeline

| Quarter | Phases | Milestone |
|---------|--------|-----------|
| Q3 2026 | 38-40 | v2.4 — Schematic Intelligence (already planned) |
| Q4 2026 | 41-42 | v2.5 — Benchmark Suite |
| Q1 2027 | 45-46 | v2.6 — Circuit Semantics |
| Q2 2027 | 43-44, 47 | v2.7 — Intelligence + Regression |
| Q3 2027 | 48, 49-50 | v3.0 — Full-Stack EDA Intelligence |
| Q4 2027 | 51, 52-54 | v3.1 — Professional Release |

---

## Part 2: Multi-Format PCB Expansion

### Current Architecture Assessment

volta's architecture is:

```
JSON Intent → Operation Executor → AST Mutation → Format-Specific Writer → Validation
```

The key insight: **operations are format-agnostic, only parsing and writing are format-specific**.

```
                    ┌──────────────────┐
                    │  Operation Layer  │  ← 74 operations (format-agnostic)
                    │  add_component,   │
                    │  connect_pins,    │
                    │  run_erc, etc.    │
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                    │  Abstract AST     │  ← Internal representation
                    │  (format-neutral) │
                    └────────┬─────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
     ┌────────▼───┐  ┌──────▼──────┐  ┌───▼────────┐
     │ KiCad Writer│  │ Altium Writer│  │ Eagle Writer│
     └────────────┘  └─────────────┘  └────────────┘
```

This means the multi-format expansion requires:
1. **Abstract AST** — format-neutral internal representation
2. **Format parsers** — read each format into abstract AST
3. **Format writers** — write abstract AST to each format
4. **Format validators** — run format-specific ERC/DRC

### Format Analysis

| Format | Market Share | Parser Complexity | API Access | Strategic Value |
|--------|-------------|-------------------|------------|-----------------|
| **KiCad** | 35% (growing fast) | Done (S-expression) | CLI (kicad-cli) | Current — maintain lead |
| **Altium** | 30% (enterprise) | High (binary + XML) | COM API, scripting | HIGH — enterprise market |
| **Eagle** | 15% (legacy) | Medium (XML + binary) | XML format, ULP scripts | MEDIUM — Autodesk ecosystem |
| **EasyEDA** | 10% (hobby/pro) | Low (JSON API) | REST API, open format | HIGH — easiest to implement |
| **OpenWater** | <1% (research) | Low (already parsed) | Open source | LOW — strategic proof point |
| **OrCAD** | 5% (enterprise) | High (proprietary) | TCL scripting | LOW — declining market |

### Expansion Strategy: "KiCad First, EasyEDA Next, Altium Last"

#### Phase 1: Abstract AST (Phase 55)

**Goal:** Extract format-agnostic representation from volta's internals.

```
AbstractCircuit:
  components: list[AbstractComponent]
    ref: str
    lib_id: str
    value: str
    footprint: str
    position: Point2D
    rotation: float
    pins: list[AbstractPin]
      number: str | int
      name: str
      type: PinType  # input, output, bidi, passive, power, unspecified
      position: Point2D  # relative to component

  nets: list[AbstractNet]
    name: str
    pins: list[PinRef]  # (ref, pin_number)
    wires: list[WireSegment]
    labels: list[Label]

  sheets: list[AbstractSheet]  # for hierarchical designs
```

**Effort:** 4-6 weeks. volta already has much of this internally — it's a refactoring exercise.

#### Phase 2: EasyEDA Support (Phase 56)

**Why EasyEDA first:**
- JSON-based format (trivial to parse)
- REST API for programmatic access
- JLCPCB integration (huge manufacturing pipeline)
- Growing hobbyist → professional adoption
- LCSC component library (world's largest)

**Deliverables:**
- `easyeda_parser.py` — Read EasyEDA JSON → Abstract AST
- `easyeda_writer.py` — Abstract AST → EasyEDA JSON
- EasyEDA API integration — push/pull designs
- LCSC component library integration

**Effort:** 6-8 weeks. JSON format is well-documented.

#### Phase 3: Altium Support (Phase 57)

**Why Altium last but most valuable:**
- Enterprise market ($5K-50K licenses)
- COM API for automation
- Binary format is complex but well-documented
- High willingness to pay for AI tooling
- Certification/partnership potential

**Deliverables:**
- `altium_parser.py` — Read Altium SchDoc/PcbDoc → Abstract AST
- `altium_writer.py` — Abstract AST → Altium format
- Altium scripting integration — COM API bridge
- Enterprise features: design rule templates, team workflows

**Effort:** 12-16 weeks. Binary format parsing is the hard part.

**Strategic play:** Altium users pay $5K-50K/year. Even a $500/year AI plugin is a no-brainer if it saves 10 hours of ERC/DRC debugging.

#### Phase 4: Eagle + OpenWater (Phase 58)

**Eagle:**
- XML-based format (easier than Altium)
- Autodesk ecosystem integration
- Large legacy design corpus

**OpenWater:**
- Already have schematics from it (proof of concept)
- Open source = good demo material
- Academic credibility

**Effort:** 4-6 weeks for Eagle (XML parsing). 2-3 weeks for OpenWater.

### Unified Operations Vision

After multi-format expansion, the same operations work across all formats:

```python
# Same API, any format
volta '{
  "op": "erc_auto_fix",
  "target_file": "compressor.sch",  # .kicad_sch, .SchDoc, .sch (Eagle), .json (EasyEDA)
  "mode": "root_cause"
}'
```

The operation executor detects format, parses to abstract AST, runs the operation, writes back in the original format.

### Market Sizing

| Segment | Users | Price | TAM |
|---------|-------|-------|-----|
| KiCad hobbyist | 500K | Free (OSS) | $0 (adoption play) |
| KiCad professional | 50K | $20/mo | $12M ARR |
| EasyEDA/JLCPCB | 2M | $10/mo | $240M ARR |
| Altium enterprise | 100K | $50/mo | $60M ARR |
| Eagle legacy | 200K | $15/mo | $36M ARR |
| **Total** | **2.85M** | | **$348M ARR** |

Even 1% penetration = $3.5M ARR.

---

## Part 3: Professional Market Viability

### Can We Swim in the Professional Pool?

**Short answer: Yes, but not as an AI designer. As an AI engineering reviewer.**

The Pertama Partners data is instructive:
- **80.3% of AI projects fail** (RAND 2025)
- **95% of GenAI pilots fail to scale** (MIT Sloan 2025)
- Successful projects: **47% of budget on foundations**, **clear pre-approval metrics**, **executive sponsorship**

volta's advantages over typical AI projects:

| Risk Factor | Typical AI Project | volta | Assessment |
|-------------|-------------------|-------------|------------|
| Clear metrics | Often vague | ERC violation count, test pass rate | STRONG |
| Data readiness | Often poor | 57K+ lines of source, 139 test files | STRONG |
| Domain specificity | Often too broad | Narrowly focused on KiCad/EDA | STRONG |
| Measurable output | Often subjective | Valid KiCad files or not | STRONG |
| Foundation investment | Often skimped | 37 phases of foundation work | STRONG |
| Executive buy-in | Often missing | We ARE the executive | STRONG |
| Scalability | Often fails here | Local model (Qwen2.5-0.5B), no cloud deps | STRONG |

**volta is in the 19.7% that succeeds** because:
1. Binary success criteria — file is valid or it isn't
2. Deep domain specificity — not general-purpose AI
3. Foundation-first investment — 37 phases before expansion
4. No scaling dependency — runs locally, no cloud costs
5. Real utility — saves hours of manual ERC/DRC work

### Competitive Landscape

| Competitor | Positioning | Strength | Weakness |
|------------|-------------|----------|----------|
| **Flux.ai** | Cloud EDA with AI | Nice UI, collaboration | Cloud-only, limited AI |
| **Jitx** | Code-generated hardware | Strong for procurement | Not interactive, not review-focused |
| **Celus** | AI-assisted circuit design | Enterprise relationships | Black box, expensive |
| **Synopsys DSO.ai** | AI for chip design | Enormous budget | ASIC-only, not PCB |
| **Cadence Allegro AI** | AI-assisted layout | Industry standard | Enterprise-only, $100K+ |
| **volta** | AI engineering review for KiCad | Open, local, measurable | KiCad-only (for now) |

**Our positioning: "Engineering review system, not AI designer."**

This is critical. The market is skeptical of AI that *designs* circuits. But AI that *reviews* and *fixes* circuits is immediately valuable. The Pertama data shows that treating AI as business transformation (not novelty) is a 61% success factor.

### Positioning Strategy

**Tier 1: OSS Tool (Now)**
- Free, open-source KiCad engineering review
- Build community, establish credibility
- "The ESLint of KiCad" — static analysis for hardware

**Tier 2: Professional Tool (Phase 56-57)**
- Multi-format support (EasyEDA, Altium)
- Professional features: team workflows, design rule templates
- Pricing: freemium (KiCad free, commercial formats paid)

**Tier 3: Enterprise Platform (Phase 57+)**
- CI/CD integration for hardware design review
- Compliance checking (IPC standards, safety requirements)
- Design review automation for regulated industries (medical, automotive, aerospace)
- Pricing: enterprise licensing

### Pertama Partners Risk Mitigation

Applied to volta specifically:

| Pertama Risk | Mitigation | Status |
|--------------|------------|--------|
| No clear pre-approval metrics | ERC violation count, benchmark accuracy, test coverage | Active |
| Poor data readiness | 57K lines source, 139 test files, 55 real hardware modules | Active |
| Leadership failure (84%) | Solo developer = no leadership gap | Active |
| Pilot-to-scale failure (95%) | Local model, no infrastructure to scale | Active |
| "AI as novelty" failure | Positioned as engineering review, not AI magic | Active |
| Insufficient foundation investment | 47% allocation to benchmarks + domain intelligence | Planned |
| Unrealistic expectations | Binary success: valid file or not | Active |

**Key insight:** volta avoids the top 3 failure modes by design:
1. **No scaling problem** — runs locally, no cloud infrastructure
2. **Measurable value** — reduces ERC violations by X% (trackable)
3. **No executive buy-in needed** — we ARE the buyer and the builder

### Professional Pool Entry Criteria

To be taken seriously by professional EDA users, we need:

| Criteria | Current | Target | Phase |
|----------|---------|--------|-------|
| Benchmark publication | None | PCB MMLU results published | 41 |
| Real project portfolio | 1 (analog-ecosystem) | 10+ real projects | 53 |
| Multi-format support | KiCad only | KiCad + EasyEDA + Altium | 56-57 |
| CI/CD integration | None | GitHub Actions + GitLab CI | 43 |
| Design rule coverage | Basic ERC | Domain-specific (SI/PI/thermal) | 48 |
| Enterprise features | None | Team workflows, audit trails | 57 |
| Documentation | Good | Professional-grade with API reference | 49-50 |
| Community | Small | 1000+ GitHub stars, 100+ Discord members | Ongoing |

### Revenue Model

| Tier | Price | Features | Target |
|------|-------|----------|--------|
| **Community** | Free | KiCad support, basic operations | Adoption |
| **Professional** | $20/mo | All formats, CI/CD, benchmarks | Individual engineers |
| **Team** | $50/seat/mo | Team workflows, design rules, audit trails | Small teams |
| **Enterprise** | Custom | On-prem, compliance, SLA | Regulated industries |

**Break-even:** ~500 professional subscribers = $120K ARR, covers development costs.

---

## Part 4: Execution Priorities

### Immediate (Q3 2026)
1. Complete Phases 38-40 (schematic routing + intelligence + ERC root cause)
2. Ship v2.4 milestone
3. Begin Phase 41 (PCB MMLU benchmark)

### Near-term (Q4 2026)
1. Ship Phase 41-42 (benchmark suite + QA dataset)
2. Publish benchmark results
3. Begin Phase 45 (circuit topology graph)

### Medium-term (Q1-Q2 2027)
1. Ship Phases 45-46 (domain intelligence)
2. Begin Phase 55 (abstract AST for multi-format)
3. Start EasyEDA integration

### Long-term (Q3 2027+)
1. Multi-format support (EasyEDA, then Altium)
2. Professional release with pricing
3. Enterprise features

### What NOT to Do

Based on Pertama Partners failure patterns:

1. **Don't rush to multi-format before benchmarks are solid.** The 2/10 evaluation score is the biggest risk. No professional takes an AI tool seriously without published benchmarks.
2. **Don't try to be an AI designer.** The "engineering review" positioning is our moat. Every failed AI EDA startup tried to design circuits. We review and fix them.
3. **Don't skip the foundation investment.** 47% on foundations is the success factor. Phases 41-48 are foundations. Don't shortcut to the demo.
4. **Don't expand to Altium before EasyEDA proves the multi-format architecture.** EasyEDA is JSON. Altium is binary. Prove the abstraction works with the easy one first.
5. **Don't chase enterprise before community.** 1000 GitHub stars before enterprise sales calls. The community validates the technology.

---

## Success Metrics

| Metric | Current | 6-Month Target | 12-Month Target |
|--------|---------|----------------|-----------------|
| Scorecard average | 6.6/10 | 7.5/10 | 9.0/10 |
| Lowest dimension | 2/10 (benchmarks + domain) | 5/10 | 8/10 |
| Format support | 1 (KiCad) | 1 (KiCad) | 2-3 (+ EasyEDA) |
| Benchmark questions | 0 | 500+ | 2000+ |
| Real project corpus | 1 | 5 | 50+ |
| GitHub stars | ~50 | 200 | 1000+ |
| Benchmark accuracy | N/A | 70% | 85%+ |
| Operations | 74 | 80+ | 90+ |
| Test count | 1392+ | 1600+ | 2000+ |

---

## Appendix: Pertama Partners Key Statistics

- **80.3%** of AI projects fail (RAND Corporation, 2025)
- **95%** of GenAI pilots fail to scale (MIT Sloan, 2025)
- **84%** of failed projects have leadership failures
- **54%** success rate with clear pre-approval metrics
- **47%** success rate with formal data readiness assessments
- **68%** success rate with sustained executive sponsorship
- **61%** success rate treating AI as business transformation
- **58%** success rate with comprehensive change management
- Successful projects: **$5.1M cost → $14.7M value (+188% ROI)**
- Successful projects spend **47% of budget on foundations** vs 18% for failed projects
