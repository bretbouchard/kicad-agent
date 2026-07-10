# Plan: Doc Naming Disambiguation Convention + Hook

## Context

Projects with multiple analogs/sections produce duplicate doc filenames. Example: analog-ecosystem has 11 files all named `CARTRIDGE-DESIGN.md` across different cartridge subdirectories. This makes search, editor tabs, and cross-referencing confusing. We need a convention agents follow automatically, enforced by a hook so no agent has to "remember."

## Approach

Two pieces: **rule file** (tells agents the convention) + **hook** (enforces it involuntarily).

---

## Piece 1: Convention Rule

**New file:** `~/.claude/rules/doc-naming.md`

Content:
```
# Doc Naming — Disambiguation Convention

When a project has multiple analogs/sections producing the same doc filename, append the analog slug:

CARTRIDGE-DESIGN.md      → CARTRIDGE-DESIGN-rat-overdrive.md
CARTRIDGE-DESIGN.md      → CARTRIDGE-DESIGN-synth-machine.md

## Rules

1. Derive the slug from the parent directory name (the section/analog folder)
2. Only append when a file with that basename already exists in a sibling directory
3. If only one section produces that doc name, no suffix needed
4. Slug format: lowercase, hyphens preserved (match directory name exactly)
5. Separator: single hyphen before slug

## Examples

hardware/dumb-cartridges/rat-overdrive/CARTRIDGE-DESIGN.md
  → CARTRIDGE-DESIGN-rat-overdrive.md

hardware/dumb-cartridges/synth-machine/CARTRIDGE-DESIGN.md
  → CARTRIDGE-DESIGN-synth-machine.md

docs/CARTRIDGE-DESIGN.md  (only one exists)
  → CARTRIDGE-DESIGN.md  (no suffix needed)

## Where This Applies

- `docs/` directory
- `.planning/` directory (phase docs across sections)
- Any project directory with multiple analogs/sections
- Does NOT apply to: README.md, CLAUDE.md, AGENTS.md, CONTRIBUTING.md, STATE.md
```

---

## Piece 2: Hook Enforcement

**Modify:** `~/.claude/settings.json` — add a new PreToolUse hook entry after the existing doc blocker (line 110)

**Matcher:** Triggers on `Write` to `.md` files in allowed directories (`docs/`, `.planning/`, `plans/`, or within project subdirectories)

**Script:** `~/.claude/hooks/doc-name-dedup.py` — Python script that:
1. Reads the target file path from stdin (JSON)
2. Extracts the basename (e.g., `CARTRIDGE-DESIGN.md`)
3. Gets the parent directory
4. Scans sibling directories for files with the same basename
5. If duplicates found → prints `[DOC-DEDUP] WARNING` with suggested names, exits 1 (blocks)
6. If no duplicates → exits 0 (allows)

**Key behaviors:**
- Advisory-only mode first: prints warning but exits 0 (doesn't block). This lets us tune the detection before making it a hard gate.
- Skips well-known files (README.md, CLAUDE.md, etc.)
- Uses parent directory name as the suggested slug
- Scans only immediate siblings (not recursive) for performance

### Hook entry in settings.json

```json
{
  "matcher": "tool == \"Write\" && tool_input.file_path matches \"\\\\.(md|txt)$\" && !(tool_input.file_path matches \"README\\\\.md|CLAUDE\\\\.md|AGENTS\\\\.md|CONTRIBUTING\\\\.md|STATE\\.md\") && (tool_input.file_path matches \"/docs/\" || tool_input.file_path matches \"\\.planning/\" || tool_input.file_path matches \"/plans/\")",
  "hooks": [
    {
      "type": "command",
      "command": "python3 \"$HOME/.claude/hooks/doc-name-dedup.py\""
    }
  ]
}
```

### Script: `~/.claude/hooks/doc-name-dedup.py`

```python
#!/usr/bin/env python3
"""
DOC-DEDUP: Warns when a doc filename duplicates a sibling directory's file.
Suggests disambiguated name using parent directory as slug.

Mode: ADVISORY (warning only, does not block)
"""
import json
import sys
import os
from pathlib import Path

# Files exempt from dedup check
EXEMPT_BASENAMES = {
    "README.md", "CLAUDE.md", "AGENTS.md", "CONTRIBUTING.md",
    "STATE.md", "PROJECT.md", "REQUIREMENTS.md", "ROADMAP.md",
    "_MANIFEST.md", "MEMORY.md", "SUMMARY.md", "PLAN.md"
}

def main():
    try:
        input_data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    tool_input = input_data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    if not file_path:
        sys.exit(0)

    path = Path(file_path)
    basename = path.name

    # Skip exempt files
    if basename in EXEMPT_BASENAMES:
        sys.exit(0)

    parent = path.parent
    if not parent.exists():
        sys.exit(0)

    # Scan sibling directories for same basename
    grandparent = parent.parent
    if not grandparent.exists():
        sys.exit(0)

    duplicates = []
    for sibling in grandparent.iterdir():
        if sibling.is_dir() and sibling != parent:
            candidate = sibling / basename
            if candidate.exists():
                duplicates.append(sibling.name)

    if duplicates:
        slug = parent.name  # e.g., "rat-overdrive"
        suggested = f"{path.stem}-{slug}{path.suffix}"
        dup_list = ", ".join(duplicates[:3])
        if len(duplicates) > 3:
            dup_list += f" (+{len(duplicates)-3} more)"

        print(f"[DOC-DEDUP] WARNING: '{basename}' also exists in: {dup_list}", file=sys.stderr)
        print(f"[DOC-DEDUP] Suggested name: {suggested}", file=sys.stderr)
        print(f"[DOC-DEDUP] Rule: see rules/doc-naming.md", file=sys.stderr)
        # Advisory mode — exit 0 (doesn't block)
        sys.exit(0)

    sys.exit(0)

if __name__ == "__main__":
    main()
```

---

## Files to Create/Modify

| File | Action | Purpose |
|------|--------|---------|
| `~/.claude/rules/doc-naming.md` | **Create** | Convention rule agents follow |
| `~/.claude/hooks/doc-name-dedup.py` | **Create** | Hook script that detects duplicates |
| `~/.claude/settings.json` | **Modify** | Add hook entry after doc blocker |

---

## Verification

1. **Rule loads**: Start a new session, check that `rules/doc-naming.md` appears in context
2. **Hook fires in advisory mode**: Write a file named `CARTRIDGE-DESIGN.md` to a directory where a sibling has the same file — expect warning in stderr, write succeeds
3. **Hook doesn't false-positive**: Write a unique doc name — expect no warning
4. **Hook skips exempt files**: Write `README.md` — expect no warning
5. **Existing analog-ecosystem**: The hook would fire for each existing `CARTRIDGE-DESIGN.md` if any were newly created (doesn't retroactively rename existing files)

## Scope Decision

The plan does NOT retroactively rename existing files in analog-ecosystem. That's a separate task. This plan establishes the convention and enforcement going forward.
