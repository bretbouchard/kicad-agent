//
//  SwiftDataTestHelpers.swift
//  VoltaTests
//
//  Shared test utilities for SwiftData ModelContainer lifecycle management.
//

import SwiftData
import Foundation
@testable import Volta

enum SwiftDataTestHelpers {
    /// Tear down an in-memory ModelContainer by deleting all entities.
    /// Prevents cross-test contamination when multiple tests create
    /// local containers.
    @MainActor
    static func drainContainer(_ container: ModelContainer) {
        let context = container.mainContext
        // Delete in dependency order: children first, parents last.
        // SwiftData/CoreData enforces mandatory inverse relationships,
        // so deleting a parent before its children causes constraint violations.
        try? context.delete(model: Message.self)
        try? context.delete(model: Decision.self)
        try? context.delete(model: ValueChange.self)
        try? context.delete(model: ProjectSnapshot.self)
        try? context.delete(model: Conversation.self)
        try? context.delete(model: Project.self)
        try? context.save()
    }
}
