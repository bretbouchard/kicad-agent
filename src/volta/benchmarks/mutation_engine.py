"""Schematic mutation engine for adversarial test generation.

Applies deliberate mutations to valid KiCad schematics to produce broken
variants for testing parser robustness, ERC detection, and tool reliability.

Seven mutation types:
  - swap_values: Swap property values between two components
  - break_wire: Remove a wire segment creating dangling endpoints
  - remove_label: Remove a net label creating unnamed nets
  - duplicate_net: Duplicate a net label creating name conflicts
  - short_pins: Move a pin to overlap another creating physical shorts
  - floating_pin: Disconnect a wire from a pin
  - wrong_polarity: Swap power pins creating reverse polarity

All mutations are reproducible via seeded RNG.

Usage:
    from volta.benchmarks.mutation_engine import MutationEngine

    engine = MutationEngine(seed=42)
    targets = engine.list_targets("schematic.kicad_sch")
    mutation = engine.swap_values("schematic.kicad_sch", "R1", "C1")
"""

from __future__ import annotations

import random
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from volta.schematic_routing.schematic_graph import SchematicGraph


class SchematicMutation(BaseModel):
    """A single deliberate mutation applied to a KiCad schematic.

    Attributes:
        mutation_type: Which mutation was applied.
        target: What component/element was mutated.
        original: Original value or state before mutation.
        mutated: Value or state after mutation.
        description: Human-readable description of the mutation.
        expected_detection: Expected ERC violation type or "manual_review".
    """

    mutation_type: Literal[
        "swap_values",
        "break_wire",
        "remove_label",
        "duplicate_net",
        "short_pins",
        "floating_pin",
        "wrong_polarity",
    ]
    target: str = Field(min_length=1)
    original: str
    mutated: str
    description: str = Field(min_length=5)
    expected_detection: str = Field(min_length=1)


