# KiCad File Format Reference for kicad-agent

Concise reference for the S-expression file formats, coordinate conventions,
and design rules that kicad-agent manipulates. Covers KiCad 10.0+.

## File Types

| Extension | Format | Description |
|-----------|--------|-------------|
| `.kicad_sch` | S-expression | Schematic sheet (one sheet per file) |
| `.kicad_pcb` | S-expression | PCB layout board |
| `.kicad_sym` | S-expression | Symbol library |
| `.kicad_mod` | S-expression | Footprint library |
| `.kicad_pro` | S-expression/JSON | Project file |
| `.kicad_wks` | S-expression | Page layout description |

## S-Expression Format

KiCad files use S-expressions (sexp) — nested parenthesized lists:

```
(symbol (lib_id "Device:R") (at 50.0 30.0 0) ...)
(symbol (lib_id "Device:C") (at 80.0 30.0 0) ...)
```

Key properties of the format:

- **Whitespace is insignificant** — indentation is for readability only
- **Strings are quoted** — `"Device:R"`, `"GND"`, `"Net-(D1-K)"`
- **Numbers are unquoted** — `50.0`, `0`, `1.0e-6`
- **Properties are `(key value ...)` pairs** — `(at X Y ROTATION)`
- **UUIDs are 32-char hex strings** — `(uuid "a1b2c3d4-e5f6-7890-abcd-ef1234567890")`
- **Order matters within atoms** — `(at X Y ROTATION)` not `(at Y X ROTATION)`

## Coordinate System

