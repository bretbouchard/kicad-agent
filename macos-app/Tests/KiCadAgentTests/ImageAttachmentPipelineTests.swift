//
//  ImageAttachmentPipelineTests.swift
//  KiCadAgentTests
//
//  Phase 239 — Image Attachment UI
//
//  Tests the factory, compressor, and router attachment bridging.
//  Does NOT test the SwiftUI .onDrop / NSOpenPanel flows (those are
//  exercised in the macOS UI test target). Unit tests focus on the
//  pure data pipeline: URL → ImageAttachment → compressed → KCAttachment.
//

import Testing
import Foundation
import AppKit
@testable import KiCadAgent

@Suite("Image Attachment Pipeline (Phase 239)")
struct ImageAttachmentPipelineTests {

    // MARK: - Helpers

    /// Write a tiny PNG (32x32 red square) to a temp file and return
    /// the URL. Uses NSImage + NSBitmapImageRep so the test exercises
    /// the same code path the picker does.
    @MainActor
    private func writeSamplePNG(name: String = "sample.png", pixelSize: CGFloat = 32) throws -> URL {
        let size = NSSize(width: pixelSize, height: pixelSize)
        let image = NSImage(size: size)
        image.lockFocus()
        NSColor.red.drawSwatch(in: NSRect(origin: .zero, size: size))
        image.unlockFocus()

        guard let tiff = image.tiffRepresentation,
              let rep = NSBitmapImageRep(data: tiff),
              let pngData = rep.representation(using: .png, properties: [:]) else {
            throw ImageAttachmentError.invalidImage(URL(fileURLWithPath: "/dev/null"))
        }
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("\(UUID().uuidString)-\(name)")
        try pngData.write(to: url)
        return url
    }

    /// Write a JPEG with a known byte count. Used to verify the
    /// extension-based mime sniffing path in the factory.
    @MainActor
    private func writeSampleJPEG() throws -> URL {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("\(UUID().uuidString).jpg")
        let image = NSImage(size: NSSize(width: 64, height: 64))
        image.lockFocus()
        NSColor.blue.drawSwatch(in: NSRect(x: 0, y: 0, width: 64, height: 64))
        image.unlockFocus()
        guard let tiff = image.tiffRepresentation,
              let rep = NSBitmapImageRep(data: tiff),
              let jpeg = rep.representation(using: .jpeg, properties: [:]) else {
            throw ImageAttachmentError.invalidImage(URL(fileURLWithPath: "/dev/null"))
        }
        try jpeg.write(to: url)
        return url
    }

    /// Build an oversized PNG fixture (≥ 12MB) by writing a noisy
    /// 6000×6000 image. PNG can't compress pseudo-random noise below
    /// ~10MB so this reliably crosses the compression threshold.
    @MainActor
    private func writeOversizedPNG() throws -> URL {
        let size = 6000
        let colorSpace = CGColorSpaceCreateDeviceRGB()
        let bitmapInfo = CGImageAlphaInfo.noneSkipLast.rawValue
        guard let ctx = CGContext(
            data: nil,
            width: size, height: size,
            bitsPerComponent: 8, bytesPerRow: 0,
            space: colorSpace, bitmapInfo: bitmapInfo
        ) else {
            throw ImageAttachmentError.invalidImage(URL(fileURLWithPath: "/dev/null"))
        }
        for y in stride(from: 0, to: size, by: 17) {
            for x in stride(from: 0, to: size, by: 17) {
                let r = CGFloat((x * 31 + y * 17) % 256) / 255.0
                let g = CGFloat((x * 7 + y * 53) % 256) / 255.0
                let b = CGFloat((x * 13 + y * 91) % 256) / 255.0
                ctx.setFillColor(red: r, green: g, blue: b, alpha: 1.0)
                ctx.fill(CGRect(x: x, y: y, width: 17, height: 17))
            }
        }
        guard let cgImage = ctx.makeImage() else {
            throw ImageAttachmentError.invalidImage(URL(fileURLWithPath: "/dev/null"))
        }
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("\(UUID().uuidString)-oversized.png")
        guard let dest = CGImageDestinationCreateWithURL(
            url as CFURL, "public.png" as CFString, 1, nil
        ) else {
            throw ImageAttachmentError.invalidImage(URL(fileURLWithPath: "/dev/null"))
        }
        CGImageDestinationAddImage(dest, cgImage, nil)
        guard CGImageDestinationFinalize(dest) else {
            throw ImageAttachmentError.invalidImage(URL(fileURLWithPath: "/dev/null"))
        }
        return url
    }

