//
//  KicadAgentDocument.swift
//  KiCadAgent
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
struct KicadAgentDocument: FileDocument {
    static var readableContentTypes: [UTType] { [.kicadAgentBundle] }
    static var writableContentTypes: [UTType] { [.kicadAgentBundle] }

    /// Manifest version — bump on format change.
    let manifestVersion: Int
    var projectMetadata: ProjectMetadata
    var conversations: [Conversation]
    var decisions: [Decision]
    var valueChanges: [ValueChange]
    var snapshots: [ProjectSnapshot]

    init() {
        self.manifestVersion = 1
        self.projectMetadata = ProjectMetadata(name: "Untitled")
        self.conversations = []
        self.decisions = []
        self.valueChanges = []
        self.snapshots = []
    }

    init(configuration: ReadConfiguration) throws {
        guard let directoryURL = configuration.file.fileURL else {
            throw KicadAgentDocumentError.invalidBundle("Missing bundle URL")
        }
        // Read manifest.json
        let manifestURL = directoryURL.appendingPathComponent("manifest.json")
        guard let manifestData = try? Data(contentsOf: manifestURL) else {
            throw KicadAgentDocumentError.invalidBundle("Missing manifest.json")
        }
        let manifest = try JSONDecoder().decode(BundleManifest.self, from: manifestData)
        self.manifestVersion = manifest.version
        self.projectMetadata = manifest.project
        self.conversations = [] // Loaded lazily on demand
        self.decisions = []
        self.valueChanges = []
        self.snapshots = []
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

        // conversations.jsonl
        let conversationsJSONL = conversations.map { _ in "{}" }.joined(separator: "\n")
        directoryWrapper.addRegularFile(
            withContents: (conversationsJSONL + "\n").data(using: .utf8)!,
            preferredFilename: "conversations.jsonl"
        )

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
