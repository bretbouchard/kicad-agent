# Plan: Create GitHub README for kicad-agent

## Context

The repo at `github.com/bretbouchard/kicad-agent` has **zero public-facing docs** — no README.md, no LICENSE, no badges, no install instructions. 116 commits, 7 phases complete, 459 tests passing, ~8K lines of source code, and nobody can understand what it does or how to use it from the repo page alone.

The goal: write a single README.md that gives visitors everything they need to understand, evaluate, install, and use kicad-agent — both as a Python library and as a Claude Code skill.

## Files to Create

1. **`README.md`** — The main repo README

## Files to Reference (already read)

- `.planning/PROJECT.md` — Project description, requirements, constraints
- `.planning/ROADMAP.md` — Phase structure, all 7 phases complete
- `pyproject.toml` — Package metadata, dependencies, entry points
- `~/.claude/skills/kicad-agent/SKILL.md` — Skill manifest
- `~/.claude/skills/kicad-agent/prompt.md` — Full operation reference (19 ops)
- `src/kicad_agent/cli.py` — CLI usage patterns

## README Structure

```markdown
# kicad-agent

## One-liner + badges (Python version, license, tests)

## What It Does
- Core value: LLM → JSON intent → AST mutation → valid KiCad file
- Why it exists (LLMs can't safely edit S-expressions)
- Supported file types (.kicad_sch, .kicad_pcb, .kicad_sym, .kicad_mod)

## Architecture
- Layer diagram: Parser → IR → Operations → Serializer → Validation
- Key files per layer

## Install
- pip install (from source for now)
- Dependencies (kiutils, sexpdata, networkx)
- Python 3.11+, KiCad 10+

## CLI Usage
- Print schema, run operations, dry-run, verbose
- Examples for each

## Claude Code Skill
- How to install the skill
- How to invoke (/kicad-agent)
- What the skill does (routes JSON ops through Python backend)

## Operations Reference
- Table of all 19 operations with file types and required fields
- Link to prompt.md for full details

## Architecture Layers
- parser/ — Parse KiCad files to AST
- ir/ — Intermediate representation with mutation tracking
- ops/ — 19 operation handlers with transaction safety
- serializer/ — Write valid KiCad files with normalization
- validation/ — ERC/DRC gates, structural checks, round-trip fidelity
- crossfile/ — Atomic cross-file operations, library propagation, diffs
- analysis/ — Connectivity graph via networkx

## Development
- Install dev deps
- Run tests (pytest)
- Lint (ruff), type check (mypy)

## Project Status
- All 7 phases complete
- 459 tests passing
- Roadmap summary
```

## Verification

1. `cat README.md` — verify content renders correctly
2. Check all code examples match actual CLI usage
3. Verify operation table matches prompt.md
4. Ensure install instructions work with actual pyproject.toml
