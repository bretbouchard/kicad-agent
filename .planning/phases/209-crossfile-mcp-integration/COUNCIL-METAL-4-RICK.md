# Phase 209 Council Review — Metal 4 Rick (GPU/Rendering/Visualization)

**Phase:** 209 — Crossfile + MCP Integration
**Review lens:** GPU rendering, 3D visualization, Metal 4 on Apple Silicon, GPU compute for DRC
**Reviewed:** 2026-07-10
**Reviewer:** Metal 4 Rick (Tier 2 — Stack-Aware Specialist)
**Verdict:** APPROVE with 1 HIGH opportunity, 3 MEDIUM opportunities, 2 INFO notes. None block Phase 209. All are v7.1+ seeds — the v7.0 manufacturing layer is sound as-shipped.

---

## Executive Summary

I audited the entire render/visualization pipeline end-to-end: `render.py` (kicad-cli wrapper, 180s timeout, PNG output), `PCBPreviewView.swift` (pure `Image(nsImage:)` display, no GPU), `handoff.py` (STEP + render optional, `include_render` currently a no-op stub at line 522-524), `vendor_drc.py` (O(n²) pairwise clearance in pure Python), and the SwiftData `Project` / Python `Build` models (no thumbnail field anywhere).

**The headline:** The current approach — kicad-cli renders a PNG, the Mac app displays it as a static image — is **fine for what it does**. Phase 172's inline rendering is a correct, shippable v7.0 pattern. But it leaves the entire Apple Silicon GPU idle for everything visual, and there is one genuinely high-value opportunity (GPU compute for the O(n²) DRC clearance check) and one strong UX opportunity (interactive 3D board viewer for handoff review) that the architecture should seed now, even if implementation is v7.1.

There is **zero Metal, SceneKit, RealityKit, or ModelIO usage** anywhere in the Mac app today. The only Metal touchpoint is MLX-Swift (LLM inference). The GPU is awake only for text generation. The most powerful processor in the machine draws a progress bar while kicad-cli subprocess does the rendering. That is the gap.

I am voting APPROVE because none of this blocks the integration capstone, and Phase 209 explicitly seeds v7.1 interfaces (`ManufacturerClient` ABC). The findings below are scoped as seeds for that interface and for a future rendering track — not as Phase 209 rework.

---

## Answers to the Six Review Questions

### 1. Should the Mac app use Metal 4 to render the 3D PCB model instead of relying on kicad-cli renders?

**Split verdict: PNG for chat bubbles (keep), Metal/SceneKit for interactive review (add).**

What exists today (`PCBPreviewView.swift:72`):
```swift
Image(nsImage: NSImage(byReferencing: artifact.url))
    .resizable()
    .aspectRatio(contentMode: .fit)
```

This is a static image fetched over a process boundary: SwiftUI → JSON-RPC → Python daemon → `kicad-cli pcb render` subprocess (180-second timeout at `render.py:150`) → PNG on disk → back to SwiftUI `Image`. For a chat bubble that needs to show "here is your board," this is acceptable — it is cacheable, deterministic, and the daemon already owns the kicad-cli lifecycle.

But the moment a user wants to *inspect* the board — orbit it, zoom into a dense BGA region, see the back side, check component clearance in 3D — a static PNG is the wrong primitive. Regenerating a new PNG for every `--rotate "-45,0,45"` costs another full kicad-cli subprocess spawn. That is not interactivity; that is a slideshow with a 180-second ceiling per frame.

**The right architecture (v7.1 seed):**
- **Chat bubble previews:** keep kicad-cli PNG. One-shot, cacheable, done. This is the correct use of the existing `PreviewRenderer` protocol.
- **Dedicated 3D board inspector view:** SceneKit via `ModelIO` loading the STEP file that the handoff package already produces (`handoff.py:496-501`, `export_step`). SceneKit on macOS 27 is Metal 4-backed under the hood — `SCNView` uses a Metal 4 device by default on Apple Silicon. This gives you orbit/zoom/pick for free without writing a single line of Metal Shading Language. The STEP → `MDLAsset` → `SCNGeometry` pipeline is ~40 lines of Swift.
- **Reserve raw Metal 4 mesh shaders** for the case where SceneKit's overhead matters (it won't, for a single PCB assembly). A PCB is maybe a few thousand component meshes — trivially within SceneKit's comfort zone. Writing a custom mesh-shader pipeline for this is gold-plating unless you add real-time ray-traced solder-mask refraction or something equally exotic. I would veto that scope.