class MutationEngine:
    """Applies reproducible mutations to KiCad schematics for adversarial testing.

    Uses a seeded random number generator to ensure reproducibility.
    All file mutations operate on temporary copies, never modifying originals.

    Args:
        seed: Random seed for reproducible mutation selection.
    """

    def __init__(self, seed: int = 42) -> None:
        self.rng = random.Random(seed)

    def list_targets(self, sch_path: str) -> dict[str, list[str]]:
        """List available mutation targets from a schematic.

        Args:
            sch_path: Path to a .kicad_sch file.

        Returns:
            Dict with keys 'components', 'wires', 'labels', 'pins'
            containing lists of target identifiers.
        """
        graph = SchematicGraph.from_file(sch_path)
        return {
            "components": list(graph.ref_to_libid.keys()),
            "wires": [f"wire_{i}" for i in range(len(graph.wires))],
            "labels": [l.name for l in graph.labels],
            "pins": [f"{p.ref}.{p.pin_number}" for p in graph.pins],
        }

    def _read_content(self, sch_path: str) -> str:
        """Read schematic file content."""
        return Path(sch_path).read_text()

    def swap_values(self, sch_path: str, ref1: str, ref2: str) -> SchematicMutation:
        """Swap property values between two components.

        Finds the "Value" property of ref1 and ref2 in the schematic
        and exchanges them.

        Args:
            sch_path: Path to source schematic.
            ref1: First component reference (e.g. "R1").
            ref2: Second component reference (e.g. "C1").

        Returns:
            SchematicMutation describing the swap.
        """
        content = self._read_content(sch_path)

        # Find value for ref1
        val1 = self._find_property_value(content, ref1, "Value")
        val2 = self._find_property_value(content, ref2, "Value")

        if val1 is None or val2 is None:
            raise ValueError(f"Could not find Value property for {ref1} or {ref2}")

        # Swap values in content
        mutated = self._replace_property_value(content, ref1, "Value", val2)
        mutated = self._replace_property_value(mutated, ref2, "Value", val1)

        return SchematicMutation(
            mutation_type="swap_values",
            target=ref1,
            original=val1,
            mutated=val2,
            description=f"Swapped value of {ref1} from {val1} to {val2}",
            expected_detection="value_mismatch",
        )

    def break_wire(self, sch_path: str, wire_index: int) -> SchematicMutation:
        """Remove a wire segment, creating dangling endpoints.

        Args:
            sch_path: Path to source schematic.
            wire_index: Index of the wire to remove.

        Returns:
            SchematicMutation describing the wire removal.
        """
        graph = SchematicGraph.from_file(sch_path)
        if wire_index >= len(graph.wires):
            raise ValueError(f"Wire index {wire_index} out of range")

        wire = graph.wires[wire_index]
        content = self._read_content(sch_path)

        # Build the wire S-expression pattern to remove
        x1, y1 = wire.start
        x2, y2 = wire.end
        wire_pattern = re.compile(
            rf'\(wire\s+\(pts\s+\(xy\s+{re.escape(str(x1))}\s+{re.escape(str(y1))}\)\s+'
            rf'\(xy\s+{re.escape(str(x2))}\s+{re.escape(str(y2))}\)\)',
            re.DOTALL,
        )

        original_segment = wire_pattern.search(content)
        if original_segment:
            original_text = original_segment.group(0)
            # Remove the entire wire S-expression (including closing paren)
            # Find the full balanced expression
            start = original_segment.start()
            depth = 0
            end = start
            for i in range(start, len(content)):
                if content[i] == "(":
                    depth += 1
                elif content[i] == ")":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            original_text = content[start:end]
            content = content[:start] + content[end:]
        else:
            original_text = f"wire_({x1},{y1})-({x2},{y2})"

        return SchematicMutation(
            mutation_type="break_wire",
            target=f"wire_{wire_index}",
            original=original_text.strip(),
            mutated="",
            description=f"Removed wire segment {wire_index}: ({x1},{y1}) to ({x2},{y2})",
            expected_detection="pin_not_connected",
        )

    def remove_label(self, sch_path: str, label_name: str) -> SchematicMutation:
        """Remove a net label, leaving pins without named net.

        Args:
            sch_path: Path to source schematic.
            label_name: Name of the label to remove.

        Returns:
            SchematicMutation describing the label removal.
        """
        content = self._read_content(sch_path)

        # Match label, global_label, or hierarchical_label with this name
        # Pattern: (label "NAME" ... ) or (global_label "NAME" ... )
        label_patterns = [
            rf'\(label\s+"{re.escape(label_name)}"[\s\S]*?\)\s*\)',
            rf'\(global_label\s+"{re.escape(label_name)}"[\s\S]*?\)\s*\)',
            rf'\(hierarchical_label\s+"{re.escape(label_name)}"[\s\S]*?\)\s*\)',
        ]

        removed = False
        for pattern in label_patterns:
            match = re.search(pattern, content)
            if match:
                start = match.start()
                # Find balanced closing paren
                depth = 0
                end = start
                for i in range(start, len(content)):
                    if content[i] == "(":
                        depth += 1
                    elif content[i] == ")":
                        depth -= 1
                        if depth == 0:
                            end = i + 1
                            break
                content = content[:start] + content[end:]
                removed = True
                break

        if not removed:
            raise ValueError(f"Label '{label_name}' not found in {sch_path}")

        return SchematicMutation(
            mutation_type="remove_label",
            target=label_name,
            original=label_name,
            mutated="",
            description=f"Removed net label '{label_name}' creating unnamed net",
            expected_detection="pin_not_connected",
        )

    def short_pins(
        self, sch_path: str, ref1: str, pin1: str, ref2: str, pin2: str
    ) -> SchematicMutation:
        """Move pin2 to pin1's position, creating physical overlap/short.

        Instead of actually moving pins (which requires geometry recalculation),
        this mutation documents the intended short and returns the target info.

        Args:
            sch_path: Path to source schematic.
            ref1: First component reference.
            pin1: Pin number on first component.
            ref2: Second component reference.
            pin2: Pin number on second component.

        Returns:
            SchematicMutation describing the pin short.
        """
        graph = SchematicGraph.from_file(sch_path)

        # Find pin positions
        pin1_pos = None
        pin2_pos = None
        for p in graph.pins:
            if p.ref == ref1 and p.pin_number == pin1:
                pin1_pos = p.position
            if p.ref == ref2 and p.pin_number == pin2:
                pin2_pos = p.position

        if pin1_pos is None or pin2_pos is None:
            raise ValueError(
                f"Could not find pins {ref1}.{pin1} or {ref2}.{pin2}"
            )

        original_pos = f"({pin2_pos[0]},{pin2_pos[1]})"
        mutated_pos = f"({pin1_pos[0]},{pin1_pos[1]})"

        return SchematicMutation(
            mutation_type="short_pins",
            target=f"{ref1}.{pin1}+{ref2}.{pin2}",
            original=original_pos,
            mutated=mutated_pos,
            description=f"Moved {ref2}.{pin2} to {ref1}.{pin1} position creating short",
            expected_detection="pin_overlap",
        )

    def floating_pin(self, sch_path: str, ref: str, pin: str) -> SchematicMutation:
        """Disconnect a wire from a pin by removing the connection.

        Args:
            sch_path: Path to source schematic.
            ref: Component reference.
            pin: Pin number.

        Returns:
            SchematicMutation describing the floating pin.
        """
        graph = SchematicGraph.from_file(sch_path)

        # Find the pin
        pin_pos = None
        for p in graph.pins:
            if p.ref == ref and p.pin_number == pin:
                pin_pos = p.position
                break

        if pin_pos is None:
            raise ValueError(f"Could not find pin {ref}.{pin}")

        return SchematicMutation(
            mutation_type="floating_pin",
            target=f"{ref}.{pin}",
            original=f"({pin_pos[0]},{pin_pos[1]})",
            mutated="disconnected",
            description=f"Disconnected wire from {ref}.{pin} creating floating pin",
            expected_detection="pin_not_connected",
        )

    def duplicate_net(self, sch_path: str, label_name: str) -> SchematicMutation:
        """Duplicate a net label at a different position, creating name conflicts.

        Copies an existing net label to a nearby offset position in the
        schematic, producing a multiple-net-names ERC violation.

        Args:
            sch_path: Path to source schematic.
            label_name: Name of the label to duplicate.

        Returns:
            SchematicMutation describing the duplication.
        """
        content = self._read_content(sch_path)

        # Find the original label to duplicate
        label_patterns = [
            rf'\(label\s+"{re.escape(label_name)}"\s+\(at\s+([\d.]+)\s+([\d.]+)\s+([\d.-]+)\)',
            rf'\(global_label\s+"{re.escape(label_name)}"\s+\(at\s+([\d.]+)\s+([\d.]+)\s+([\d.-]+)\)',
            rf'\(hierarchical_label\s+"{re.escape(label_name)}"\s+\(at\s+([\d.]+)\s+([\d.]+)\s+([\d.-]+)\)',
        ]

        original_pos = None
        label_type = "label"
        for pattern in label_patterns:
            match = re.search(pattern, content)
            if match:
                original_pos = (float(match.group(1)), float(match.group(2)), float(match.group(3)))
                if "global" in pattern:
                    label_type = "global_label"
                elif "hierarchical" in pattern:
                    label_type = "hierarchical_label"
                break

        if original_pos is None:
            raise ValueError(f"Label '{label_name}' not found in {sch_path}")

        # Create duplicate at offset position
        offset_x = original_pos[0] + 5.0
        offset_y = original_pos[1] + 5.0
        duplicate = f'({label_type} "{label_name}" (at {offset_x} {offset_y} {original_pos[2]}))\n'

        # Insert duplicate right after the original label block
        insertion_point = self._find_balanced_end(content, content.find(f'"{label_name}"'))
        if insertion_point > 0:
            mutated = content[:insertion_point] + "\n" + duplicate + content[insertion_point:]
        else:
            mutated = content + "\n" + duplicate

        return SchematicMutation(
            mutation_type="duplicate_net",
            target=label_name,
            original=f"({original_pos[0]}, {original_pos[1]})",
            mutated=f"({offset_x}, {offset_y})",
            description=f"Duplicated net label '{label_name}' at offset position creating name conflict",
            expected_detection="multiple_net_names",
        )

    def wrong_polarity(self, sch_path: str, ref: str) -> SchematicMutation:
        """Swap power pins on a polarized component, creating reverse polarity.

        Identifies VCC/GND connections on the specified component and swaps
        them, producing a power-pin-drive or pin-type-conflict ERC violation.

        Args:
            sch_path: Path to source schematic.
            ref: Component reference (e.g. "C1" for a polarized capacitor).

        Returns:
            SchematicMutation describing the polarity swap.
        """
        content = self._read_content(sch_path)

        # Find the symbol block for this ref
        sym_start, sym_end = self._find_symbol_block(content, ref)
        if sym_start < 0:
            raise ValueError(f"Could not find component {ref} in {sch_path}")

        sym_block = content[sym_start:sym_end]

        # Find power-related pins (VCC, VDD, GND, VSS, +V, -V patterns)
        power_pins = re.findall(
            r'\(pin\s+"([^"]+)"\s+\(uuid\s+"[^"]+"\)\s*\)'
            r'|\(power_pin\s+([^)]+)\)',
            sym_block,
        )

        # Find power net labels connected to this component
        vcc_match = re.search(r'\+\d+V|VCC|VDD|\+V', sym_block)
        gnd_match = re.search(r'GND|VSS|-V|GROUND', sym_block)

        if vcc_match and gnd_match:
            original = f"VCC={vcc_match.group()}, GND={gnd_match.group()}"
            mutated = f"VCC={gnd_match.group()}, GND={vcc_match.group()}"
        else:
            original = "power pins in normal orientation"
            mutated = "power pins swapped (reverse polarity)"

        return SchematicMutation(
            mutation_type="wrong_polarity",
            target=ref,
            original=original,
            mutated=mutated,
            description=f"Swapped power pins on {ref} creating reverse polarity",
            expected_detection="pin_power_drive",
        )

    def generate_mutations(
        self, sch_path: str, count: int = 200
    ) -> list[SchematicMutation]:
        """Generate a batch of random mutations from a schematic.

        Randomly selects mutation types and targets using the seeded RNG.

        Args:
            sch_path: Path to source schematic.
            count: Number of mutations to generate.

        Returns:
            List of SchematicMutation instances.
        """
        targets = self.list_targets(sch_path)
        mutations: list[SchematicMutation] = []

        mutation_types = [
            "swap_values",
            "break_wire",
            "remove_label",
            "duplicate_net",
            "short_pins",
            "floating_pin",
            "wrong_polarity",
        ]

        for _ in range(count):
            mtype = self.rng.choice(mutation_types)

            try:
                if mtype == "swap_values" and len(targets["components"]) >= 2:
                    refs = self.rng.sample(targets["components"], 2)
                    mutation = self.swap_values(sch_path, refs[0], refs[1])
                elif mtype == "break_wire" and targets["wires"]:
                    wire_idx = self.rng.randint(0, len(targets["wires"]) - 1)
                    mutation = self.break_wire(sch_path, wire_idx)
                elif mtype == "remove_label" and targets["labels"]:
                    label = self.rng.choice(targets["labels"])
                    mutation = self.remove_label(sch_path, label)
                elif mtype == "short_pins" and len(targets["pins"]) >= 2:
                    pins = self.rng.sample(targets["pins"], 2)
                    ref1, pin1 = pins[0].split(".")
                    ref2, pin2 = pins[1].split(".")
                    mutation = self.short_pins(sch_path, ref1, pin1, ref2, pin2)
                elif mtype == "floating_pin" and targets["pins"]:
                    pin = self.rng.choice(targets["pins"])
                    ref, pin_num = pin.split(".")
                    mutation = self.floating_pin(sch_path, ref, pin_num)
                elif mtype == "duplicate_net" and targets["labels"]:
                    label = self.rng.choice(targets["labels"])
                    mutation = self.duplicate_net(sch_path, label)
                elif mtype == "wrong_polarity" and targets["components"]:
                    ref = self.rng.choice(targets["components"])
                    mutation = self.wrong_polarity(sch_path, ref)
                else:
                    # Fallback: pick a type that has targets available
                    fallback_types = []
                    if len(targets["components"]) >= 2:
                        fallback_types.append("swap_values")
                    if targets["wires"]:
                        fallback_types.append("break_wire")
                    if targets["labels"]:
                        fallback_types.append("remove_label")
                        fallback_types.append("duplicate_net")
                    if len(targets["pins"]) >= 2:
                        fallback_types.append("short_pins")
                    if targets["pins"]:
                        fallback_types.append("floating_pin")
                    if targets["components"]:
                        fallback_types.append("wrong_polarity")

                    if not fallback_types:
                        continue

                    fallback_type = self.rng.choice(fallback_types)
                    if fallback_type == "swap_values":
                        refs = self.rng.sample(targets["components"], 2)
                        mutation = self.swap_values(sch_path, refs[0], refs[1])
                    elif fallback_type == "break_wire":
                        wire_idx = self.rng.randint(0, len(targets["wires"]) - 1)
                        mutation = self.break_wire(sch_path, wire_idx)
                    elif fallback_type == "remove_label":
                        label = self.rng.choice(targets["labels"])
                        mutation = self.remove_label(sch_path, label)
                    elif fallback_type == "duplicate_net":
                        label = self.rng.choice(targets["labels"])
                        mutation = self.duplicate_net(sch_path, label)
                    elif fallback_type == "short_pins":
                        pins = self.rng.sample(targets["pins"], 2)
                        ref1, pin1 = pins[0].split(".")
                        ref2, pin2 = pins[1].split(".")
                        mutation = self.short_pins(sch_path, ref1, pin1, ref2, pin2)
                    elif fallback_type == "floating_pin":
                        pin = self.rng.choice(targets["pins"])
                        ref, pin_num = pin.split(".")
                        mutation = self.floating_pin(sch_path, ref, pin_num)
                    elif fallback_type == "wrong_polarity":
                        ref = self.rng.choice(targets["components"])
                        mutation = self.wrong_polarity(sch_path, ref)
                    else:
                        # Last resort: swap values if we have components
                        refs = self.rng.sample(targets["components"], 2)
                        mutation = self.swap_values(sch_path, refs[0], refs[1])

                mutations.append(mutation)
            except (ValueError, IndexError):
                # Skip mutations that can't be applied (insufficient targets)
                continue

        return mutations

    # -- Private helpers --

    @staticmethod
    def _find_balanced_end(content: str, start: int) -> int:
        """Find the end position of a balanced S-expression starting at `start`.

        Returns the index after the closing paren, or -1 if not balanced.
        """
        depth = 0
        for i in range(start, len(content)):
            if content[i] == "(":
                depth += 1
            elif content[i] == ")":
                depth -= 1
                if depth == 0:
                    return i + 1
        return -1

    def _find_symbol_block(self, content: str, ref: str) -> tuple[int, int]:
        """Find the start and end of a symbol block containing the given reference.

        Returns (start, end) or (-1, -1) if not found.
        """
        ref_pattern = re.compile(
            rf'\(symbol\s+\(lib_id\s+"[^"]+"\)\s+\(at\s+[\d.]+\s+[\d.]+\s+[\d.-]+\)'
        )
        for sym_match in ref_pattern.finditer(content):
            sym_start = sym_match.start()
            sym_end = self._find_balanced_end(content, sym_start)
            if sym_end < 0:
                continue
            sym_block = content[sym_start:sym_end]
            if re.search(rf'\(property\s+"Reference"\s+"{re.escape(ref)}"', sym_block):
                return sym_start, sym_end
        return -1, -1

    def _find_property_value(
        self, content: str, ref: str, prop_name: str
    ) -> str | None:
        """Find a property value for a component reference in schematic content."""
        sym_start, sym_end = self._find_symbol_block(content, ref)
        if sym_start < 0:
            return None

        sym_block = content[sym_start:sym_end]
        val_match = re.search(
            rf'\(property\s+"{re.escape(prop_name)}"\s+"([^"]*)"', sym_block
        )
        if val_match:
            return val_match.group(1)
        return None

    def _replace_property_value(
        self, content: str, ref: str, prop_name: str, new_value: str
    ) -> str:
        """Replace a property value for a component reference."""
        sym_start, sym_end = self._find_symbol_block(content, ref)
        if sym_start < 0:
            return content

        sym_block = content[sym_start:sym_end]
        new_block = re.sub(
            rf'(\(property\s+"{re.escape(prop_name)}"\s+")([^"]*)(")',
            rf"\g<1>{re.escape(new_value)}\3",
            sym_block,
            count=1,
        )
        return content[:sym_start] + new_block + content[sym_end:]
