# Plan: Fix All 14 Council Findings

## Context
Council of Ricks deep-dive review returned REJECT with 14 findings (2 critical, 4 high, 5 medium, 3 low). All must be fixed across C++ DSP headers and Swift channel strip views.

---

## Fixes (ordered by severity)

### C-1: SID polyBLEP stub — `SIDVoiceCapability.h:296-301`
**Problem:** Dead `phaseInc = 0.0` variable, returns naive signal with misleading comment.
**Fix:** Remove dead variable. Implement proper polyBLEP correction using the same technique as PulseCapability but only at phase=0 (rising) and phase=width (falling) boundaries. The SVF filter does NOT excuse skipping anti-aliasing.

**File:** `backend/instruments/retro_future_chip/include/capabilities/SIDVoiceCapability.h`

### C-2: BRR encoding produces garbage — `BRRSampleCapability.h:172-213`
**Problem:** Three bugs: (1) unsigned nibble extraction instead of signed BRR deltas, (2) double-counted block offset in nibble pair index, (3) `static uint8_t` mutable array is not thread-safe.
**Fix:** Replace the runtime encoding with pre-computed `static const` sample data (4 waveforms × 4 blocks × 9 bytes). This eliminates all three bugs at once — correct encoding, no allocation, thread-safe. Follow the DPCMCapability pattern of `static const` arrays.

**File:** `backend/instruments/retro_future_chip/include/capabilities/BRRSampleCapability.h`

### H-1: Thread-unsafe mutable static — `BRRSampleCapability.h:177`
**Problem:** `static uint8_t builtinData[]` in inline function — shared mutable state across TUs.
**Fix:** Eliminated by C-2 fix (pre-computed `static const` data).

### H-3: Butterworth coefficient math error — `ColorizerChain.h:368-385`
**Problem:** `alpha * alpha * 0.5f` is not the standard Butterworth numerator `(1 - cos(w0)) / 2`.
**Fix:** Replace with correct formula:
```cpp
float b0 = (1.0f - std::cos(w0)) / (2.0f * a0);
float b1 = 2.0f * b0;
float b2 = b0;
```

**File:** `backend/instruments/retro_future_chip/include/colorizer/ColorizerChain.h` (applyBandLimit method)

### H-4: Dead speaker lowpass computation — `ColorizerChain.h:335-345`
**Problem:** `cutoff` computed then cast to `(void)`. Dead code.
**Fix:** Remove the dead `cutoff` variable and comment. The band-limit filter has its own coefficient computation in `applyBandLimit()`.

**File:** `backend/instruments/retro_future_chip/include/colorizer/ColorizerChain.h` (computeSpeakerCoefficients method)

### M-1: PolyBLEP edge detection swapped — `PulseCapability.h:404-435`
**Problem:** Rising edge correction applied at `duty`, falling edge at `1.0`. Correct: rising at `0.0` (wrap), falling at `duty`.
**Fix:** Swap the edge logic:
```cpp
// Rising edge at phase = 0.0 (wrap point): -1 → +1 transition
double distToRising = phase;  // distance from wrap
// Falling edge at phase = duty: +1 → -1 transition
double distToFalling = phase - duty;
if (distToFalling < 0.0) distToFalling += 1.0;
```
Swap the correction signs accordingly (rising subtracts, falling adds — or adjust based on direction).

**File:** `backend/instruments/retro_future_chip/include/capabilities/PulseCapability.h`

### M-2: Shared RNG state for pink/white noise — `ColorizerChain.h:579-601`
**Problem:** `generatePinkNoise()` borrows `noiseState_` which `generateWhiteNoise()` also uses. Hidden coupling.
**Fix:** Add dedicated `pinkNoiseState_` member (uint32_t), seed it in `prepare()` alongside `noiseState_`, use it exclusively in `generatePinkNoise()`.

**File:** `backend/instruments/retro_future_chip/include/colorizer/ColorizerChain.h`
- Add member at line ~211: `uint32_t pinkNoiseState_;`
- Seed in `prepare()` at line ~66: `pinkNoiseState_ = 12345 + 67890;` (different seed)
- Change line 596: `uint32_t& s = pinkNoiseState_;`

