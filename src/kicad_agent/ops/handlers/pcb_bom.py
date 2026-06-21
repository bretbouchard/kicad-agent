"""BOM generation handler -- read-only operation for LCSC/JLCPCB part lookup.

Parses KiCad schematic files (.kicad_sch) for component instances,
looks up each component in an externalized YAML part mapping table,
aggregates by part+value, and returns a structured BOM with LCSC codes,
quantities, and estimated costs.

Ported from hardware/generate_boms.py (proven across 55 modules).
Security: uses yaml.safe_load to prevent arbitrary code execution (T-89-17).
"""

import logging
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

import yaml

logger = logging.getLogger(__name__)

_BOM_HANDLERS: dict[str, Callable] = {}


def register_bom(op_type: str) -> Callable:
    """Decorator to register a BOM operation handler."""
    def decorator(fn: Callable) -> Callable:
        _BOM_HANDLERS[op_type] = fn
        return fn
    return decorator


# ---------------------------------------------------------------------------
# Bundled YAML path
# ---------------------------------------------------------------------------

_BUNDLED_MAPPINGS_PATH = Path(__file__).parent.parent.parent.parent.parent / "data" / "part-mappings.yaml"


def _load_mappings(custom_path: str | None = None) -> dict:
    """Load part mapping table from YAML.

    Args:
        custom_path: Optional custom YAML path. Defaults to bundled.

    Returns:
        Dict with ics, passives, potentiometers, connectors sections.

    Raises:
        FileNotFoundError: If mapping file does not exist.
        yaml.YAMLError: If YAML parsing fails.
    """
    path = Path(custom_path) if custom_path else _BUNDLED_MAPPINGS_PATH
    if not path.exists():
        raise FileNotFoundError(f"Part mapping file not found: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Value normalization (ported from generate_boms.py)
# ---------------------------------------------------------------------------

def _normalize_value(val: str) -> str:
    """Normalize component value strings for matching."""
    v = val.strip()
    v = re.sub(r"\s*(ohm|Ohm|\u03a9|\?)\s*$", "", v, flags=re.IGNORECASE)
    v = re.sub(r"_\d+\.?\d*%$", "", v)
    v = re.sub(r"^\.(\d)", r"0.\1", v)
    v = re.sub(r"^(\d+)[Rr](\d+)$", r"\1.\2", v)
    v = re.sub(r"^(\d+)[Kk](\d+)$", r"\1.\2k", v)
    v = re.sub(r"^(\d+)[Mm](\d+)$", r"\1.\2M", v)
    v = re.sub(r"K$", "k", v)
    v = re.sub(r"M$", "M", v)
    pf_match = re.match(r"^(\d+)(\d{2})pF$", v, re.IGNORECASE)
    if pf_match:
        major, minor = pf_match.group(1), pf_match.group(2)
        val_pf = int(major + minor)
        if val_pf >= 1000:
            val_nf = val_pf / 1000.0
            v = f"{int(val_nf)}nF" if val_nf == int(val_nf) else f"{val_nf}nF"
    return v


# ---------------------------------------------------------------------------
# Component classification (ported from generate_boms.py)
# ---------------------------------------------------------------------------

_IC_LIB_KEYWORDS = [
    "tl072", "tl074", "tl082", "tl084", "ne5532", "lf353", "lm358", "lm741", "op07",
    "mcp3008", "mcp4728", "mcp23017", "mcp4131", "mcp4822", "tlv5618",
    "74hc14", "74hc595", "sn74hc", "cd4066",
    "el817", "ams1117", "7805", "l7805",
    "lm13700", "tc1044", "pt2399", "p82b96",
    "ad9833", "nsl-32", "as3320", "mf10",
    "max7219", "g6k", "rp2350", "ssd1306", "usb",
    "ssm2164", "v2164", "that2180", "that1512", "ina217",
    "pcm1808", "bd139", "bd140", "2n5457", "bc547", "bc557",
    "bc847", "bc857", "ssm2212", "mat02", "mmbt3904",
    "2n3904", "sjr", "zss-108", "mmbt3906",
    "2n3906", "j112",
]


def _classify_component(lib_id: str, ref: str, value: str) -> str:
    """Classify component as ic, capacitor, resistor, diode, led, ferrite,
    pot, connector, power, or other."""
    lib_lower = lib_id.lower()
    ref_upper = ref.upper()

    if lib_lower.startswith("power:") or ref_upper.startswith("#PWR"):
        return "power"
    if "connector" in lib_lower or ref_upper.startswith("J") or "header" in lib_lower:
        return "connector"
    if "pot" in lib_lower or ref_upper.startswith("RV"):
        return "pot"
    if "device:c" == lib_lower or lib_lower.endswith(":c") or ref_upper.startswith("C"):
        return "capacitor"
    if "device:r" == lib_lower or lib_lower.endswith(":r") or ref_upper.startswith("R"):
        return "resistor"
    if "diode" in lib_lower or ref_upper.startswith("D"):
        if "led" in lib_lower or "LED" in value:
            return "led"
        return "diode"
    if "ferrite" in lib_lower or ref_upper[:2] == "FB":
        return "ferrite"
    if any(x in lib_lower for x in ["transistor", "bjt", "mosfet", "fet"]):
        return "ic"
    for ic in _IC_LIB_KEYWORDS:
        if ic in lib_lower:
            return "ic"
    if ref_upper.startswith("U") or ref_upper.startswith("Q"):
        return "ic"
    if ref_upper.startswith("K"):
        return "ic"
    if ref_upper.startswith("FL"):
        return "ferrite"
    return "other"


# ---------------------------------------------------------------------------
# Part lookup
# ---------------------------------------------------------------------------

def _lookup_part(
    category: str,
    value: str,
    lib_id: str,
    mappings: dict,
) -> dict:
    """Look up LCSC info for a component.

    Returns dict with lcsc, package, basic, price_usd keys.
    """
    v = _normalize_value(value)
    ics = mappings.get("ics", {})
    passives = mappings.get("passives", {})
    pots = mappings.get("potentiometers", {})

    # IC exact match
    if v in ics:
        entry = ics[v]
        return {
            "lcsc": entry["lcsc"],
            "package": entry["package"],
            "basic": entry["basic"],
            "price_usd": entry["price_usd"],
        }

    # Capacitor lookup
    if category == "capacitor":
        caps = passives.get("capacitors", {})
        v_lower = v.lower().replace(" ", "")
        if v_lower in caps:
            entry = caps[v_lower]
            return {
                "lcsc": entry["lcsc"],
                "package": entry["package"],
                "basic": entry["basic"],
                "price_usd": entry["price_usd"],
            }
        v_stripped = re.sub(r"[/\s]+\d+\.?\d*V$", "", v_lower)
        if v_stripped in caps:
            entry = caps[v_stripped]
            return {
                "lcsc": entry["lcsc"],
                "package": entry["package"],
                "basic": entry["basic"],
                "price_usd": entry["price_usd"],
            }
        # uF to nF conversion
        if v_stripped.endswith("uf"):
            num_s = v_stripped.replace("uf", "")
            try:
                uf_val = float(num_s)
                nf_val = uf_val * 1e3
                if nf_val == int(nf_val) and int(nf_val) >= 1:
                    nf_key = f"{int(nf_val)}nF"
                    if nf_key in caps:
                        entry = caps[nf_key]
                        return {
                            "lcsc": entry["lcsc"],
                            "package": entry["package"],
                            "basic": entry["basic"],
                            "price_usd": entry["price_usd"],
                        }
                if abs(uf_val - 0.1) < 0.001 and "100nF" in caps:
                    entry = caps["100nF"]
                    return {"lcsc": entry["lcsc"], "package": entry["package"], "basic": entry["basic"], "price_usd": entry["price_usd"]}
            except ValueError:
                pass
        return {"lcsc": "N/A", "package": "0805", "basic": False, "price_usd": 0.01}

    # Resistor lookup
    if category == "resistor":
        res = passives.get("resistors", {})
        if v in res:
            entry = res[v]
            return {
                "lcsc": entry["lcsc"],
                "package": entry["package"],
                "basic": entry["basic"],
                "price_usd": entry["price_usd"],
            }
        return {"lcsc": "N/A", "package": "0805", "basic": False, "price_usd": 0.003}

    # Diode lookup
    if category == "diode":
        dios = passives.get("diodes", {})
        v_lower = v.lower().replace(" ", "")
        if v in dios:
            entry = dios[v]
            return {"lcsc": entry["lcsc"], "package": entry["package"], "basic": entry["basic"], "price_usd": entry["price_usd"]}
        if v_lower in dios:
            entry = dios[v_lower]
            return {"lcsc": entry["lcsc"], "package": entry["package"], "basic": entry["basic"], "price_usd": entry["price_usd"]}
        return {"lcsc": "N/A", "package": "SOD-323", "basic": False, "price_usd": 0.01}

    # LED lookup
    if category == "led":
        return {"lcsc": "C2297", "package": "0805", "basic": True, "price_usd": 0.01}

    # Ferrite lookup
    if category == "ferrite":
        return {"lcsc": "C1015", "package": "0805", "basic": True, "price_usd": 0.005}

    # Potentiometer lookup
    if category == "pot":
        if v in pots:
            entry = pots[v]
            return {"lcsc": entry["lcsc"], "package": entry["package"], "basic": entry["basic"], "price_usd": entry["price_usd"]}
        return {"lcsc": "N/A", "package": "THT Panel", "basic": False, "price_usd": 0.80}

    # Fallback: generic N/A
    return {"lcsc": "N/A", "package": "N/A", "basic": False, "price_usd": 0.00}


# ---------------------------------------------------------------------------
# Schematic parsing (ported from generate_boms.py)
# ---------------------------------------------------------------------------

def _find_matching_paren(content: str, start: int) -> int:
    """Find the closing paren that matches the opening paren at start."""
    depth = 0
    i = start
    while i < len(content):
        if content[i] == "(":
            depth += 1
        elif content[i] == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _find_lib_symbols_end(content: str) -> int:
    """Find where the (lib_symbols ...) block ends."""
    match = re.search(r"\(lib_symbols\b", content)
    if not match:
        return 0
    start = match.start()
    end = _find_matching_paren(content, start)
    return end + 1 if end >= 0 else len(content)


def _parse_schematic(filepath: Path) -> list[dict]:
    """Parse a KiCad schematic file and extract all component instances.

    Handles two KiCad schematic formats:
    - Format A (KiCad native): (symbol (lib_id "...") ...) after lib_symbols block
    - Format B (generated): (component ...) blocks after lib_symbols block

    Returns list of dicts with lib_id, ref, value, footprint keys.
    """
    content = filepath.read_text(encoding="utf-8")
    components = []

    lib_symbols_end = _find_lib_symbols_end(content)
    body = content[lib_symbols_end:]

    # Format A: (symbol (lib_id "...") ...)
    pos = 0
    found_format_a = False
    while pos < len(body):
        match = re.search(r"\(symbol\s+\(lib_id\s+\"([^\"]+)\"\)", body[pos:])
        if not match:
            break
        found_format_a = True
        start = pos + match.start()
        lib_id = match.group(1)
        end = _find_matching_paren(body, start)
        if end < 0:
            break
        block = body[start : end + 1]

        ref_match = re.search(r'\(property\s+"Reference"\s+"([^"]+)"', block)
        ref = ref_match.group(1) if ref_match else "?"
        val_match = re.search(r'\(property\s+"Value"\s+"([^"]+)"', block)
        value = val_match.group(1) if val_match else "?"
        fp_match = re.search(r'\(property\s+"Footprint"\s+"([^"]*)"', block)
        footprint = fp_match.group(1) if fp_match else ""

        components.append({"lib_id": lib_id, "ref": ref, "value": value, "footprint": footprint})
        pos = end + 1

    if found_format_a:
        return components

    # Format B: (component ...) blocks
    pos = 0
    while pos < len(body):
        match = re.search(r"\(component\b", body[pos:])
        if not match:
            break
        start = pos + match.start()
        end = _find_matching_paren(body, start)
        if end < 0:
            break
        block = body[start : end + 1]

        ref_match = re.search(r'\(property\s+"Reference"\s+"([^"]+)"', block)
        ref = ref_match.group(1) if ref_match else "?"
        val_match = re.search(r'\(property\s+"Value"\s+"([^"]+)"', block)
        value = val_match.group(1) if val_match else "?"
        fp_match = re.search(r'\(property\s+"Footprint"\s+"([^"]*)"', block)
        footprint = fp_match.group(1) if fp_match else ""

        sym_match = re.search(r'\(symbol\s+"([^"]+)"', block)
        lib_id = ""
        if sym_match:
            raw = sym_match.group(1)
            parts = raw.rsplit("_", 2)
            lib_id = parts[0] if len(parts) >= 3 else raw

        ref_upper = ref.upper()
        if ref_upper.startswith("#PWR") or ref_upper.startswith("#FLG"):
            pos = end + 1
            continue
        if ref in ("", "?") and value in ("", "?"):
            pos = end + 1
            continue

        components.append({"lib_id": lib_id, "ref": ref, "value": value, "footprint": footprint})
        pos = end + 1

    return components


def _strip_multi_unit_suffix(ref: str) -> str:
    """Strip multi-unit suffix from reference (U1A -> U1, U1B -> U1)."""
    match = re.match(r"^([A-Z]+\d+)[A-Z]$", ref.upper())
    if match:
        return match.group(1)
    return ref


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

@register_bom("generate_bom")
def _handle_generate_bom(
    op: Any,
    ir: Any,
    file_path: Path,
) -> dict[str, Any]:
    """Generate BOM with LCSC/JLCPCB part numbers from a schematic.

    Args:
        op: GenerateBomOp with target_file, supplier, mapping_file.
        ir: Not used (read-only operation).
        file_path: Resolved path to the .kicad_sch file.

    Returns:
        Dict with bom list, total_cost_usd, total_components, unmapped list.
    """
    try:
        mappings = _load_mappings(op.mapping_file)
    except FileNotFoundError as exc:
        return {"success": False, "error": str(exc), "bom": [], "total_cost_usd": 0.0, "total_components": 0, "unmapped": []}

    if not file_path.exists():
        return {"success": False, "error": f"Schematic not found: {file_path}", "bom": [], "total_cost_usd": 0.0, "total_components": 0, "unmapped": []}

    components = _parse_schematic(file_path)
    if not components:
        return {"success": True, "bom": [], "total_cost_usd": 0.0, "total_components": 0, "unmapped": []}

    # Process components: classify, lookup, aggregate
    # Key: (normalized_base_ref, part_value, lcsc_code) -> [refs, info]
    groups: dict[tuple, dict] = {}
    unmapped: list[dict] = []

    for comp in components:
        category = _classify_component(comp["lib_id"], comp["ref"], comp["value"])

        if category == "power":
            continue

        base_ref = _strip_multi_unit_suffix(comp["ref"])
        info = _lookup_part(category, comp["value"], comp["lib_id"], mappings)

        group_key = (base_ref, comp["value"], info["lcsc"])
        if group_key not in groups:
            groups[group_key] = {
                "base_ref": base_ref,
                "part": comp["value"],
                "lcsc": info["lcsc"],
                "package": info["package"],
                "basic": info["basic"],
                "price_usd": info["price_usd"],
                "refs": [],
            }
        groups[group_key]["refs"].append(comp["ref"])

        if info["lcsc"] == "N/A" and category not in ("connector", "pot", "other"):
            unmapped.append({"ref": comp["ref"], "value": comp["value"], "reason": "No LCSC mapping found"})

    # Build BOM list
    bom = []
    total_cost = 0.0
    total_components = 0

    for key, entry in sorted(groups.items(), key=lambda x: x[0][0]):
        qty = len(entry["refs"])
        cost = qty * entry["price_usd"]
        total_cost += cost
        total_components += qty

        ref_str = ", ".join(entry["refs"])
        if len(ref_str) > 40:
            ref_str = ref_str[:37] + "..."

        bom.append({
            "ref": ref_str,
            "part": entry["part"],
            "package": entry["package"],
            "lcsc": entry["lcsc"],
            "basic": entry["basic"],
            "qty": qty,
            "cost": round(cost, 4),
        })

    return {
        "success": True,
        "bom": bom,
        "total_cost_usd": round(total_cost, 2),
        "total_components": total_components,
        "unmapped": unmapped,
    }
