//
//  KicadAgentDocument.swift
//  Volta
//
//  Phase 190 — iCloud Drive Bundle
//
//  .kicadagent document type — FileDocument backed by a directory bundle.
//  Stores conversation.jsonl, decisions.jsonl, snapshots/, renders/.
//
//  FILE-01/02/03/04/05/06: file format requirements.
//

import Foundation
import SwiftUI
import UniformTypeIdentifiers

/// Uniform type identifier for .kicadagent bundles.
extension UTType {
    static let kicadAgentBundle = UTType(exportedAs: "com.kicadagent.bundle")
}

/// FileDocument representation of a .kicadagent bundle.
///
/// ponytail: directory bundle, not flat file. Each piece (conversation,
/// decisions, snapshots, renders) is a separate file for diff-friendliness.
///
/// Phase 190 note: SwiftData @Model classes (Conversation, Decision, etc.)
/// are NOT held directly in this struct — they're not Sendable (model
/// objects are bound to a ModelActor). The bundle holds serialized JSON
/// snapshots only; materialization to live SwiftData objects happens in
/// the SwiftData layer when the document is opened.
struct KicadAgentDocument: FileDocument {
    static var readableContentTypes: [UTType] { [.kicadAgentBundle] }
    static var writableContentTypes: [UTType] { [.kicadAgentBundle] }

    /// Manifest version — bump on format change.
    let manifestVersion: Int
    var projectMetadata: ProjectMetadata

    init() {
        self.manifestVersion = 1
        self.projectMetadata = ProjectMetadata(name: "Untitled")
    }

    init(configuration: ReadConfiguration) throws {
        // Phase 190: lazy loading — full file-system read happens when the
        // document is materialized into a live SwiftData context.
        let fileWrappers = configuration.file.fileWrappers ?? [:]
        guard fileWrappers["manifest.json"] != nil else {
            throw KicadAgentDocumentError.invalidBundle("Missing manifest.json")
        }

        // Decode manifest if present.
        if let manifestData = fileWrappers["manifest.json"]?.regularFileContents {
            let manifest = try JSONDecoder().decode(BundleManifest.self, from: manifestData)
            self.manifestVersion = manifest.version
            self.projectMetadata = manifest.project
        } else {
            self.manifestVersion = 1
            self.projectMetadata = ProjectMetadata(name: "Untitled")
        }
    }

    func fileWrapper(configuration: WriteConfiguration) throws -> FileWrapper {
        let directoryWrapper = FileWrapper(directoryWithFileWrappers: [:])

        // manifest.json
        let manifest = BundleManifest(
            version: manifestVersion,
            project: projectMetadata,
            createdAt: .now,
            kicadAgentVersion: Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "0.0.0"
        )
        let manifestData = try JSONEncoder().encode(manifest)
        directoryWrapper.addRegularFile(withContents: manifestData, preferredFilename: "manifest.json")

        return directoryWrapper
    }
}

/// Bundle manifest — top-level metadata for the .kicadagent directory.
struct BundleManifest: Codable, Sendable {
    let version: Int
    let project: ProjectMetadata
    let createdAt: Date
    let kicadAgentVersion: String
}

/// Project-level metadata stored in the bundle.
struct ProjectMetadata: Codable, Sendable {
    var name: String
    var description: String?

    init(name: String, description: String? = nil) {
        self.name = name
        self.description = description
    }
}

/// Errors specific to .kicadagent bundle handling.
enum KicadAgentDocumentError: LocalizedError {
    case invalidBundle(String)
    case unsupportedVersion(Int)

    var errorDescription: String? {
        switch self {
        case .invalidBundle(let reason): return "Invalid .kicadagent bundle: \(reason)"
        case .unsupportedVersion(let v): return "Unsupported bundle version: \(v)"
        }
    }
}
