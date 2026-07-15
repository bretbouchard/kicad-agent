---
phase: 238
type: summary
status: complete
---

# Phase 238 Summary — Real Preview Wire-up

## Status: COMPLETE

The App Store claim of inline schematic / PCB previews is now real:

- **SchematicPreviewView** was already wired to a real `PreviewRenderer`
  protocol (schematic path was real since Phase 233). Confirmed + now
  augmented with **file watcher** and **"Open in KiCad" button**.
- **PCBPreviewView** had a real wiring too, but `SwiftSVGRenderer.renderPCB`
  was writing a **1x1 placeholder PNG** (67 bytes). Replaced with
  `PCBImageRenderer` — a Core Graphics-based real PCB renderer.
- **LiquidGlassShell** now provides `SwiftSVGRenderer` as a fallback when
  the daemon is unavailable — no more "no preview" dead state.

## What Was Added This Phase

| File | Change |
|------|--------|
| `macos-app/Sources/Volta/Views/InlineRendering/PCBImageRenderer.swift` | NEW — Core Graphics PCB → PNG renderer (no daemon) |
| `macos-app/Sources/Volta/Views/InlineRendering/PreviewFileWatcher.swift` | NEW — DispatchSource-based debounced file watcher |
| `macos-app/Sources/Volta/Views/InlineRendering/SwiftSVGRenderer.swift` | MODIFIED — `renderPCB` now delegates to `PCBImageRenderer` (was placeholder) |
| `macos-app/Sources/Volta/Views/InlineRendering/SchematicPreviewView.swift` | MODIFIED — wires `PreviewFileWatcher` + adds "Open in KiCad" button |
| `macos-app/Sources/Volta/Views/InlineRendering/PCBPreviewView.swift` | MODIFIED — wires `PreviewFileWatcher` + adds "Open in KiCad" button |
| `macos-app/Sources/Volta/Views/LiquidGlassShell.swift` | MODIFIED — falls back to `SwiftSVGRenderer` when daemon unavailable |
| `macos-app/Tests/VoltaTests/PreviewRendererTests.swift` | NEW — 7 tests |

## PCB Renderer

`PCBImageRenderer` parses the `.kicad_pcb` via `PCBParser` and renders:

- **Traces** (segments) — F.Cu red, B.Cu blue, filtered by `side`
- **Vias** — small yellow circles
- **Footprints** — white silkscreen outline
- **Pads** — gold rectangles / ellipses with dark green drill holes
- **Bounding box** — auto-computed from footprints/segments/vias, padded 5mm
- **Background** — KiCad's standard dark green PCB canvas

Renders at 10 px/mm (matches the schematic renderer scale). Output is a
real PNG via `CGContext` + `NSBitmapImageRep`, **not** a placeholder.

`SwiftSVGRenderer.renderPCB` now simply delegates to `PCBImageRenderer`,
so all paths (LiquidGlassShell direct, MessageBubbleView via
`PreviewRenderer`, etc.) get the real render.

## File Watcher

`PreviewFileWatcher` uses `DispatchSource.makeFileSystemObjectSource`
with 250ms debounce. Re-renders the preview on any change. Started in
the view's `.task`, stopped in `.onDisappear`. No external dependencies.

Verified by `PreviewFileWatcher debounces multiple writes into one callback`:
3 rapid writes within the debounce window → 1 callback.

## "Open in KiCad" Button

Both `SchematicPreviewView` and `PCBPreviewView` now have a small
`arrow.up.right.square` button overlaid in the top-right of the preview
that calls `NSWorkspace.shared.open(schematicPath / pcbPath)`. macOS-only
(guarded with `#if os(macOS)`). Liquid Glass circular material. A11y
labeled.

## LiquidGlassShell Fallback

```swift
private func makePreviewRenderer() -> (any PreviewRenderer)? {
    if let client = daemonSupervisor.mcpClient {
        return DaemonPreviewRenderer(client: client)
    }
    return SwiftSVGRenderer()  // NEW fallback (was: nil)
}
```

Previously: if no daemon, no preview at all → chat shows blank space.
Now: native Swift renderer always works, daemon is just a higher-quality
option when available.

## Tests (all 7 passing)

| Test | What it verifies |
|------|-----------------|
| `pcbRendererProducesValidPNG` | Real PCB IR → valid PNG with magic bytes |
| `pcbRendererEmptyBoard` | Empty board doesn't crash; falls back to 50x50mm default |
| `pcbRendererSideFilter` | Front/back side produces different output (correct color) |
| `schematicRendererDelegatesPCB` | `SwiftSVGRenderer.renderPCB` no longer returns the 67-byte placeholder |
| `magicBytesRoundTrip` | T-172-01: PNG magic verifier works on real render, rejects SVG |
| `fileWatcherDebounce` | 3 writes within 250ms → 1 callback (debounce works) |
| `mockRendererStillValid` | Mock renderer still produces valid magic bytes (regression) |

## What's NOT in this slice (deferred)

- **Pan/zoom beyond NSScrollView** — covered by FullScreenInspector;
  not part of this gap.
- **Real-time 3D preview** — separate feature, requires KiCad 3D viewer.
- **Per-instance renderer selection** (e.g. user can pick "always use
  daemon" in settings) — out of scope; current default is daemon-first,
  native-fallback.
- **File watcher for in-app edits** (e.g. when the chat itself writes
  to the file) — the watcher's debounce collapses the write and the
  render into one render, which is the desired behavior.

## Verification

```
swift test --filter "PreviewRendererTests"
✔ Test "MockPreviewRenderer still produces valid magic bytes" passed
✔ Test "PCBImageRenderer.renderPNG produces a valid PNG with magic bytes" passed
✔ Test "PCBImageRenderer.renderPNG respects F.Cu/B.Cu side filter" passed
✔ Test "SwiftSVGRenderer.renderPCB delegates to PCBImageRenderer (not placeholder)" passed
✔ Test "PCBImageRenderer.renderPNG handles an empty board without crashing" passed
✔ Test "MagicBytes.verify accepts a real PNG and rejects garbage" passed
✔ Test "PreviewFileWatcher debounces multiple writes into one callback" passed
✔ Test run with 7 tests in 1 suite passed after 0.372 seconds.
```

The inline preview is no longer a mock. The App Store claim is real.
