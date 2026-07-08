//
//  KCMessage.swift
//  KiCadAgent
//
//  Phase 164 — LLM Provider Protocol
//
//  One chat turn. MOD-01 lock: this is the only message shape that crosses
//  the provider boundary. Provider classes translate KCMessage[] into their
//  SDK's native message array.
//
//  ponytail: role enum is exhaustive — providers can switch without a
//  default, getting compile-time safety when a new role is added.
//

import Foundation

/// A single chat message. Value-type + Sendable — safe to persist,
/// share across actors, and use in conversation state (Phase 168).
struct KCMessage: Sendable, Equatable, Identifiable {
    let id: UUID
    var role: KCRole
    var content: String
    var images: [KCAttachment]

    init(
        id: UUID = UUID(),
        role: KCRole,
        content: String,
        images: [KCAttachment] = []
    ) {
        self.id = id
        self.role = role
        self.content = content
        self.images = images
    }
}

/// Chat role. Exhaustive so provider adapters compile-check every case.
enum KCRole: String, Sendable, Equatable, Codable, CaseIterable {
    case system
    case user
    case assistant
    case tool
}
