//
//  WindowManager.swift
//  Volta
//
//  Phase 171 — Liquid Glass UI Shell
//
//  Tracks open project windows across the WindowGroup scene. SwiftUI's
//  WindowGroup handles window creation natively (cmd+N); this manager
//  provides the missing piece — a queryable registry of what's open,
//  the active window, and a cap to prevent window-spam (T-171-04).
//
//  Design:
//  - One instance per app process (ObservableObject + @MainActor)
//  - Tracks openProjectIds: Set<UUID> for O(1) lookup
//  - Tracks activeProjectId for menu bar / cmd+W behavior
//  - Cap at 100 windows per threat model T-171-04 mitigation
//  - No NSWindow references — pure state, SwiftUI-native
//
//  ponytail: no NSWindow, no AppKit. Pure @Observable state.
//

import SwiftUI
import OSLog

/// Multi-window state for the KiCad Agent app.
///
/// Phase 171 — Liquid Glass UI Shell (T-171-04 mitigation).
@MainActor
@Observable
final class WindowManager {
    /// Maximum concurrent windows. Prevents accidental window spam.
    static let maxOpenWindows = 100

    /// Project IDs currently open in some window. Insertion-ordered.
    private(set) var openProjectIds: [UUID] = []

    /// The project ID whose window is currently key.
    /// Drives the Window menu and cmd+W dispatch.
    private(set) var activeProjectId: UUID?

    /// True when the next `openWindow` should be allowed.
    /// Returns false when `openProjectIds.count >= maxOpenWindows`.
    var isAtCap: Bool { openProjectIds.count >= Self.maxOpenWindows }

    /// Register a project as having an open window. Idempotent.
    /// Returns true if registered (or already was), false if at cap.
    @discardableResult
    func register(projectId: UUID) -> Bool {
        if openProjectIds.contains(projectId) {
            activeProjectId = projectId
            return true
        }
        guard !isAtCap else {
            Logger.ui.error("WindowManager at cap (\(Self.maxOpenWindows)) — refused projectId=\(projectId.uuidString.prefix(8))")
            return false
        }
        openProjectIds.append(projectId)
        activeProjectId = projectId
        Logger.ui.info("Window opened for projectId=\(projectId.uuidString.prefix(8)) (total=\(self.openProjectIds.count))")
        return true
    }

    /// Unregister a project's window. No-op if not registered.
    func unregister(projectId: UUID) {
        openProjectIds.removeAll { $0 == projectId }
        if activeProjectId == projectId {
            activeProjectId = openProjectIds.last
        }
        Logger.ui.info("Window closed for projectId=\(projectId.uuidString.prefix(8)) (total=\(self.openProjectIds.count))")
    }

    /// Mark a project as the active window (key window gained focus).
    func setActive(projectId: UUID) {
        guard openProjectIds.contains(projectId) else {
            Logger.ui.warning("setActive called for unregistered projectId=\(projectId.uuidString.prefix(8))")
            return
        }
        activeProjectId = projectId
    }

    /// True if the project has any open window.
    func isOpen(_ projectId: UUID) -> Bool {
        openProjectIds.contains(projectId)
    }
}