### Units
- **Millimeters (mm)** — all positions, sizes, clearances, track widths
- **Degrees** — rotations, angles (0.0 = 3 o'clock, counter-clockwise positive)
- **Mils** — some legacy footprint dimensions (1 mil = 0.0254mm)

### Schematic Coordinates
- **Origin**: Bottom-left of sheet (KiCad 6+)
- **X increases rightward**
- **Y increases upward** — but pin `(at X Y)` is the connection point, not graphic tip
- **Pin relative position**: `abs_component_Y - pin_rel_Y` (subtract for absolute)

### PCB Coordinates
- **Origin**: Center of board outline (or arbitrary user-set origin)
- **X increases rightward**
- **Y increases upward** (same as schematic)
- **Layers**: Front copper (F.Cu), Back copper (B.Cu), silkscreen, mask, paste, etc.

### Grid Conventions
- **Default schematic grid**: 50mil (1.27mm) in KiCad 6+, 1000mil in legacy
- **Default PCB grid**: 25mil (0.635mm) or 50mil (1.27mm)
- **Snap to grid**: Components and wires snap to grid unless explicitly overridden
- **Common footprints use 2.54mm (100mil) or 1.27mm (50mil) pin pitch**

### Device:R/C Pin Offset Warning
- `Device:R` and `Device:C` symbols have **3.81mm pin offsets** (not 2.54mm)
- This places connection points off the standard 2.54mm grid
- Accept false-positive `wire_dangling` ERC errors, use no-connects for optional pins
- See kicad-agent memory: `KiCad Coordinate Gotchas`

## Schematic Format (.kicad_sch)

### Top-Level Structure

```
(kicad_sch
  (version 20231120)       ;; File format version
  (generator "kicad-cli")  ;; Tool that created/modified the file

  (uuid "project-uuid")

  (paper "A4")             ;; Paper size

  (lib_symbols             ;; Embedded symbol definitions
    (symbol "Device:R" ...)
    (symbol "Device:C" ...)
  )

  (symbol                  ;; Placed symbol instance
    (lib_id "Device:R")
    (at 50.0 30.0 0)       ;; Position and rotation
    (uuid "instance-uuid")
    (property "Reference" "R1" (at 52.54 27.46 0)
      (effects (font (size 1.27 1.27))))
    (property "Value" "10k" (at 52.54 32.54 0)
      (effects (font (size 1.27 1.27))))
    (pin "1"                ;; Pin definitions
      (uuid "pin-uuid")
      (at 0 -2.54 0)        ;; Relative position
      (length 2.54)
      (name "1")
      (function "passive"))
    ...
  )

  (wire                    ;; Wire connections
    (pts (xy 52.54 30.0) (xy 65.0 30.0))
    (stroke (width 0) (type default))
    (uuid "wire-uuid")
  )

  (label "GND"             ;; Net label
    (at 65.0 30.0 0)
    (fields_autoplaced yes)
    (uuid "label-uuid")
    (effects (font (size 1.27 1.27)) (justify left))
  )

  (no_connect "pad-uuid")   ;; Explicit no-connect flag

  (hierarchical_label ...) ;; Hierarchical sheet labels
  (sheet ...)              ;; Hierarchical sheet references
  (symbol_instances ...)   ;; Symbol-to-sheet cross-references
)
```

### Symbol Library Embedding

Symbols can be defined inline (`lib_symbols` section) or referenced from
external `.kicad_sym` files. kicad-agent embeds symbols inline to ensure
self-contained schematics.

### Power Symbols

Power symbols (`#PWR` prefix) use special connection rules:
- All symbols with the same net name (e.g., `VCC`, `GND`) are implicitly connected
- No explicit wire needed between power symbols
- Pin type is typically `power_in` or `power_out`
- kicad-agent bug #49: `add_power` creates 0-pin symbols — use `passive` pin type instead

## PCB Format (.kicad_pcb)

### Top-Level Structure

```
(kicad_pcb
  (version 20240108)

  (general
    (thickness 1.6)        ;; Board thickness in mm
    (depth 25)              ;; Board depth for 3D rendering
  )

  (paper "A4")

  (layers                  ;; Layer stackup definition
    (0 "F.Cu" signal)
    (31 "B.Cu" signal)
    (32 "B.Adhes" user)
    (33 "F.Adhes" user)
    (34 "B.Paste" user)
    (35 "F.Paste" user)
    (36 "B.SilkS" user)
    (37 "F.SilkS" user)
    (38 "B.Mask" user)
    (39 "F.Mask" user)
    (40 "Dwgs.User" user)
    (41 "Cmts.User" user)
    (42 "Eco1.User" user)
    (43 "Eco2.User" user)
    (44 "Edge.Cuts" user)
    (45 "Margin" user)
  )

  (setup
    (pad_to_mask_clearance 0.05)
    (pad_to_paste_clearance -0.025)
    (pcbplotparams ...)
    (aux_axis_origin 50 50) ;; Custom origin offset
  )

  (net 0 "")                ;; Net declarations
  (net 1 "GND")
  (net 2 "VCC")
  (net 3 "Net-(R1-Pad1)")

  (segment                 ;; Track segment
    (start 50.0 30.0)
    (end 80.0 30.0)
    (width 0.25)
    (layer "F.Cu")
    (net 3)
    (tstamp "segment-uuid")
  )

  (via                     ;; Via
    (at 65.0 30.0)
    (size 0.8)
    (drill 0.4)
    (layers "F.Cu" "B.Cu")
    (net 3)
    (tstamp "via-uuid")
  )

  (footprint               ;; Placed footprint
    (type "pad")
    (lib_id "Resistor_SMD:R_0603_1608Metric")
    (at 50.0 30.0 0)
    (uuid "footprint-uuid")
    (property "Reference" "R1" (at 0 -1.43 0) ...)
    (property "Value" "10k" (at 0 1.43 0) ...)
    (pad "1" smd roundrect   ;; Pad definitions
      (at -0.775 0)
      (size 0.9 0.95)
      (layers "F.Cu" "F.Paste" "F.Mask")
      (net 3)
      (tstamp "pad-uuid")
    )
    ...
  )

  (gr_line (start 0 0) (end 100 0)     ;; Board outline on Edge.Cuts
    (stroke (width 0.1) (type solid))
    (layer "Edge.Cuts")
  )

  (zone                    ;; Copper zone
    (net 1)
    (net_name "GND")
    (layer "F.Cu")
    (tstamp "zone-uuid")
    (hatch edge 0.5)
    (connect_pads
      (clearance 0.5)
    )
    (min_thickness 0.25)
    (filled_polygon_thickness 0.25)
    (fill yes)
    (polygon
      (pts
        (xy 10 10)
        (xy 90 10)
        (xy 90 70)
        (xy 10 70)
      )
    )
  )

  (group "" ...)           ;; Group definitions
)
```

### Net Declarations
- Net 0 is always unnamed/empty
- Net names follow pattern: `Net-(ComponentReference-PadName)`
- Power nets use actual name: `GND`, `VCC`, `+3V3`, etc.

### Footprint Placement
- `(at X Y ROTATION)` — center position
- Rotation in degrees (0, 90, 180, 270 typical)
- Footprints on F.Cu are placed as viewed from top
- kicad-agent bug: kiutils `Board.to_file()` drops nets — use raw S-expression for PCBs

### Layer Naming Convention
- `F.` prefix = Front (top side)
- `B.` prefix = Back (bottom side)
- `In` prefix = Inner copper layers (In1.Cu through In30.Cu)
- Common signal layers: F.Cu, B.Cu, In1.Cu ... In30.Cu
- Non-copper: F.SilkS, B.SilkS, F.Mask, B.Mask, F.Paste, B.Paste

## Footprint Format (.kicad_mod)

### Structure

```
(module "Resistor_SMD:R_0603_1608Metric" (layer F.Cu)
  (descr "Resistor SMD 0603 (1608 Metric)")
  (tags "resistor 0603")
  (fp_text reference "R**" (at 0 -1.43) ...)
  (fp_text value "R" (at 0 1.43) ...)

  (pad 1 smd roundrect        ;; Pad type and shape
    (at -0.775 0)              ;; Position relative to footprint origin
    (size 0.9 0.95)            ;; Pad dimensions
    (layers F.Cu F.Paste F.Mask) ;; Pad layers
    (roundrect_rratio 0.25)    ;; Corner radius ratio
    (solder_mask_margin 0.05)   ;; Mask expansion
    (thermal_bridge 0.5 2)      ;; Thermal relief spokes
  )

  (pad 2 smd roundrect
    (at 0.775 0)
    (size 0.9 0.95)
    (layers F.Cu F.Paste F.Mask)
    (roundrect_rratio 0.25)
    (solder_mask_margin 0.05)
  )

  (fp_line                    ;; Graphic elements (silkscreen, courtyard, etc.)
    (start -0.78 -0.94)
    (end 0.78 -0.94)
    (stroke (width 0.12) (type solid))
    (layer F.SilkS)
  )

  (fp_poly                    ;; Courtyard outline
    (pts
      (xy -1.32 -0.97)
      (xy 1.32 -0.97)
      (xy 1.32 0.97)
      (xy -1.32 0.97)
    )
    (stroke (width 0.05) (type solid))
    (layer F.CrtYd)
  )
)
```

### Pad Types
| Type | Description |
|------|-------------|
| `smd` | Surface mount device |
| `thru_hole` | Through-hole (plated) |
| `np_thru_hole` | Non-plated through-hole |
| `connect` | Pad on copper zone edge |
| `edge` | Board edge connector pad |

### Pad Shapes
| Shape | Description |
|-------|-------------|
| `rect` | Rectangle |
| `circle` | Circle |
| `oval` | Oval/oblong |
| `roundrect` | Rounded rectangle (with `roundrect_rratio`) |
| `trapezoid` | Trapezoid |
| `custom` | Custom shape (polygon points) |

## Symbol Format (.kicad_sym)

### Structure

```
(kicad_symbol "Device" (in_bom yes) (on_board yes)
  (property "Reference" "R" (at 0.762 0 0)
    (effects (font (size 1.27 1.27)) (justify left)))
  (property "Value" "R" (at 0.762 1.27 0)
    (effects (font (size 1.27 1.27)) (justify left)))
  (property "Footprint" "" (at 0 0 0)
    (effects (font (size 1.27 1.27)) hide))

  (symbol "R_0603"          ;; Symbol variant
    (pin_numbers hide)       ;; Hide pin numbers
    (pin_names (offset 0))   ;; Pin name offset
    (exclude_from_sim no)    ;; Include in simulation
    (in_bom yes)             ;; Include in BOM
    (on_board yes)           ;; Include on PCB

    (pin "1"                 ;; Pin definition
      (uuid "pin-uuid")
      (at 0 -2.54 0)        ;; Relative to symbol origin
      (length 2.54)          ;; Pin graphic length
      (name "1")
      (number "1")
      (function "passive")  ;; Electrical function
    )
    (pin "2"
      (uuid "pin-uuid")
      (at 0 2.54 0)
      (length 2.54)
      (name "2")
      (number "2")
      (function "passive")
    )

    (graphic                ;; Symbol graphic (lines, arcs, rectangles)
      (polyline
        (pts (xy -0.762 -1.016) (xy 0.762 -1.016))
        (stroke (width 0) (type default) (color 0 0 0 0))
        (fill (type none))
      )
    )
  )
)
```

### Pin Functions
| Function | Description |
|----------|-------------|
| `passive` | Passive component pin |
| `input` | Input pin |
| `output` | Output pin |
| `bidirectional` | Bidirectional pin |
| `power_in` | Power input (VCC, GND) |
| `power_out` | Power output (regulator output) |
| `no_connect` | Explicitly unconnected |
| `unspecified` | Default/unknown |

## Multi-Pin Connector Layouts

Multi-pin connectors (e.g., Card_Edge_64P) have non-sequential pin positions:
- Pins 1-32 on the left side, pins 33-64 ALL on the right side
- Right-side pins reuse Y positions from left-side pins
- **Never calculate pin positions from pin number** — use lookup tables
- kicad-agent memory: `KiCad Coordinate Gotchas`

## ERC (Electrical Rules Check)

Common ERC violations kicad-agent handles:

| Error | Description | Typical Cause |
|-------|-------------|---------------|
| `pin_conflict` | Pin type conflict (output→output) | Shorted outputs |
| `wire_dangling` | Wire end not connected | Missing pin connection |
| `no_connect_connected` | Wire connected to no-connect | Wrong no-connect placement |
| `unresolved_variable` | Text variable not resolved | Missing field value |
| `missing_unit` | Multi-unit symbol not fully placed | Incomplete IC placement |

Run ERC via:
```bash
kicad-cli sch erc <file.kicad_sch>
```

## DRC (Design Rules Check)

Common DRC violations:

| Error | Description | Typical Cause |
|-------|-------------|---------------|
| `unconnected_pad` | Pad not connected | Missing route |
| `missing_courtyard` | Footprint has no courtyard | Bad footprint |
| `courtyard_overlap` | Courtyards overlap | Components too close |
| `track_width` | Track too narrow for net class | Wrong width setting |
| `via_diameter` | Via too small | Via clearance issue |
| `clearance` | Minimum clearance violated | Objects too close |
| `edge_clearance` | Copper too close to board edge | Placement issue |

Run DRC via:
```bash
kicad-cli pcb drc <file.kicad_pcb>
```

## Net Naming Conventions

| Pattern | Meaning |
|---------|---------|
| `GND` | Ground net |
| `VCC`, `+3V3`, `+5V`, `+12V` | Power nets |
| `Net-(R1-Pad1)` | Auto-generated signal net name |
| `Net-(J1-Pin3)` | Connector pin net |
| `USB_DP`, `USB_DM` | Named signal nets |

## kicad-agent Known Gotchas

These are tracked in kicad-agent's memory system:

1. **Pin (at X Y) = wire connection point** — not pin graphic tip
2. **Schematic Y is inverted** — `abs_Y = comp_Y - pin_rel_Y`
3. **Multi-pin connectors** — non-sequential layouts, use lookup tables
4. **Device:R/C 3.81mm offset** — connection points off standard grid
5. **kiutils Board.to_file() drops nets** — use raw S-expression for PCBs
6. **add_power creates 0-pin symbols** — don't use, change pin type to passive
7. **add_component missing rotation** — post-process: append ` 0` to `(at X Y)`
