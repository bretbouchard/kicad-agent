//
//  OnboardingState.swift
//  KiCadAgent
//
//  Phase 242 — First-run Onboarding
//
//  SwiftData @Model that remembers whether the user has seen (and
//  dismissed / completed) the 3-step onboarding tour. The model
//  container holds a single row — we use a deterministic id and
//  fetch-or-create semantics in `OnboardingStateStore` so multiple
//  app launches don't accumulate duplicate state rows.
//
//  Why a separate "State" directory: this isn't a domain entity
//  (like Project or Conversation). It's app-level chrome. Keeping
//  it in /State mirrors Track F's "app shell state" boundary.
//

import Foundation
import SwiftData
import OSLog

/// Onboarding tour progress for a single install of the app.
@Model
final class OnboardingState {
    /// Stable id — always the same value so the row is unique.
    /// We use a hard-coded UUID for the single canonical state row.
    @Attribute(.unique) var id: UUID

    /// User dismissed the tour without completing it (skip button).
    /// Stops the tour from re-appearing.
    var dismissed: Bool

    /// User finished the 3 steps.
    /// Like `dismissed` but signals we should not nag them.
    var completed: Bool

    /// 0-based index of the last step shown. Persists across
    /// app launches so a crash mid-tour doesn't restart from step 0.
    var currentStep: Int

    /// When the tour was last surfaced. Used by the "Show me around
    /// again" button to re-show after a long absence.
    var lastShownAt: Date?

    init(
        id: UUID = OnboardingState.canonicalId,
        dismissed: Bool = false,
        completed: Bool = false,
        currentStep: Int = 0,
        lastShownAt: Date? = nil
    ) {
        self.id = id
        self.dismissed = dismissed
        self.completed = completed
        self.currentStep = currentStep
        self.lastShownAt = lastShownAt
    }

    /// Hard-coded UUID so the row is unique across launches. We
    /// deliberately don't use `UUID()` here — the same install
    /// should always have the same OnboardingState id.
    static let canonicalId = UUID(uuidString: "00000000-0000-0000-0000-00000000F100")!
}

/// Store façade. Centralizes fetch-or-create so the rest of the
/// app doesn't have to know about SwiftData plumbing.
@MainActor
enum OnboardingStateStore {
    /// The canonical onboarding row. Creates one on first access.
    /// Caller is expected to have a ModelContext in scope.
    @discardableResult
    static func current(in context: ModelContext) -> OnboardingState {
        let id = OnboardingState.canonicalId
        let descriptor = FetchDescriptor<OnboardingState>(
            predicate: #Predicate<OnboardingState> { $0.id == id }
        )
        if let existing = try? context.fetch(descriptor).first {
            return existing
        }
        let new = OnboardingState()
        context.insert(new)
        Logger.ui.info("OnboardingState created (first launch)")
        return new
    }
}