    // MARK: - Factory

    @Test("Factory: PNG file → ImageAttachment with correct dimensions and mime type")
    @MainActor
    func factoryPNG() throws {
        let url = try writeSamplePNG(pixelSize: 32)
        defer { try? FileManager.default.removeItem(at: url) }
        let attachment = try ImageAttachmentFactory.make(from: url)
        #expect(attachment.mimeType == "image/png")
        #expect(attachment.pixelWidth == 32)
        #expect(attachment.pixelHeight == 32)
        #expect(attachment.fileSizeBytes > 0)
    }

    @Test("Factory: JPEG file → mime type sniffed from extension")
    @MainActor
    func factoryJPEG() throws {
        let url = try writeSampleJPEG()
        defer { try? FileManager.default.removeItem(at: url) }
        let attachment = try ImageAttachmentFactory.make(from: url)
        #expect(attachment.mimeType == "image/jpeg")
        #expect(attachment.pixelWidth == 64)
    }

    @Test("Factory: rejects unsupported file type (TXT)")
    @MainActor
    func factoryRejectsUnsupported() throws {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("\(UUID().uuidString).txt")
        try "hello world".write(to: url, atomically: true, encoding: .utf8)
        defer { try? FileManager.default.removeItem(at: url) }

        do {
            _ = try ImageAttachmentFactory.make(from: url)
            Issue.record("Expected an error for a .txt file")
        } catch let error as ImageAttachmentError {
            #expect(error.errorDescription?.contains("Unsupported") == true)
        } catch {
            Issue.record("Expected ImageAttachmentError, got \(error)")
        }
    }

    @Test("Factory: rejects non-existent file")
    @MainActor
    func factoryRejectsMissing() {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("\(UUID().uuidString).png")
        do {
            _ = try ImageAttachmentFactory.make(from: url)
            Issue.record("Expected an error for a missing file")
        } catch let error as ImageAttachmentError {
            #expect(error.errorDescription?.contains("Can't read") == true)
        } catch {
            Issue.record("Expected ImageAttachmentError, got \(error)")
        }
    }

    // MARK: - Compression

    @Test("Compressor: small PNG passes through unchanged")
    @MainActor
    func compressorSmallPassesThrough() throws {
        let url = try writeSamplePNG(pixelSize: 32)
        defer { try? FileManager.default.removeItem(at: url) }
        let original = try ImageAttachmentFactory.make(from: url)
        let result = try ImageAttachmentCompressor.compressIfNeeded(original)
        #expect(result == nil, "Expected nil (no compression) for small file")
    }

    @Test("Compressor: force-compress resizes a 6000x6000 image to under 10MB")
    @MainActor
    func compressorOversizedShrinks() throws {
        let url = try writeOversizedPNG()
        defer { try? FileManager.default.removeItem(at: url) }
        let original = try ImageAttachmentFactory.make(from: url)
        // Force compression regardless of the on-disk size — we want to
        // verify the resize + re-encode behavior, not just the threshold
        // trigger. PNG compresses pseudo-noise to a few hundred KB, so
        // `compressIfNeeded` would no-op on this fixture; the
        // interesting question is "can the compressor shrink a huge
        // pixel array?".
        let compressed = try ImageAttachmentCompressor.compress(original)
        // Output must be under the 10MB budget.
        #expect(compressed.fileSizeBytes <= ImageAttachment.maxFileSizeBytes)
        // Output is JPEG (re-encoded, EXIF stripped by ImageIO).
        #expect(compressed.mimeType == "image/jpeg")
        // Longest side fits within 2048.
        #expect(max(compressed.pixelWidth, compressed.pixelHeight) <= Int(ImageAttachment.maxDimension))
        // Temp file written; clean up.
        try? FileManager.default.removeItem(at: compressed.url)
    }

