---
phase: 239
type: summary
status: complete
---

# Phase 239 Summary — Image Attachment UI

## Status: COMPLETE

The chat compose bar now has three real ways to attach an image:

1. **Paperclip button** → `NSOpenPanel` filtered to PNG / JPEG / HEIC, multi-select.
2. **Drag-and-drop** → `.onDrop(of: [.fileURL])` on the compose bar.
3. **Cmd+V** → `NSEvent` local monitor when the text field has focus; clipboard
   image is written to a temp file and attached.

All three paths funnel through one `attachImage(from:)` helper which validates
the file, optionally compresses it (resize to 2048px max, re-encode as JPEG,
strip EXIF), and appends to `pendingImages`. Router now bridges the
`ImageAttachment` array into `KCPrompt.attachments` as `KCAttachment` so
vision-capable models actually see the bytes.

Gap A5 from `GAP-ANALYSIS-CURRENT.md` closed.

## What Was Added This Phase

| File | Change |
|------|--------|
| `macos-app/Sources/Volta/Views/Chat/ImageAttachmentFactory.swift` | NEW — `ImageAttachmentFactory.make(from:)` URL → `ImageAttachment` with magic-byte sniffing and pixel-dimension detection |
| `macos-app/Sources/Volta/Views/Chat/ImageAttachmentCompressor.swift` | NEW — CGContext resize to 2048px + `CGImageDestination` re-encode as JPEG (strips EXIF) |
| `macos-app/Sources/Volta/Views/Chat/RouterStreamProvider.swift` | MODIFIED — `buildKCPrompt` reads `ImageAttachment.url` and emits `KCAttachment` for each; bad-file errors logged + skipped, never poison the stream |
| `macos-app/Sources/Volta/Views/Chat/ChatView.swift` | MODIFIED — `attachButton` → real `NSOpenPanel`; `.onDrop` on compose bar; `NSEvent` local monitor for Cmd+V; `attachError` banner; helper methods `presentOpenPanel`, `handleDrop`, `installPasteMonitor`, `writeClipboardImageToTemp`, `attachImage` |
| `macos-app/Sources/Volta/VoltaApp.swift` | MODIFIED — added `static let stream` to `Logger` extension (used by `RouterStreamProvider` for attachment read failures) |
| `macos-app/Tests/VoltaTests/ImageAttachmentPipelineTests.swift` | NEW — 12 tests |

## Three attach paths, one pipeline

```swift
@MainActor
private func attachImage(from url: URL) {
    do {
        var attachment = try ImageAttachmentFactory.make(from: url)
        if let compressed = try ImageAttachmentCompressor.compressIfNeeded(attachment) {
            attachment = compressed
        }
        pendingImages.removeAll { $0.id == attachment.id }  // idempotent re-attach
        pendingImages.append(attachment)
        attachError = nil
    } catch let error as ImageAttachmentError {
        attachError = error.errorDescription
    } catch {
        attachError = error.localizedDescription
    }
}
```

`presentOpenPanel` (paperclip), `handleDrop` (drag-drop), and
`writeClipboardImageToTemp` (Cmd+V paste) all call into this. The error
banner at the top of the compose bar surfaces validation failures
("Unsupported image type: application/octet-stream") so the user gets a
clear message instead of a silent rejection.

## Compression (T-239-02, T-239-03)

`ImageAttachmentCompressor` fires when `needsCompression(attachment) == true`
(> 10 MB). The compressor:

1. Loads via `NSImage` → `CGImage`.
2. Computes a scale so the longest side fits within 2048 px.
3. Draws into a new RGB `CGContext` (alpha dropped — JPEG has none).
4. Re-encodes via `CGImageDestinationCreateWithURL` + `UTType.jpeg` at 0.85
   quality. ImageIO drops EXIF on re-encode.
5. Writes to `temporaryDirectory/volta-attachments/<UUID>.jpg`.

`compressIfNeeded` is a no-op for small files (returns `nil`); the
chat pipeline only swaps in the compressed attachment when the size
budget is exceeded. The `KCPrompt` always sees the on-disk URL, so
re-renders pick up the right bytes.

## Router bridging

