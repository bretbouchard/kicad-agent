//
//  ImageAttachmentFactory.swift
//  Volta
//
//  Phase 239 — Image Attachment UI
//
//  Builds an `ImageAttachment` from an arbitrary file URL, with magic-byte
//  sniffing and pixel-dimension detection. Used by the file picker, drag-
//  and-drop handler, and clipboard paste pipeline.
//
//  ponytail: one factory entrypoint per source. The compression step
//  (resize + re-encode) lives in `ImageAttachmentCompressor` so the
//  factory stays a thin reader.
//

import Foundation
import AppKit

/// Errors raised while converting a URL into a chat ImageAttachment.
enum ImageAttachmentError: Error, LocalizedError, Equatable {
    case fileNotReadable(URL)
    case unsupportedMimeType(String)
    case invalidImage(URL)

    var errorDescription: String? {
        switch self {
        case .fileNotReadable(let url):
            return "Can't read file at \(url.path)."
        case .unsupportedMimeType(let mime):
            return "Unsupported image type: \(mime). Use PNG, JPEG, or HEIC."
        case .invalidImage(let url):
            return "File is not a valid image: \(url.lastPathComponent)."
        }
    }
}

/// One factory entrypoint per source. Returns the raw attachment;
///// compression (resize + re-encode) is a separate concern.
enum ImageAttachmentFactory {
    /// Read the file at `url` and produce an `ImageAttachment`.
    /// Throws `ImageAttachmentError` if the file isn't a readable,
    /// supported image.
    static func make(from url: URL) throws -> ImageAttachment {
        // 1. Reachability.
        guard let data = try? Data(contentsOf: url) else {
            throw ImageAttachmentError.fileNotReadable(url)
        }
        guard !data.isEmpty else {
            throw ImageAttachmentError.fileNotReadable(url)
        }

        // 2. Mime-type sniff — first by extension, then by magic bytes
        //    (NSImage can't read HEIC reliably, so we need this for
        //    the metadata even if NSImage fails later).
        let mimeType = sniffMimeType(url: url, data: data)
        guard ImageAttachment.acceptedMimeTypes.contains(mimeType) else {
            throw ImageAttachmentError.unsupportedMimeType(mimeType)
        }

        // 3. Pixel dimensions from NSImage.
        guard let image = NSImage(data: data) else {
            throw ImageAttachmentError.invalidImage(url)
        }
        let width = Int(image.size.width.rounded())
        let height = Int(image.size.height.rounded())

        // 4. Attributes.
        let size = (try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? data.count
        return ImageAttachment(
            fileName: url.lastPathComponent,
            fileSizeBytes: Int64(size),
            mimeType: mimeType,
            url: url,
            pixelWidth: width,
            pixelHeight: height
        )
    }

    /// Determine the mime type — prefer the extension (fast), fall back
    /// to magic-byte sniffing. Unknown extensions return `application/octet-stream`
    /// so the caller can reject them with a clear message.
    static func sniffMimeType(url: URL, data: Data) -> String {
        let ext = url.pathExtension.lowercased()
        switch ext {
        case "png":  return "image/png"
        case "jpg", "jpeg": return "image/jpeg"
        case "heic", "heif": return "image/heic"
        default: break
        }
        if let sniffed = KCAttachment.sniffMimeType(data: data) {
            return sniffed
        }
        return "application/octet-stream"
    }
}
