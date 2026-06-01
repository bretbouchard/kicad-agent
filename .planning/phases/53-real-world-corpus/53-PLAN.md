# Phase 53: Real-World Corpus Expansion

**Score Impact:** Training Corpus 9 -> 10
**Requirement:** CORPUS-02
**Depends On:** Phase 52-01 (synthetic circuit templates for comparison baseline)

---

## Objective

Curate 50+ real KiCad projects from the open-source hardware community, with quality gates, license tracking, and searchable index. This complements the synthetic circuits from Phase 52 with authentic, messy, real-world designs.

---

## Why

Synthetic circuits (Phase 52) are clean and validated by construction. Real-world circuits have:

1. Non-ideal component values and unconventional design choices
2. Multi-sheet hierarchical schematics with real complexity
3. Diverse footprint and symbol library conventions
4. ERC violations that reveal common design mistakes (useful for troubleshooting training)
5. Ground truth from working hardware (tested, manufactured designs)

The existing `real_dataset.py` and `GithubDiscovery` crawler already handle PCB+schematic pairs for GRPO training. Phase 53 extends this with a curated, classified, quality-gated corpus specifically for circuit-level training -- not just board-level graph extraction.

---

## Plans

| Plan | Description | Files | Est. Tasks |
|------|-------------|-------|------------|
| [53-01](./53-01-PLAN.md) | Project curation pipeline | `corpus_curator.py`, `project_index.py` | 2 |

---

## Success Criteria

- 50+ curated open-source KiCad projects
- Each project passes quality gates (parses, >= 5 components, identifiable function)
- SPDX license tracking with commercial-use compatibility flags
- Searchable index by category, complexity, component types, license
- JSONL corpus compatible with existing training pipeline
