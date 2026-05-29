# Operations

46 operation handlers, Pydantic-validated operation schema, and the operation executor.

The ops module defines the complete operation schema using Pydantic models and provides individual handlers for each operation type. Operations are atomic: one mutation per operation, one target file per operation.

::: kicad_agent.ops
    options:
      show_source: true
