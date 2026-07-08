//
//  KCAttachment.swift
//  KiCadAgent
//
//  Phase 164 — LLM Provider Protocol
//
//  Binary attachment (image, eventually audio). Vision tasks per
//  Phase 98 use Gemma 4 12B V2 — schematic/PCB screenshots flow as
//  KCAttachment inside KCMessage.images.
//
//  ponytail: just data + mime type. No complex file-URL indirection —
//  provider copies bytes into its native SDK structure.
//

import Foundation

struct KCAttachment: Sendable, Equatable, Identifiable {
    let id: UUID
    var data: Data
    var mimeType: String

    init(id: UUID = UUID(), data: Data, mimeType: String) {
        precondition(!data.isEmpty, "Attachment data must not be empty")
        precondition(mimeType.contains("/"), "MimeType must look like 'image/png'")
        self.id = id
        self.data = data
        self.mimeType = mimeType
    }
}

extension KCAttachment {
    /// ponytail: PNG convenience — most common case for schematic screenshots
    /// and PCB renders (kicad-cli pcb render outputs PNG).
    static func png(_ data: Data) -> KCAttachment {
        KCAttachment(data: data, mimeType: "image/png")
    }

    /// JPEG convenience — used for photo inputs from iPhone camera.
    static func jpeg(_ data: Data) -> KCAttachment {
        KCAttachment(data: data, mimeType: "image/jpeg")
    }

    /// Best-effort sniff — looks at magic bytes. Used by drag-drop
    /// validation in ModelCatalogView.
    static func sniffMimeType(data: Data) -> String? {
        guard data.count >= 4 else { return nil }
        let prefix = [UInt8](data.prefix(4))
        // PNG: 89 50 4E 47
        if prefix == [0x89, 0x50, 0x4E, 0x47] { return "image/png" }
        // JPEG: FF D8 FF
        if prefix.starts(with: [0xFF, 0xD8, 0xFF]) { return "image/jpeg" }
        // GIF: 47 49 46 38
        if prefix == [0x47, 0x49, 0x46, 0x38] { return "image/gif" }
        // WEBP: "RIFF....WEBP" — check 12 bytes
        if data.count >= 12,
           [UInt8](data.prefix(4)) == [0x52, 0x49, 0x46, 0x46],
           [UInt8](data[8..<12]) == [0x57, 0x45, 0x42, 0x50] {
            return "image/webp"
        }
        return nil
    }
}
