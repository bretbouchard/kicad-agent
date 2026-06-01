# Phase 51: Interactive Playground

## Overview

Elevate demo quality from 9 to 10 with a web-based playground for exploring kicad-agent operations without any local setup. Users upload KiCad files, select operations, see results in real-time with SVG previews and ERC/DRC reports -- all in a browser.

## Motivation

Phase 49 gives us `kicad-agent demo` for one-command output. Phase 50 gives us beautiful annotated SVGs and reports. But a CLI still requires local installation, KiCad dependency, and terminal comfort. A web playground removes all barriers: open a URL, upload a file, explore operations visually. This is the top-of-funnel demo that converts evaluators into users.

## Plans

| Plan | Title | Type | Depends On | Status |
|------|-------|------|------------|--------|
| 51-01 | Web Playground with FastAPI Backend | execute | 50-01 | Not started |

## Plan Details

### 51-01: Web Playground

FastAPI backend exposing operations as REST API, WebSocket for real-time feedback, and a static HTML/JS frontend with:
- File upload for KiCad schematics and PCBs
- Operation palette listing all available operations with schema
- SVG preview panel showing uploaded/modified files
- ERC/DRC report panel with annotated results
- Real-time operation execution feedback via WebSocket

Files: `src/kicad_agent/playground/app.py`, `src/kicad_agent/playground/api.py`, `src/kicad_agent/playground/static/`, `tests/test_playground.py`

## Requirements Coverage

| Requirement | Plan | Description |
|-------------|------|-------------|
| DEMO-03 | 51-01 | Interactive playground for exploring operations |

## Success Criteria

1. `kicad-agent playground` starts a local web server on port 8000
2. File upload accepts .kicad_sch and .kicad_pcb files
3. Operation palette lists all available operations with parameter schemas
4. SVG preview renders uploaded schematics
5. ERC/DRC operations produce annotated results visible in browser
6. WebSocket provides real-time execution feedback
7. No build step required -- vanilla HTML/JS frontend
8. File upload is secured against path traversal and size abuse

## Dependencies

- Phase 50 (visual output showcase) for SVG annotation
- Phase 30 (MCP operations server) for operation schema exposure
- Phase 7 (GSD skill integration) for handler/operation infrastructure
- Phase 49 (one-command demo) for demo template showcase