**Why not Metal 4 mesh shaders directly?** Because the geometry count is tiny by GPU standards. Mesh shaders shine when you are culling millions of meshlets against a HiZ buffer. A PCB has thousands of components, not millions. The vertex/fragment pipeline (which SceneKit wraps) is the right tool. Metal 4's value here is the *device* and *command queue* — which SceneKit gives you without handwritten encoders. Save the hand-written Metal 4 for the DRC compute shader (finding #5), where the parallelism is real.

### 2. Could the vendor DRC violations be visualized as a 3D overlay on the board?

**Yes — and this is the highest-leverage visualization opportunity. High value, low effort.**

The violations in `vendor_drc.py` already carry the geometry needed for a 3D overlay. Look at the clearance violation shape (`vendor_drc.py:427-441`):
```python
Violation(
    description=...,
    severity=Severity.ERROR,
    type="vendor_clearance",
    items=({
        "layer": layer,
        "actual_gap_mm": gap,
        "required_mm": limit,
        "net_a": net1,
        "net_b": net2,
    },),
)
```

Every violation has a layer, the offending nets, and the actual-vs-required gap. The track-width, drill, annular-ring, and via-diameter checks each carry the feature's coordinates implicitly (the segment/via they failed on). This is everything you need to render red highlight halos on the exact copper features that violate, at the correct Z-height for the layer.

**Concrete design (v7.1):**
- Extend `VendorDrcResult` (or its Swift mirror) to include the `(x, y, layer)` of each violating feature. Today the geometry is known inside `_check_clearance` but not surfaced into the `Violation.items` for clearance (it only carries layer name, not coordinates). Track-width/drill/annular/via checks would need the same coordinate lift.
- In the 3D inspector view, render violating features as a second draw pass with an emissive red material and a pulsing opacity animation (driven by a 2Hz timer — trivial in SceneKit via `SCNAction`).
- Color-code by severity: ERROR = red, WARNING = amber. The `Severity` enum already exists (`validation/erc_drc.py`).

This turns "you have 47 clearance violations" into "here are the 47 red regions on your board, tap one to see the gap." That is the difference between a DRC report and a DRC *experience*. The data is 90% there; the rendering is straightforward SceneKit. Recommend as a v7.1 feature with the coordinate-surfacing refactor done now as a low-risk incremental.

**SLC note:** The coordinate lift is a pure data-structure change to frozen `Violation` items dicts — backward compatible, testable, no GPU work required to ship the data side.

### 3. Is the STEP file the right format, or should there be a Metal-optimized mesh?

**STEP is correct. Ship STEP. Convert to GPU mesh at load time. Do NOT invent a "Metal mesh" interchange format.**

STEP (ISO 10303) is the industry-standard 3D interchange for fabrication. Every board house, every MCAD tool, every KiCad 3D viewer consumes it. `export_step` (`general.py:176`) producing `.step` in the handoff zip (`handoff.py:496`) is the right call. Replacing it with a proprietary `.metalmesh` would make the handoff package unreadable by the people who actually manufacture the board. That is a hard reject.

**The "Metal-optimized mesh" lives at runtime, not on disk.** The conversion path on Apple Silicon is:
```
STEP file
  → MDLAsset(url:)                    // ModelIO loads STEP (bundled importer)
  → MDLAsset.loadAsset()              // tessellate to MDLMesh
  → SCNGeometry(mdlMesh:)             // SceneKit wraps it
  → SCNView.scene.rootNode.addChild   // Metal 4 device renders it
```

ModelIO tessellates the STEP B-rep into triangles once, caches the `SCNGeometry`, and you have a GPU-resident mesh for the session. No custom mesh format. No offline conversion tool. The first load takes a second or two; subsequent orbit/zoom is 60fps+ on any Apple Silicon GPU because the geometry is already in VRAM.

