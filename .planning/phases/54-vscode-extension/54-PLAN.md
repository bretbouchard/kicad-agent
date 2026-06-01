# Phase 54: VS Code Extension

**Score Impact:** Workflow Integration 9 -> 10
**Requirement:** WORKFLOW-01
**Depends On:** Phase 49-01 (MCP edit server stable API)

---

## Objective

Build a VS Code extension that connects to the existing kicad-agent MCP edit server, providing KiCad file editing with AI assistance directly in the editor. Zero new MCP tools -- reuse the existing 60+ dynamic tools from `edit_server.py`.

---

## Why

The MCP edit server (`edit_server.py`) exposes 60+ dynamically generated tools via stdio transport. Currently, the only way to use these is through Claude Desktop or raw MCP client calls. A VS Code extension would:

1. Provide right-click context menu actions for common KiCad workflows
2. Offer command palette integration for ERC, DRC, and visualization
3. Show a sidebar panel with operation history and ERC reports
4. Auto-run ERC on file save via file watcher
5. Lower the barrier to entry for hardware engineers already using VS Code

The extension is a thin TypeScript client -- all intelligence lives in the existing MCP server. This keeps the extension maintainable and ensures feature parity with any MCP client.

---

## Plans

| Plan | Description | Files | Est. Tasks |
|------|-------------|-------|------------|
| [54-01](./54-01-PLAN.md) | VS Code extension with MCP integration | `extension.ts`, `mcpClient.ts`, `operations.ts` | 3 |

---

## Success Criteria

- VS Code extension installs and activates for `.kicad_sch` / `.kicad_pcb` files
- Right-click context menus for "Fix ERC violations" and "Suggest improvements"
- Command palette commands for ERC, DRC, visualization
- Sidebar panel showing operation history and ERC report
- File watcher triggers ERC on `.kicad_sch` save
- Extension packaged as `.vsix` via `vsce`
- All MCP client logic tested with vitest