### M-4: std::string allocation in preset load — `RetroFutureChipDSP_Pure.cpp:471`
**Problem:** No documentation that `loadPreset()` must only be called from non-RT context.
**Fix:** Add comment: `// NOTE: loadPreset() allocates — must only be called from non-real-time context.`

**File:** `backend/instruments/retro_future_chip/src/dsp/RetroFutureChipDSP_Pure.cpp`

### M-5: onGainChange optional allows silent DSP breakage — `ChannelStripCompactView.swift:80`
**Problem:** `onGainChange: ((Double) -> Void)?` means callers can skip wiring DSP update. `ConsoleXMixerTab.swift:537` already passes `nil`.
**Fix:** Change to non-optional with a no-op default:
```swift
onGainChange: @escaping (Double) -> Void = { _ in }
```
Apply same change to ChannelStripExpandedView and ChannelStripView. Remove `?` unwrapping at call sites.

**Files:**
- `swift_frontend/SwiftFrontendShared/Sources/ViewsControls/Strip/ChannelStripCompactView.swift`
- `swift_frontend/SwiftFrontendShared/Sources/ViewsControls/Strip/ChannelStripExpandedView.swift`
- `swift_frontend/SwiftFrontendShared/Sources/ViewsControls/Strip/ChannelStripView.swift`

### L-1: Mixed-concern preset changes
**Problem:** Echo tuning mixed with sweep parameter addition in same commit.
**Fix:** No code change needed — note for future commit hygiene. Remove from fix list.

### L-2: Fixed RNG seed produces correlated noise — `ColorizerChain.h:65`
**Problem:** Every ColorizerChain instance uses same seed 12345.
**Fix:** Add `static uint32_t instanceCounter_ = 0;` at class scope. In `prepare()`: `noiseState_ = 12345 + (++instanceCounter_) * 11111;`. This gives each instance a unique but deterministic seed.

**File:** `backend/instruments/retro_future_chip/include/colorizer/ColorizerChain.h`

### L-3: Debug tag naming in console.txt
**Problem:** `MIXER-FADER-BUG` tag in `docs/console.txt`.
**Fix:** The MIXER-FADER-BUG tag only exists in `docs/console.txt` (documentation of a debug session), not in live code. The C++ printf debris was already cleaned. The console.txt is historical log — update the tag references there.

**File:** `docs/console.txt`

---

## Files to Modify

| # | File | Fixes |
|---|------|-------|
| 1 | `backend/instruments/retro_future_chip/include/capabilities/SIDVoiceCapability.h` | C-1 |
| 2 | `backend/instruments/retro_future_chip/include/capabilities/BRRSampleCapability.h` | C-2, H-1 |
| 3 | `backend/instruments/retro_future_chip/include/colorizer/ColorizerChain.h` | H-3, H-4, M-2, L-2 |
| 4 | `backend/instruments/retro_future_chip/include/capabilities/PulseCapability.h` | M-1 |
| 5 | `backend/instruments/retro_future_chip/src/dsp/RetroFutureChipDSP_Pure.cpp` | M-4 |
| 6 | `swift_frontend/SwiftFrontendShared/Sources/ViewsControls/Strip/ChannelStripCompactView.swift` | M-5 |
| 7 | `swift_frontend/SwiftFrontendShared/Sources/ViewsControls/Strip/ChannelStripExpandedView.swift` | M-5 |
| 8 | `swift_frontend/SwiftFrontendShared/Sources/ViewsControls/Strip/ChannelStripView.swift` | M-5 |
| 9 | `docs/console.txt` | L-3 |

## Execution Order

1. C++ DSP fixes (C-1, C-2, H-1, H-3, H-4, M-1, M-2, L-2, M-4) — can be parallelized per file
2. Swift fixes (M-5) — 3 strip view files
3. Docs fix (L-3)
4. Build verification: `./build-config/scripts/test-all.sh --cpp`

## Verification

1. C++ backend tests: `./build-config/scripts/test-all.sh --cpp`
2. Swift build: verify strip views compile (xcodebuild or swift build)
3. Re-run Council review to confirm clean pass
