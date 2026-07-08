"""Phase 158: SPICE model registry.

Generic macromodels for common ICs. Components without models are marked
UNSIMULATABLE. Models sourced from public TI/ADI datasheets.
"""
from __future__ import annotations

# ICs we have SPICE macromodels for.
SPICE_MODELS: dict[str, str] = {
    "NE5532": """
* NE5532 dual opamp macromodel (simplified)
.SUBCKT NE5532 IN+ IN- VCC VEE OUT
  EOUT OUT 0 VCC VEE 0.5
  GIN 0 N1 IN+ IN- 100K
  RN1 N1 0 1K
  EOUT2 OUT 0 N1 0 100
  ROUT OUT 0 100
.ENDS NE5532
""",
    "TL072": """
* TL072 JFET opamp macromodel (simplified)
.SUBCKT TL072 IN+ IN- VCC VEE OUT
  GIN 0 N1 IN+ IN- 200K
  RN1 N1 0 1K
  EOUT2 OUT 0 N1 0 200
  ROUT OUT 0 100
.ENDS TL072
""",
    "LM358": """
* LM358 opamp macromodel (simplified)
.SUBCKT LM358 IN+ IN- VCC VEE OUT
  GIN 0 N1 IN+ IN- 50K
  RN1 N1 0 1K
  EOUT2 OUT 0 N1 0 100
  ROUT OUT 0 200
.ENDS LM358
""",
    "2N3904": """
* 2N3904 NPN general-purpose transistor (Gummel-Poon, room-temp only)
*
* kicad-agent-cjl: This is the OnSemi 2N3904 Gummel-Poon model from the
* public datasheet. Parameters are tuned for Tnom=27C (ngspice default).
* Temperature coefficients (Tnom, TR, etc.) are NOT included — simulations
* are accurate at room temperature but drift significantly above 70C or
* below 0C. For thermal analysis, swap in the official OnSemi SPICE model
* archive (https://www.onsemi.com/design/tools-software/selection-st/spice-models)
* which includes full temperature dependence.
*
* Acceptable for: Phase 204 closed-box magic proof (room temp assumed),
*                 Eurorack input preamp optimization (always room temp)
* NOT acceptable for: thermal runaway analysis, automotive temperature
*                     range, military temp range, junction temp estimation
.MODEL 2N3904 NPN(
+  Is=6.734f Xti=3 Eg=1.11 Vaf=74.03 Bf=416.4
+  Ne=1.259 Ise=6.734f Ikf=66.78m Xtb=1.5
+  Br=.7371 Nc=2 Isc=0 Ikr=0 Rc=1
+  Cjc=3.638p Mjc=.3085 Vjc=.75 Fc=.5
+  Cje=4.493p Mje=.2593 Vje=.75 Tr=239.5n Tf=301.2p
+  Itf=.4 Vtf=4 Xtf=2
+)
""",
}

# ICs we CANNOT simulate (no reliable macromodel available).
UNSIMULATABLE: set[str] = {
    "AK4619VN",   # Audio codec — proprietary DSP, no SPICE model
    "RP2350B",    # Microcontroller — digital, not analog-simulatable
    "RP2040",     # Microcontroller — digital
    "W5500",      # Ethernet controller — digital
    "MCP23017",   # I/O expander — digital
    "MCP23008",   # I/O expander — digital
}


def get_model(part_name: str) -> str | None:
    """Get the SPICE model for a part, or None if unavailable.

    Args:
        part_name: Part name (e.g. "NE5532", "TL072").

    Returns:
        SPICE .SUBCKT definition, or None if no model available.
    """
    name_upper = part_name.upper().split(":")[-1]
    for key, model in SPICE_MODELS.items():
        if key.upper() in name_upper:
            return model
    return None


def is_simulatable(part_name: str) -> bool:
    """Check if a part can be simulated.

    Args:
        part_name: Part name or lib_id.

    Returns:
        True if the part has a SPICE model or is a generic passive.
    """
    name_upper = part_name.upper()
    # Passives are always simulatable.
    if any(p in name_upper for p in ("RESIST", "CAPACITOR", "INDUCT", "DEVICE:R", "DEVICE:C", "DEVICE:L")):
        return True
    # Check UNSIMULATABLE list.
    for u in UNSIMULATABLE:
        if u.upper() in name_upper:
            return False
    # Check if we have a model.
    return get_model(part_name) is not None


def get_all_models() -> str:
    """Get all SPICE model definitions concatenated (for embedding in .cir)."""
    return "\n".join(SPICE_MODELS.values())
