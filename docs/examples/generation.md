# Generation Examples

Walk through template board generation, iterative refinement, and manufacturing export.

## Template Board Generation

Generate a PCB from a template specification.

```python
from kicad_agent.generation import generate_board

# Generate from a template specification
spec = {
    "template": "motor-driver",
    "components": [
        {"library_id": "Device:R_Small_US", "value": "10k", "reference": "R1"},
        {"library_id": "Device:C_Small", "value": "100nF", "reference": "C1"},
    ],
    "nets": [
        {"name": "VCC", "pins": ["R1.1", "C1.1"]},
        {"name": "GND", "pins": ["R1.2", "C1.2"]},
    ]
}

result = generate_board(spec, project_dir="/path/to/project")
```

## LLM-Driven Design Critique

Use an LLM to critique and refine a generated design.

```python
from kicad_agent.generation import critique_design

# Critique a design and get improvement suggestions
findings = critique_design(
    design_path="/path/to/board.kicad_pcb",
    requirements="Motor driver with H-bridge, 12V supply, PWM control"
)

for finding in findings:
    print(f"[{finding.severity}] {finding.message}")
```

The design critic evaluates:

- Component placement合理性
- Net connectivity completeness
- Power supply decoupling
- Signal integrity concerns
- Manufacturing constraints

## Iterative Refinement

The generation pipeline supports iterative refinement where the LLM critiques the design, fixes are applied, and the cycle repeats until convergence.

```python
from kicad_agent.generation import refine_design

result = refine_design(
    design_path="/path/to/board.kicad_pcb",
    max_iterations=5,
    convergence_threshold=0.9
)

print(f"Converged: {result.converged}")
print(f"Iterations: {result.iterations}")
print(f"Final quality score: {result.quality_score}")
```

## Manufacturing Export

Export manufacturing artifacts from a completed design.

```python
from kicad_agent.export import export_gerbers, export_bom

# Generate Gerber files
gerber_result = export_gerbers(
    pcb_path="/path/to/board.kicad_pcb",
    output_dir="/path/to/gerbers/"
)

# Generate bill of materials
bom_result = export_bom(
    schematic_path="/path/to/board.kicad_sch",
    output_path="/path/to/bom.csv"
)
```

### Gerber output includes

- Copper layers (F.Cu, B.Cu, Inner layers)
- Silkscreen (F.SilkS, B.SilkS)
- Solder mask (F.Mask, B.Mask)
- Solder paste (F.Paste, B.Paste)
- Edge cuts
- Drill files

### BOM output includes

- Reference designators
- Component values
- Footprint assignments
- Quantity per value