If you ever find yourself wanting to pre-bake the mesh (e.g., for instant load of huge boards), cache it as `.usdz` (Apple's archive format, ModelIO round-trips to it). USDZ is a documented standard, not a Metal-specific blob. But for v7.1 this is premature — STEP load latency on a typical PCB is negligible.

### 4. Could the handoff package include an interactive 3D preview?

**No — not *inside* the zip. Yes — in the Mac app that opens the zip.**

The handoff zip (`handoff.py:593-598`) is for a fabricator. Fabricators want Gerbers, drill, BOM, pick-and-place, and a STEP. They do NOT want an embedded HTML/JS viewer, a `.scn` file, or a bundled app. Stuffing an interactive viewer into a manufacturing handoff is scope confusion — the recipient is a factory, not a stakeholder doing design review.

**The interactive 3D preview belongs in the Mac app's build-history / handoff-review surface.** When a user opens a past build (the `Build` record from `build.py`), the app should offer an "Inspect 3D" button that loads the build's `{stem}.step` (already in the zip, already on disk in `builds/handoff_{ts}/`) into a SceneKit inspector. Zero additional artifacts needed — the STEP is already there. This is a pure client-side feature.

The one thing worth adding to the *manifest* (not the zip payload): a `preview_image` field pointing at a rendered thumbnail PNG (see finding #6). That gives the build-history list a visual without forcing a 3D load for every row.

### 5. Any GPU-accelerated opportunities in the DRC clearance check (O(n²) pairwise)?

**Yes — this is the single strongest GPU-compute opportunity in the manufacturing layer. HIGH severity finding.**

The clearance check (`vendor_drc.py:369-442`) is textbook embarrassingly-parallel pairwise geometry:

```python
for i in range(n):
    for j in range(i + 1, n):
        # bounding-box pre-filter
        # _segment_gap (4x point-to-segment distance + intersection test)
```

This is O(n²) within each layer bucket, in pure Python, on the CPU, in the daemon process. The bounding-box AABB pre-filter helps in practice, but the worst case (dense routing layer, e.g., a BGA fanout with thousands of segments on `F.Cu`) is still quadratic. For a board with 5,000 segments on a layer, that is ~12.5M pairwise tests, each doing segment-intersection + 4 point-to-segment projections in interpreted Python. This will be the slowest thing in the pre-handoff validation gate (`handoff.py:333-366`).

**Why this is a perfect GPU compute kernel:**
- Each `(i, j)` pair is independent — zero synchronization between threads.
- The per-pair work is small and branchy (AABB reject, then 4 distance calcs) — ideal for a wide SIMD GPU.
- The data is a flat array of `float4` (start.xy, end.xy) per segment — coalesces perfectly.
- The output is a sparse violation list — classic stream-compaction pattern (atomic append or two-pass count + fill).

**A Metal compute shader sketch (the actual fix):**
```metal
// One thread per (i, j) pair. Grid dim = n*(n-1)/2.
[[kernel]] void clearance_check(
    device const Segment* segments [[buffer(0)]],   // float4 each, layer-bucketed
    device const float*    widths   [[buffer(1)]],
    constant uint&         count    [[buffer(2)]],
    constant float&        min_clearance [[buffer(3)]],
    device atomic_uint*    violation_count [[buffer(4)]],
    device ViolationOut*   violations     [[buffer(5)]],  // pre-allocated
    uint gid [[thread_position_in_grid]]
) {
    // Decompose linear gid -> (i, j) upper-triangle index
    uint i, j; decompose_upper_triangle(gid, count, i, j);
    if (i >= count || j >= count) return;

    Segment a = segments[i]; Segment b = segments[j];
    // AABB reject (expanded by min_clearance + half-widths)
    if (aabb_disjoint(a, b, min_clearance)) return;

    float gap = segment_gap(a, b);
    float required = min_clearance + widths[i]/2 + widths[j]/2;
    if (gap >= required) return;

    // Append to violation list (stream compaction via atomic)
    uint idx = atomic_fetch_add_explicit(violation_count, 1, memory_order_relaxed);
    violations[idx] = { i, j, gap, required };
}
```

On an M-series GPU with 32-wide SIMD, a 12.5M-pair grid dispatches in a few milliseconds. The Python loop would take seconds to minutes for the same board.

**Honest caveats (read these before you scope it):**
1. **The check runs in the Python daemon, not the Mac app.** Moving it to GPU means either (a) a Python→Metal bridge (PyObjC + Metal-cpp, or a small native helper), or (b) relocating the vendor DRC check into the Swift app and calling it over the existing JSON-RPC boundary. Option (b) is cleaner — the Swift app already owns a Metal device (via MLX), and the `NativeBoard` geometry can be serialized to it. This is a real architecture decision, not a one-day task.
2. **The AABB pre-filter already makes typical boards fast enough.** Most layers are not BGAs. The GPU win is for the pathological dense case. Measure before you migrate. Add a segment-count threshold (e.g., >2000 segments on a layer → GPU path) and keep the Python path for small boards.
3. **Determinism:** the GPU kernel must produce violations in a stable order (sort by `(i,j)` post-pass) so build-to-build diffs are meaningful. `diff_builds` (`build.py:187`) and the manifest rely on stable output. The atomic-append pattern above needs a sort pass.
4. **Single-source-of-truth:** if you migrate the clearance math to Metal, you now have two implementations (Python reference + Metal fast path) that must agree to floating-point epsilon. Keep the Python path as the deterministic reference and use the GPU path with a `--verify` mode that spot-checks.

**Recommendation:** Seed this in v7.1 as a tracked opportunity, do NOT block v7.0 on it. The current Python implementation is correct and ships. But if board sizes grow or pre-handoff validation latency becomes a complaint, this is the first thing to move to the GPU.

### 6. Should the build history include rendered thumbnails?

**Yes. Low effort, high UX value. MEDIUM finding.**

The `Build` record (`build.py:54-80`) is a frozen dataclass with `build_id`, `board_rev`, `git_sha`, `status`, `artifacts`, paths. There is no visual. The SwiftData `Project` model (`Project.swift`) has no render/thumbnail field either. So the build-history list (when it exists in the UI) will be a list of text rows: "Build abc123, rev 1.2, handed_off." That is a missed opportunity — humans recognize boards by sight, not by UUID prefix.

**Concrete design:**
- During `export_handoff`, when `include_render=True` (currently a no-op stub at `handoff.py:522-524`), generate a small thumbnail PNG (e.g., 400×300, front side, isometric) alongside the full-res render. This reuses `render_pcb` (`render.py:87`) with smaller dimensions — no new rendering code.
- Add a `thumbnail_path` field to `Build` (it is frozen, so via `dataclasses.replace` in the builder — same pattern as `transition_to`). Persist it in `build.json`.
- On the Swift side, add a `thumbnailURL` to whatever SwiftData model backs the build-history row, and display it via the existing `Image(nsImage:)` pattern. Cache aggressively.
- The thumbnail is non-critical (like STEP/render): tolerate its absence, fall back to a placeholder SF Symbol.

This is the cheapest "make the product feel alive" change in this review. The render infrastructure exists; the field just needs to be plumbed. The `include_render` flag is already there and already defaulted off — flip it on for the thumbnail-size path only (cheap, ~5-10s vs the full-res 180s ceiling).

---

## Severity Summary

| # | Severity | Category | Finding | Action |
|---|----------|----------|---------|--------|
| 5 | **HIGH** | GPU Compute | O(n²) clearance check in pure Python; ideal Metal compute kernel candidate | Seed v7.1; do NOT block v7.0 |
| 1 | **MEDIUM** | Rendering | No 3D viewer; static PNG only. SceneKit STEP inspector recommended | v7.1 feature |
| 2 | **MEDIUM** | Visualization | Vendor DRC violations lack coordinates for 3D overlay; data lift needed | Coordinate-surface refactor now (low-risk) |
| 6 | **MEDIUM** | UX | No build-history thumbnails; `include_render` is a no-op stub | v7.1, cheap |
| 3 | INFO | Interchange | STEP is correct format; do NOT invent Metal mesh format | No action — current choice is right |
| 4 | INFO | Scope | Interactive 3D belongs in Mac app, not in handoff zip | No action — current boundary is right |

---

## What Is Right Today (Do Not Break)

- **kicad-cli PNG renders for chat bubbles** (`render.py`, `PCBPreviewView.swift`) — correct, cacheable, shippable. Keep.
- **STEP in the handoff zip** (`handoff.py:496`) — correct industry format. Keep.
- **Magic-byte verification** (`PCBPreviewView.swift:114`, T-172-01) — good security hygiene on the render path. Keep.
- **`PreviewRenderer` protocol** (`InlineRenderingTypes.swift:154`) — the UI depends on a protocol, not the daemon. This means a future `SceneKitPreviewRenderer` (for 3D) and `MetalDrcRenderer` (for overlays) slot in without touching `PCBPreviewView`. The architecture is already ready for the GPU additions above. Good design.
- **Bounding-box AABB pre-filter** in `_check_clearance` — the right optimization for the CPU path. Keep even after a GPU path is added (the GPU kernel reuses the same AABB logic).

---

## SLC Compliance

- v7.0 manufacturing layer as-shipped: **PASS** (no GPU work required to ship)
- v7.1 rendering track (if scoped per findings 1, 2, 5, 6): **conditional PASS** — requires the coordinate-lift refactor (finding 2) and a documented decision on Python-vs-Swift ownership of the GPU DRC path (finding 5) before implementation begins.

---

## Bottom Line

The v7.0 layer is correct and ships. The current PNG-render approach is the right default. But the project is leaving the Apple Silicon GPU entirely idle for visualization, and the vendor DRC clearance check is the one place where GPU compute would deliver a measurable, user-facing speedup on large boards. Seed both for v7.1: (a) a SceneKit-based 3D inspector that consumes the STEP the handoff already produces, with vendor-DRC violations as a red overlay pass, and (b) a Metal compute kernel for the O(n²) clearance check, gated behind a segment-count threshold with the Python path retained as the deterministic reference. Plus the cheap thumbnail win for build history.

None of this blocks Phase 209. Vote: **APPROVE**.
