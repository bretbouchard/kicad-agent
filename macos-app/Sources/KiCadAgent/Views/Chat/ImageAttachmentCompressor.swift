//
//  ImageAttachmentCompressor.swift
//  KiCadAgent
//
//  Phase 239 — Image Attachment UI
//
//  Compresses an `ImageAttachment` that exceeds the chat size budget
//  (10 MB). Strategy: scale to fit within 2048×2048, re-encode as JPEG
//  at 0.85 quality, write to a new temp file. JPEG re-encoding also
//  strips EXIF metadata (Apple's CGImageDestination drops it by default
//  when re-encoding).
//
//  ponytail: pure function over an ImageAttachment. Caller decides
//  when to call (file picker, drop, paste). Compression is the
//  last step before the bytes are bridged into KCAttachment.
//

import Foundation
import AppKit
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers

/// Resize + re-encode an oversized image attachment.
enum ImageAttachmentCompressor {
    /// Returns a new attachment if compression was needed, or `nil`
    /// if the input was within the size budget. The new attachment
    /// points to a temp file (caller is responsible for cleanup, or
    /// can let the OS reap it on next boot — temp dir is volatile).
    static func compressIfNeeded(_ attachment: ImageAttachment) throws -> ImageAttachment? {
        guard ImageAttachmentValidator.needsCompression(attachment) else {
            return nil
        }
        return try compress(attachment)
    }

    /// Force compression (used by tests to verify a 20MB image is
    /// brought under the 10MB budget even if its on-disk size
    /// doesn't strictly exceed the limit after a sample read).
    static func compress(_ attachment: ImageAttachment) throws -> ImageAttachment {
        guard let nsImage = NSImage(contentsOf: attachment.url),
              let cgImage = nsImage.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
            throw ImageAttachmentError.invalidImage(attachment.url)
        }

        // Scale so the longest side is at most `maxDimension`.
        let maxSide = CGFloat(ImageAttachment.maxDimension)
        let width = CGFloat(cgImage.width)
        let height = CGFloat(cgImage.height)
        let scale = min(1.0, maxSide / max(width, height))
        let newWidth = Int((width * scale).rounded())
        let newHeight = Int((height * scale).rounded())

        // Draw into an RGB color space to drop alpha (JPEG has none).
        let colorSpace = CGColorSpaceCreateDeviceRGB()
        let bitmapInfo = CGImageAlphaInfo.noneSkipLast.rawValue
        guard let ctx = CGContext(
            data: nil,
            width: newWidth,
            height: newHeight,
            bitsPerComponent: 8,
            bytesPerRow: 0,
            space: colorSpace,
            bitmapInfo: bitmapInfo
        ) else {
            throw ImageAttachmentError.invalidImage(attachment.url)
        }
        ctx.interpolationQuality = .high
        ctx.draw(cgImage, in: CGRect(x: 0, y: 0, width: newWidth, height: newHeight))
        guard let resized = ctx.makeImage() else {
            throw ImageAttachmentError.invalidImage(attachment.url)
        }

        // Re-encode as JPEG via ImageIO (strips EXIF by default).
        let outputURL = makeTempJPEGURL(for: attachment)
        guard let dest = CGImageDestinationCreateWithURL(
            outputURL as CFURL,
            UTType.jpeg.identifier as CFString,
            1,
            nil
        ) else {
            throw ImageAttachmentError.invalidImage(attachment.url)
        }
        let options: [CFString: Any] = [
            kCGImageDestinationLossyCompressionQuality: 0.85
        ]
        CGImageDestinationAddImage(dest, resized, options as CFDictionary)
        guard CGImageDestinationFinalize(dest) else {
            throw ImageAttachmentError.invalidImage(attachment.url)
        }

        let data = try Data(contentsOf: outputURL)
        return ImageAttachment(
            id: attachment.id,
            fileName: attachment.fileName,
            fileSizeBytes: Int64(data.count),
            mimeType: "image/jpeg",
            url: outputURL,
            pixelWidth: newWidth,
            pixelHeight: newHeight
        )
    }

    /// Make a temp URL for the compressed JPEG. We use a UUID-prefixed
    /// filename so concurrent compressions don't clobber each other.
    private static func makeTempJPEGURL(for attachment: ImageAttachment) -> URL {
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent("kicad-agent-attachments", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let baseName = (attachment.fileName as NSString).deletingPathExtension
        return dir.appendingPathComponent("\(UUID().uuidString)-\(baseName).jpg")
    }
}
