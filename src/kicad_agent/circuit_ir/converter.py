"""KiCad → SKIDL converter.

Reads a .kicad_sch file, extracts components and nets,
and generates a Python build_*.py script using SKIDL.
"""

from __future__ import annotations
from pathlib import Path
from typing import Optional
from .parts_mapper import PartsMapper, MappedPart


class KiCadToSkidlConverter:
    """Converts a KiCad schematic to a SKIDL Python script."""
    
    def __init__(self):
        self.mapper = PartsMapper()
        self.components = []
        self.nets = []
        self.power_nets = set()
        self.diagnostics = []
    
    def convert(self, sch_path: str | Path, output_path: str | Path | None = None,
                level: str = "L1") -> str:
        """Convert a .kicad_sch to SKIDL Python code.
        
        Args:
            sch_path: Path to .kicad_sch file
            output_path: Where to write build_*.py (default: stdout)
            level: Representation level ("L1" pin-level, "L2" component-level)
        
        Returns:
            The generated Python code as a string.
        """
        sch_path = Path(sch_path)
        if not sch_path.exists():
            raise FileNotFoundError(f"Schematic not found: {sch_path}")
        
        # Use kicad-agent CLI for extract_nets (known-working path)
        import subprocess, json, os
        old_cwd = os.getcwd()
        os.chdir(str(sch_path.parent))
        try:
            cli_result = subprocess.run(
                ["kicad-agent", json.dumps({
                    "op_type": "extract_nets",
                    "target_file": sch_path.name
                })],
                capture_output=True, text=True, timeout=60
            )
        finally:
            os.chdir(old_cwd)
        
        # Parse the nets from the output
        nets_data = {}
        output_text = cli_result.stdout
        import re
        nets_match = re.search(r"nets:\s*(\{.*?\})\s*\n\s*stats:", output_text, re.DOTALL)
        if nets_match:
            try:
                nets_data = eval(nets_match.group(1))
            except:
                nets_data = {}
        
        # Extract components from the schematic
        components = self._extract_components(sch_path)
        
        # Generate SKIDL code
        from .emitter import SkidlEmitter
        emitter = SkidlEmitter()
        code = emitter.emit(
            board_name=sch_path.stem,
            components=components,
            nets=nets_data,
            power_nets=self.power_nets,
            level=level,
        )
        
        if output_path:
            Path(output_path).write_text(code)
        
        return code
    
    def _extract_components(self, sch_path: Path) -> list[dict]:
        """Extract component info from schematic."""
        import re
        
        content = sch_path.read_text()
        components = []
        
        # Find component instances (outside lib_symbols)
        lib_end = self._find_lib_symbols_end(content)
        after_lib = content[lib_end:]
        
        # Match lib_id + Reference + Value + Footprint
        # Schematic format: (symbol (lib_id "...") ... (property "Reference" "..." ...) (property "Value" "..." ...) (property "Footprint" "..." ...)
        lib_ids = re.findall(r'\(lib_id "([^"]+)"', after_lib)
        refs = re.findall(r'\(property "Reference" "([^"]+)"', after_lib)
        values = re.findall(r'\(property "Value" "([^"]*)"', after_lib)
        footprints = re.findall(r'\(property "Footprint" "([^"]*)"', after_lib)
        
        for i in range(min(len(lib_ids), len(refs), len(values), len(footprints))):
            lib_id = lib_ids[i]
            ref = refs[i]
            value = values[i]
            footprint = footprints[i]
            
            # Skip power flag references
            if ref.startswith("#PWR") or ref.startswith("#FLG"):
                continue
            
            # Map to SKIDL representation
            mapped = self.mapper.map(lib_id, value, footprint)
            
            if mapped.strategy == "power":
                self.power_nets.add(value)
                continue
            
            components.append({
                "ref": ref,
                "lib_id": lib_id,
                "value": value,
                "footprint": footprint,
                "mapped": mapped,
            })
        
        return components
    
    def _find_lib_symbols_end(self, content: str) -> int:
        """Find the end of the (lib_symbols) section."""
        idx = content.find("(lib_symbols")
        if idx < 0:
            return 0
        d = 0
        for i in range(idx, len(content)):
            if content[i] == "(":
                d += 1
            elif content[i] == ")":
                d -= 1
                if d == 0:
                    return i + 1
        return 0
