# Phase 95: Dual Knowledge Base Integration - Context

**Gathered:** 2026-06-14
**Status:** Ready for planning

<domain>
## Phase Boundary

Wire the 4 KiCad reference documents (already written in `docs/`) into both consumers:
1. **Cognee** -- ingest into the knowledge graph so Claude Code sessions can semantically search KiCad domain knowledge
2. **Local model** -- create a section injection system that maps kicad-agent operation types to relevant doc sections, injecting them into prompts at runtime

Out of scope: modifying the reference documents themselves, adding new reference docs, changing the local model architecture, replacing the fine-tuned model with RAG-only.

</domain>

<decisions>
## Implementation Decisions

### D-01: Cognee Ingestion Pipeline
- Use `mcp__cognee-local__add` to ingest each of the 4 reference docs
- Use `mcp__cognee-local__cognify` to process ingested data into the knowledge graph
- After ingestion, verify with `mcp__cognee-local__search` using known content from each doc
- Create a helper script or documented manual process so re-ingestion is easy when docs update

### D-02: Section Injection Architecture
- Create `src/kicad_agent/llm/knowledge.py` -- central knowledge module
- Load and chunk reference docs by `##` header sections at import time
- Map operation types (from `ops/registry`) to relevant sections via a lookup table
- Provide a `get_context_for_op(op_type: str, file_type: str) -> str` function
- Integrate into `ContextBuilder.build_error_summary()` and `build_text_prompt()`
- Wire KnowledgeManager into at least one execution path (executor or CLI handler) so knowledge injection actually activates

### D-03: Section Selection Strategy
- Map by operation category (schematic ops -> schematic reference, PCB ops -> PCB reference)
- Include core rules (coordinate system, grid snap, common pitfalls) in ALL prompts
- Limit injection to **2000 tokens per prompt** (locked decision -- RESEARCH.md rationale: system prompts are 500-1500 tokens, 2000 for knowledge keeps total under 4K within 8K context)
- Per-section token cap of **800 tokens max** -- if a single section exceeds this, take the first ~800 tokens worth of paragraphs (split on double-newline boundaries)
- Include a `--no-knowledge` CLI flag to disable injection for benchmarks
- Token budget configurable via `KICAD_KNOWLEDGE_TOKEN_BUDGET` env var with 2000 default

### D-04: Token Budget Management
- Local model context is limited (~4-8K tokens for Gemma/Qwen)
- System prompt + operation context + injected knowledge must fit
- Priority: system prompt > operation context > knowledge injection
- Knowledge injection truncated if total exceeds budget threshold
- Per-section cap prevents single large sections from consuming the entire budget

### D-05: File Path Resolution
- Knowledge files loaded from package-relative path: `docs/` relative to project root
- At import time, resolve via `__file__` or `importlib.resources`
- Graceful fallback if docs not found (log warning, return empty context)

### Claude's Discretion
- Whether to cache parsed sections in memory vs re-parse on each call
- Whether Cognee ingestion should be a CLI command or a standalone script
- Error handling granularity (per-section failures vs whole-file failures)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Source Documents (to be ingested/mapped)
- `docs/kicad_agent_reference.md` -- Agent-centric schematic editing reference (939 lines)
- `docs/pcb_editor_reference.md` -- Agent-centric PCB editing reference (8495 lines)
- `docs/gerbview_reference.md` -- Agent-centric Gerber viewing reference (167 lines)
- `docs/kicad_docs.md` -- Full KiCad Schematic Editor reference (9478 lines)

### Integration Points
- `src/kicad_agent/llm/text_prompts.py` -- System prompts and `build_text_prompt()` function
- `src/kicad_agent/llm/context_builder.py` -- `ContextBuilder` class with `build_error_summary()` and `sanitize()`
- `src/kicad_agent/llm/local_client.py` -- `LocalLLMClient` that sends prompts to the local model
- `src/kicad_agent/ops/registry.py` -- Operation registry with all operation types (117 ops, 21 categories)
- `src/kicad_agent/ops/executor.py` -- Operation executor that calls the LLM pipeline
- `src/kicad_agent/handler.py` -- Operation dispatch handler

### Existing Knowledge Patterns
- `src/kicad_agent/context.py` -- Project context loading (component intelligence, net analysis)
- `src/kicad_agent/inference/wrapper.py` -- InferenceWrapper with system prompt and context assembly

</canonical_refs>

<specifics>
## Specific Ideas

### Operation-to-Section Mapping Examples
| Operation Type | Source Doc | Sections |
|---------------|-----------|----------|
| `add_component` | kicad_agent_reference.md | Components, Power Symbols |
| `add_wire` | kicad_agent_reference.md | Wires, Connection Points |
| `add_label` / `add_bus` | kicad_agent_reference.md | Labels, Buses |
| `auto_place` | pcb_editor_reference.md | Placement, Design Rules |
| `move_footprint` | pcb_editor_reference.md | Footprints, Pads |
| `add_zone` | pcb_editor_reference.md | Copper Zones, Fill Rules |
| `modify_net_class` | pcb_editor_reference.md | Net Classes, Constraints |
| `run_gate_check` | kicad_agent_reference.md | Generating a Netlist |
| `gate_status` | kicad_agent_reference.md | Generating a Netlist |
| Any op | kicad_agent_reference.md | Coordinate System, Grid/Snap (always included) |

### Core Rules (always injected, ~200 tokens)
- Pin (at X Y) = wire connection point
- Schematic Y is inverted: abs_Y = comp_Y - pin_rel_Y
- Device:R/C have 3.81mm pin offsets (not 2.54mm)
- Wires terminate at (at) coordinates
- Grid snap: 50 mil (1.27mm) for schematics, 0.25mm for PCBs

</specifics>

<deferred>
## Deferred Ideas

- Embedding-based semantic retrieval for section selection (use exact mapping for v1)
- MCP tool for runtime knowledge queries
- Automatic section weight tuning based on model performance
- Knowledge base versioning tied to doc commits

</deferred>

---
*Phase: 95-knowledge-base-integration*
*Context gathered: 2026-06-14*
