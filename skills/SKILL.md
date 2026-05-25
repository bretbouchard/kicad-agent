---
name: kicad-agent
description: "AI-safe structural editing of KiCad schematic, PCB, symbol library, and footprint files via JSON operations. Use when editing any KiCad 10+ file (.kicad_sch, .kicad_pcb, .kicad_sym, .kicad_mod), analyzing component/net/footprint state, or running ERC/DRC validation. Invoked as /kicad-agent."
argument-hint: "[operation JSON | status | context | help]"
user_invocable: true
allowed-tools:
  - Read
  - Bash
  - Write
  - Edit
  - Grep
  - Glob
---

<objective>
Bridge between Claude and the kicad-agent Python backend for AI-safe KiCad file editing. Claude constructs JSON operations conforming to the Pydantic operation schema; the skill handler validates them against the schema and executes via the kicad-agent Python library. The LLM never touches raw S-expressions -- it emits structured intents, and the Python tool layer mutates the AST, serializes valid KiCad files, and validates via ERC/DRC gates.

Architecture: LLM -> intent JSON -> AST mutation -> validated KiCad file. Zero corruption, every time.
</objective>

<process>

## Step 0: Load prompt template

Read `prompt.md` from the same directory as this file. It contains the full operation reference with field descriptions, JSON examples, and constraints. Use it to construct valid operations.

## Step 1: Parse $ARGUMENTS

Determine the user's intent:

- **"help"** -- Print available operations from prompt.md. List all 19 operation types with brief descriptions.
- **"status"** -- Report current project context. Look for KiCad files in the working directory and summarize what was found (schematic, PCB, symbol libs, footprint libs).
- **"context"** -- Render a project summary. Parse any .kicad_pro file found, list schematics, PCBs, and libraries with component counts.
- **JSON operation** -- Treat as an operation to execute. Must conform to the operation schema documented in prompt.md.

## Step 2: Validate the JSON operation

If the argument is a JSON operation, validate it against the Pydantic operation schema:

```bash
cd ~/apps/kicad-agent && python3 -c "
import json, sys
from kicad_agent.ops.schema import Operation
op = Operation.model_validate_json(sys.stdin.read())
print(json.dumps({'valid': True, 'op_type': op.root.op_type, 'target_file': op.root.target_file}))
" <<< '$OPERATION_JSON'
```

If validation fails, report the exact constraint violated and suggest corrections.

## Step 3: Execute the operation

Run the validated operation through the kicad-agent pipeline:

```bash
cd ~/apps/kicad-agent && python3 -c "
import json, sys
from kicad_agent.ops.schema import Operation
from kicad_agent.ops.executor import OperationExecutor
op = Operation.model_validate_json(sys.stdin.read())
executor = OperationExecutor(project_dir='.')
result = executor.execute(op)
print(json.dumps(result, indent=2))
" <<< '$OPERATION_JSON'
```

## Step 4: Format and display the result

Present the execution result to the user:
- Success: Confirm what changed, show the operation type and target file
- Failure: Show the error message with context about what constraint was violated
- Validation: If ERC/DRC was triggered, summarize pass/fail status

</process>

<context>
The full operation schema with field-level documentation, constraints, and JSON examples is in prompt.md in the same directory. Always consult it before constructing operations.

Supported file types: .kicad_sch (schematic), .kicad_pcb (PCB), .kicad_sym (symbol library), .kicad_mod (footprint library)
KiCad version: 10+ only
Position units: millimeters (mils not supported)
Operations are atomic: one mutation per operation, one target file per operation
