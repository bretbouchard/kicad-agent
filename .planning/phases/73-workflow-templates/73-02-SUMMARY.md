---
phase: 73-workflow-templates
plan: 02
subsystem: ops, mcp
tags: [workflows, templates, mcp, meta-tools, operation-sequences]

# Dependency graph
requires:
  - phase: 71
    provides: registry with complete operation metadata
  - phase: 73-01
    provides: validate_conflicts and validate_dependencies functions
provides:
  - 8 workflow templates for common KiCad task sequences
  - list_workflows and get_workflow MCP meta-tools
  - Workflow dependency chain and conflict-free validation
affects: [mcp-clients, llm-agents, operation-planning]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Workflow templates: named multi-step sequences with required/optional steps"
    - "MCP workflow tools: read-only discovery meta-tools for LLM guidance"

key-files:
  created: []
  modified:
    - src/kicad_agent/ops/workflows.py
    - src/kicad_agent/mcp/edit_server.py
    - tests/test_workflows.py
    - tests/test_mcp/test_edit_server.py

key-decisions:
  - "drc_check removed from full_pcb_layout workflow (MCP meta-tool, not a registered operation)"
  - "update_pcb_from_schematic removed from full_pcb_layout (requires kicad-cli external dependency)"
  - "Workflow templates use only registered operations for validation consistency"

requirements-completed: []

# Metrics
started: 2026-06-06T20:15:30Z
completed: 2026-06-06T20:17:00Z
duration: 2m
duration_minutes: 2
commits: 1
files_modified: 4
---

# Phase 73 Plan 02: Workflow Templates Summary

**8 predefined workflow templates exposed as MCP read-only meta-tools for LLM-guided multi-step operation sequences**

## Performance

- **Duration:** 2m
- **Started:** 2026-06-06T20:15:30Z
- **Completed:** 2026-06-06T20:17:00Z
- **Tasks:** 1
- **Commits:** 1 (atomic task commit)
- **Files modified:** 4

## Accomplishments
- Added 2 new workflow templates: `full_pcb_layout` (PCB layout pipeline) and `convert_legacy_schematic` (KiCad 5/6 to 10 conversion), bringing total to 8
- Exposed `list_workflows` and `get_workflow` as read-only MCP meta-tools in edit_server.py
- All 8 workflows validated: step op_types exist in registry, dependency chains are internally consistent, no conflicts between steps
- 6 new MCP dispatch tests covering list_workflows, get_workflow (valid, unknown, detailed steps, required flags, PCB workflow)

## Task Commits

1. **Task 1: Workflow templates + MCP meta-tools** - `aca5923` (feat)

## Files Created/Modified
- `src/kicad_agent/ops/workflows.py` - Added full_pcb_layout and convert_legacy_schematic templates (8 total)
- `src/kicad_agent/mcp/edit_server.py` - Added list_workflows and get_workflow meta-tool definitions and dispatch handlers
- `tests/test_workflows.py` - Added TestWorkflowConflictFree class for conflict validation across all 8 workflows
- `tests/test_mcp/test_edit_server.py` - Added TestWorkflowDispatch class (6 tests), updated meta-tool count to 9

## Decisions Made
- `full_pcb_layout` does not include `update_pcb_from_schematic` because it requires external `kicad-cli` dependency that cannot be validated as an operation prerequisite
- `full_pcb_layout` does not include `drc_check` because it is an MCP meta-tool, not a registered operation -- DRC can be run separately via the MCP tool
- Workflow templates are read-only MCP tools -- they provide guidance to LLMs, not execution automation

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Removed drc_check from full_pcb_layout workflow**
- **Found during:** Task 1 (adding full_pcb_layout workflow)
- **Issue:** `drc_check` is an MCP meta-tool name, not a registered operation in OPERATION_REGISTRY
- **Fix:** Replaced with `analyze_split_plane` (registered read-only operation) as optional final step
- **Files modified:** src/kicad_agent/ops/workflows.py
- **Verification:** TestWorkflowStepOpTypes parametrized test passes for full_pcb_layout

**2. [Rule 1 - Bug] Removed update_pcb_from_schematic from full_pcb_layout workflow**
- **Found during:** Task 1 (dependency chain validation)
- **Issue:** `update_pcb_from_schematic` requires `kicad-cli` (external tool dependency), not a registered operation prerequisite
- **Fix:** Removed from workflow; schematic-to-PCB sync is a separate explicit step users run via MCP
- **Files modified:** src/kicad_agent/ops/workflows.py
- **Verification:** TestWorkflowDependencyChains test passes for full_pcb_layout

---

**Total deviations:** 2 auto-fixed (both Rule 1 - bugs in workflow step composition)
**Impact on plan:** Minor adjustments to workflow composition; 8 templates delivered as planned.

## Issues Encountered
None beyond the above auto-fixes.

## Next Phase Readiness
- 8 workflow templates available for LLM-guided operation sequencing
- MCP meta-tools provide workflow discovery (list_workflows) and detail (get_workflow)
- All workflows validated against dependency graph and conflict detection
- Ready for downstream phases using workflow-aware operation planning

---
*Phase: 73-workflow-templates*
*Completed: 2026-06-06*
