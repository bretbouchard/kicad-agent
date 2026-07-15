# Plan: Fix Bug #66 — resolve_pin_positions returns pin tip instead of body

## Context

Bug #66 reports that `resolve_pin_positions` returns the pin **tip** (body + pin_length * direction) instead of the pin **body** `(at dx dy)`. KiCad ERC checks electrical connectivity at the pin body position, not the tip. This caused incorrect wire placement on the x64_i2c schematic (64 LEDs + 64 resistors).

**Root cause:** `PinResolver._parse_components()` at line 303 sets `"position": (wire_x, wire_y)` — the computed tip. The `"body_position"` field already exists with correct coords, but `"position"` (the primary field) is wrong.

## Fix: Swap `position` to body, add `tip_position` for wire endpoint

### Files to modify

#### 1. `src/volta/schematic_routing/pin_resolver.py` (lines 303-305)
**Swap `"position"` and add `"tip_position"`.**
```python
# Before:
pin_data[pin_number] = {
    "position": (wire_x, wire_y),
    "body_position": (body_x, body_y),
    ...
}
# After:
pin_data[pin_number] = {
    "position": (body_x, body_y),
    "body_position": (body_x, body_y),
    "tip_position": (wire_x, wire_y),
    ...
}
```
Note: Keep `body_position` as-is for backward compat — it's already correct.

#### 2. `src/volta/schematic_routing/net_connector.py` (line 128)
**Change tip reference from `"position"` to `"tip_position"`.**
```python
# Before:
wx, wy = pin_info["position"]
# After:
wx, wy = pin_info["tip_position"]
```
This module uses both body and tip to compute label offset direction vectors — it needs the tip, just via the correct key name.

#### 3. `src/volta/ops/handlers/schematic_query.py` (line 156)
No change needed — handler returns `result.get("pins", {})` which will now contain the corrected `"position"`.

### Test files to update

#### 4. `tests/test_pin_resolver.py`
Update all assertions where `"position"` is compared to tip values. Swap to body values:
- Line 289: `pins["1"]["position"]` from `(59.69, 80.01)` → `(59.69, 78.74)` (body)
- Line 294: `pins["2"]["position"]` from `(59.69, 69.85)` → `(59.69, 71.12)` (body)
- Lines 327, 332, 340: multi-unit pin `"position"` assertions → body values
- Line 366: named pin `"position"` assertion → body value
- Line 401: rotation pin `"position"` assertion → body value
- Add `"tip_position"` assertions where `"position"` used to assert tip values.

#### 5. `tests/test_collision_detector.py` (lines 398, 438, 474)
Collision detector uses `"position"` for pin overlap detection. Now that `"position"` is body, update the expected coordinate values from tip to body.

#### 6. `tests/test_net_connector.py` (lines 65-70, 81-87, 103-104, 114-115, 131-132, 148-149, 159-160)
Update mock data: swap `"position"` values from tip to body, add `"tip_position"` with the old tip values. Also update label position assertions (lines 394, 410, 424) which compute from tip — these should stay the same since `net_connector.py` will use `"tip_position"`.

### Files NOT modified
- `src/volta/ir/schematic_ir.py:get_pin_positions()` — already returns body coords via kiutils `pin_def.position.X/Y`. Correct.
- `src/volta/ops/violation_classifier.py` — uses `pin.get("position")` on data from `SchematicIR.get_pin_positions()` which already returns body. Unaffected.
- `src/volta/schematic_routing/collision_detector.py` — uses `pin_info["position"]` from PinResolver. After fix, `"position"` will be body, which is correct for overlap detection.

## Verification

```bash
# Run affected tests
python -m pytest tests/test_pin_resolver.py tests/test_collision_detector.py tests/test_net_connector.py -xvs

# Run net_label_placer tests (uses get_pin_positions from SchematicIR, unaffected)
python -m pytest tests/test_net_label_placer.py -xvs

# Full regression
python -m pytest tests/ -x --timeout=60
```
