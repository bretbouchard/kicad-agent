# Council of Ricks All-Hands Review — 2026-06-01

**Review scope:** Entire kicad-agent codebase — 315 files, ~81K lines, 3171 tests, 54 phases

## Specialists Deployed (6)

| # | Specialist | Findings | Verdict |
|---|-----------|----------|---------|
| 1 | Code Quality & Architecture | 11 (3H, 5M, 2L) | APPROVE |
| 2 | Training & AI Pipeline | 5 (5H) | APPROVE |
| 3 | Operations & Engineering | 14 (5H, 5M, 4L) | APPROVE |
| 4 | Security & Infrastructure | 10 (1C, 4H, 3M, 2L) | APPROVE |
| 5 | Integration & CLI/UX | 10 (3H, 4M, 3L) | APPROVE |
| 6 | Test Coverage & Quality | 13 (5C*, 2H, 5M, 3L) | REJECT |

**Evil Morty's Final Ruling: REJECT** — 5 stale hardcoded test constants must be fixed.

## Consolidated Findings

### CRITICAL (1)
- C-1: `eval()` in circuit_templates.py:127 — replace with safe expression parser

### HIGH — Security (5)
- H-1: Playground upload lacks content validation (playground/api.py:86)
- H-2: Playground can bind 0.0.0.0 without auth warning (cli.py:688)
- H-3: BulkFetcher repo_name not validated (crawler/bulk_fetcher.py:69)
- H-4: Security tests use source inspection not runtime (test_security_hardening.py:35)
- H-5: autouse API key fixture contamination (conftest_llm.py:115)

### HIGH — Routing Correctness (5)
- H-6: `snap_to_node` O(n) linear scan (routing/graph.py:273)
- H-7: `route_all_nets` ignores intermediate pins (routing/pathfinder.py:139)
- H-8: TrackSegment hardcodes net number 0 (routing/bridge.py:63)
- H-9: ViaSegment hardcodes net number 0 (routing/bridge.py:164)
- H-10: `mark_path_as_obstacle` only blocks exact edges (routing/graph.py:313)

### HIGH — Training Integrity (4)
- H-11: GitHub token parameter handling (training/real_dataset.py:367)
- H-12: Parallel seed offset race condition (training/generator.py:56)
- H-13: Unseeded random in train_step (training/grpo.py:258)
- H-14: Self-referential best-of-N picking (training/reward_model.py:292)

### HIGH — CLI/UX (3)
- H-15: `route` subcommand crashes on paths outside CWD (cli.py:386)
- H-16: No top-level `--help` listing subcommands (cli.py:710)
- H-17: `component-search --help` starts MCP server (cli.py:520)

### HIGH — Architecture (3)
- H-18: executor.py exceeds 800-line limit (2070 lines)
- H-19: repair.py exceeds 800-line limit (1385 lines)
- H-20: topology_graph.py exceeds 800-line limit (950 lines)

### Stale Test Constants (5)
- T-1: `assert count == 85` (test_slc_compliance.py:271)
- T-2: README op count hardcoded (test_slc_compliance.py:282)
- T-3: SKILL.md op count hardcoded (test_slc_compliance.py:313)
- T-4: `assert len(submods) == 17` (test_code_quality.py:86)
- T-5: Hardcoded MCP tool counts (test_edit_server.py:39)

### MEDIUM (12)
- M-1: DFM exit code 1 ambiguity (dfm/cli.py:39)
- M-2: MCP edit server strips $defs/$ref (edit_server.py:104)
- M-3: CLI accesses private _extract_board_stats (cli.py:471)
- M-4: MCP servers depend on private lifespan_context (server.py:231)
- M-5: batch_connect label fallback empty string (executor.py:657)
- M-6: SolderMaskCheck O(n^2) without caching (dfm/checks.py:158)
- M-7: _interpolate_path undocumented precondition (routing/geometry.py:52)
- M-8: Layout-aware accesses PlacementGraph._graph (layout_aware.py:253)
- M-9: _raw_written skips UUID verification (executor.py:1519)
- M-10: Broad except Exception in violation_classifier (violation_classifier.py:205)
- M-11: Private _dirty/_raw_written accessed from executor (executor.py:691)
- M-12: 4 untested source modules

### LOW (10)
- L-1 through L-10: Code duplication, encapsulation, DFM truncation, fixtures, etc.

## Remediation Milestone: v3.1 Council Remediation

6 phases (60-65), covering all findings by domain.

---
*Review completed: 2026-06-01*