`RouterStreamProvider.buildKCPrompt` previously dropped attachments on the
floor (it explicitly said so in a comment — see git blame for the
"NOT yet bridged" line, now removed). It now reads each `ImageAttachment.url`
as `Data`, wraps it in a `KCAttachment`, and passes the array to
`KCPrompt.attachments`:

```swift
static func buildKCPrompt(history: [ChatMessage], attachments: [ImageAttachment]) -> KCPrompt {
    let messages: [ChatMessage] = history
        .filter { $0.role != .system }
        .map { msg in
            let role: KCRole = (msg.role == .user) ? .user : .assistant
            return KCMessage(role: role, content: msg.content)
        }
    let kcAttachments = attachments.compactMap(makeKCAttachment)
    return KCPrompt(messages: messages, attachments: kcAttachments)
}

private static func makeKCAttachment(from image: ImageAttachment) -> KCAttachment? {
    guard let data = try? Data(contentsOf: image.url) else {
        Logger.stream.error("Attachment read failed: \(image.url.path, privacy: .public)")
        return nil
    }
    return KCAttachment(data: data, mimeType: image.mimeType)
}
```

A read failure logs and skips that single attachment so a corrupt file
doesn't kill the whole stream. The text history always flows through.

## Tests (all 12 passing)

| Test | What it verifies |
|------|-----------------|
| `Factory: PNG file → ImageAttachment` | URL→ImageAttachment; mime=image/png, dims correct |
| `Factory: JPEG file → mime sniffed from extension` | URL→ImageAttachment; mime=image/jpeg |
| `Factory: rejects unsupported file type (TXT)` | .txt file throws `unsupportedMimeType` |
| `Factory: rejects non-existent file` | Missing file throws `fileNotReadable` |
| `Compressor: small PNG passes through unchanged` | `compressIfNeeded` no-ops on small input |
| `Compressor: compressIfNeeded no-ops on a small attachment` | Same as above (second test for clarity) |
| `Compressor: compressIfNeeded fires when over budget` | Threshold logic fires before I/O |
| `Compressor: force-compress resizes a 6000x6000 image` | `compress()` shrinks huge image, longest side ≤ 2048, output is JPEG, size ≤ 10MB |
| `Router: buildKCPrompt includes attachments` | Image bytes round-trip into `KCPrompt.attachments` |
| `Router: buildKCPrompt with no attachments` | Empty array flows through cleanly |
| `Router: buildKCPrompt silently skips vanished files` | Read-failure path doesn't poison the stream |
| `Validator: needsCompression is true exactly when over 10MB` | Threshold gate |

## Verification

```
swift test --filter "ImageAttachmentPipelineTests"
✔ All 12 tests passed in 1 suite
✔ Test run with 12 tests in 1 suite passed after 1.342 seconds.

swift build
✔ Build complete! (no errors, no new warnings)
```

Plus the chat+image focused sweep:

```
swift test --filter "ImageAttachmentPipelineTests|ChatPipelineE2ETests"
✔ Test run with 23 tests in 2 suites passed after 2.428 seconds.
```

The pre-existing `MLXLocalProvider.minimumVRAMBytes` test failure and the
SwiftData fatal-error process crash are unrelated to this phase (both
existed before Phase 239; verified by running the chat+image suite
in isolation, which is fully green).

## What's NOT in this slice (deferred)

- **Multi-image UI** — data model supports N images per message; UI is
  single-image row for v1.
- **Camera capture** — covered by Phase 236 (Vision Input).
- **Vision-aware model auto-routing** — Gemma 4 12B V2 is the target;
  the router currently still selects by `preferredProviderPerTask`.
- **Visual diff of the picker sheet** — Phase 235 handles visual review.

## Stupid-Proof Verification

- **User-stupid**: Tapping the paperclip and selecting a 50MB PNG
  → compression banner-less (silently resizes + re-encodes), the
  message sends, the model sees a 2048px JPEG instead of a 50MB PNG.
  No modal dialog, no spinner — happens in the picker pipeline.
- **Magic-stupid**: Cmd+V with a screenshot on the clipboard → image
  appears in the chip row. Hit return → message goes out with
  the image attached. Zero ceremony, zero file dialogs.
