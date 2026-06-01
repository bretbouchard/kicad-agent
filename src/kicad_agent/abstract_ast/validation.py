"""Circuit validation with cross-model invariant checks.

Validates AbstractCircuit instances for common errors:
- Duplicate component references
- Dangling pin references in nets (missing components or pins)
- Single-pin nets (likely incomplete connections)
- Empty circuits
"""

from __future__ import annotations

from dataclasses import dataclass

from kicad_agent.abstract_ast.models import AbstractCircuit, AbstractComponent


@dataclass(frozen=True)
class ValidationIssue:
    """A single validation finding."""

    severity: str  # "error" or "warning"
    category: str  # "duplicate_ref", "dangling_pin", "single_pin_net", "empty_circuit"
    description: str
    component_ref: str | None = None
    net_name: str | None = None


class CircuitValidator:
    """Validates cross-model invariants on an AbstractCircuit.

    Checks:
    - Unique component references within circuit and each sheet
    - Net pin_refs reference existing components and pins
    - Warns on single-pin nets (likely incomplete)
    - Warns on empty circuits
    """

    @staticmethod
    def validate(circuit: AbstractCircuit) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []

        # Check empty circuit
        total_components = len(circuit.components) + sum(
            len(s.components) for s in circuit.sheets
        )
        if total_components == 0:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    category="empty_circuit",
                    description="Circuit has no components",
                )
            )

        # Check unique refs in top-level components
        issues.extend(_check_unique_refs(circuit.components, "circuit top level"))

        # Check unique refs per sheet
        for sheet in circuit.sheets:
            issues.extend(_check_unique_refs(sheet.components, f"sheet '{sheet.name}'"))

        # Build ref -> component index for pin ref checking
        all_components = {c.ref: c for c in circuit.components}
        for sheet in circuit.sheets:
            for c in sheet.components:
                all_components[c.ref] = c

        # Check net pin refs
        all_nets = list(circuit.nets)
        for sheet in circuit.sheets:
            all_nets.extend(sheet.nets)

        for net in all_nets:
            if len(net.pin_refs) == 1:
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        category="single_pin_net",
                        description=f"Net '{net.name}' has only 1 pin connection",
                        net_name=net.name,
                    )
                )

            for ref, pin_number in net.pin_refs:
                if ref not in all_components:
                    issues.append(
                        ValidationIssue(
                            severity="error",
                            category="dangling_pin",
                            description=(
                                f"Net '{net.name}' references non-existent "
                                f"component '{ref}'"
                            ),
                            component_ref=ref,
                            net_name=net.name,
                        )
                    )
                else:
                    comp = all_components[ref]
                    pin_numbers = {p.number for p in comp.pins}
                    if pin_numbers and pin_number not in pin_numbers:
                        issues.append(
                            ValidationIssue(
                                severity="error",
                                category="dangling_pin",
                                description=(
                                    f"Net '{net.name}' references pin "
                                    f"'{pin_number}' on '{ref}', but component "
                                    f"has pins: {sorted(pin_numbers)}"
                                ),
                                component_ref=ref,
                                net_name=net.name,
                            )
                        )

        return issues


def _check_unique_refs(
    components: list[AbstractComponent], location: str
) -> list[ValidationIssue]:
    """Check for duplicate component references."""
    issues: list[ValidationIssue] = []
    seen: dict[str, int] = {}
    for comp in components:
        if comp.ref in seen:
            issues.append(
                ValidationIssue(
                    severity="error",
                    category="duplicate_ref",
                    description=(
                        f"Duplicate ref '{comp.ref}' in {location} "
                        f"(occurrences: {seen[comp.ref] + 1}+)"
                    ),
                    component_ref=comp.ref,
                )
            )
        seen[comp.ref] = seen.get(comp.ref, 0) + 1
    return issues