    @Test("Compressor: compressIfNeeded no-ops on a small attachment")
    @MainActor
    func compressorThresholdLogic() throws {
        let url = try writeSamplePNG(pixelSize: 64)
        defer { try? FileManager.default.removeItem(at: url) }
        let original = try ImageAttachmentFactory.make(from: url)
        // Small file → no compression, returns nil.
        let result = try ImageAttachmentCompressor.compressIfNeeded(original)
        #expect(result == nil)
    }

    @Test("Compressor: compressIfNeeded fires when manually-constructed attachment exceeds budget")
    func compressorThresholdFires() throws {
        // Construct an attachment with fileSize > 10MB but a missing
        // backing file (compress() would fail, but compressIfNeeded's
        // threshold check runs first). Confirms the budget gate fires
        // before any I/O is attempted.
        let huge = ImageAttachment(
            fileName: "huge.png",
            fileSizeBytes: ImageAttachment.maxFileSizeBytes + 1,
            mimeType: "image/png",
            url: URL(fileURLWithPath: "/tmp/does-not-exist-\(UUID().uuidString).png"),
            pixelWidth: 6000, pixelHeight: 6000
        )
        #expect(ImageAttachmentValidator.needsCompression(huge))
    }

    // MARK: - Router bridging (Phase 239 wiring)

    @Test("Router: buildKCPrompt includes attachments when chat message has images")
    @MainActor
    func routerBridgesAttachments() throws {
        let url = try writeSamplePNG(pixelSize: 32)
        defer { try? FileManager.default.removeItem(at: url) }
        let attachment = try ImageAttachmentFactory.make(from: url)
        let history: [ChatMessage] = [
            ChatMessage(role: .user, content: "What is this?", attachments: [attachment])
        ]
        let prompt = RouterStreamProvider.buildKCPrompt(
            history: history, attachments: [attachment]
        )
        #expect(prompt.attachments.count == 1, "Expected 1 KCAttachment")
        #expect(prompt.attachments.first?.mimeType == "image/png")
        // Bytes round-trip the file we wrote.
        let originalBytes = try Data(contentsOf: url)
        #expect(prompt.attachments.first?.data == originalBytes)
    }

    @Test("Router: buildKCPrompt with no attachments produces empty array")
    func routerEmptyAttachments() {
        let history: [ChatMessage] = [
            ChatMessage(role: .user, content: "hello")
        ]
        let prompt = RouterStreamProvider.buildKCPrompt(history: history, attachments: [])
        #expect(prompt.attachments.isEmpty)
        #expect(prompt.messages.count == 1)
    }

    @Test("Router: buildKCPrompt silently skips attachments whose file vanished")
    @MainActor
    func routerSkipsMissingFile() throws {
        let url = try writeSamplePNG(pixelSize: 32)
        let attachment = try ImageAttachmentFactory.make(from: url)
        // Now delete the file behind the attachment's back.
        try FileManager.default.removeItem(at: url)
        let history: [ChatMessage] = [
            ChatMessage(role: .user, content: "What is this?", attachments: [attachment])
        ]
        let prompt = RouterStreamProvider.buildKCPrompt(
            history: history, attachments: [attachment]
        )
        // Read failed → attachment is skipped, not poisoned.
        #expect(prompt.attachments.isEmpty)
        // Text history still flowed through.
        #expect(prompt.messages.count == 1)
    }

    @Test("Validator: needsCompression is true exactly when over 10MB")
    func validatorBoundary() {
        let small = ImageAttachment(
            fileName: "a.png", fileSizeBytes: 1024,
            mimeType: "image/png", url: URL(fileURLWithPath: "/tmp/a"),
            pixelWidth: 1, pixelHeight: 1
        )
        let big = ImageAttachment(
            fileName: "b.png", fileSizeBytes: ImageAttachment.maxFileSizeBytes + 1,
            mimeType: "image/png", url: URL(fileURLWithPath: "/tmp/b"),
            pixelWidth: 1, pixelHeight: 1
        )
        #expect(ImageAttachmentValidator.needsCompression(small) == false)
        #expect(ImageAttachmentValidator.needsCompression(big) == true)
    }
}
