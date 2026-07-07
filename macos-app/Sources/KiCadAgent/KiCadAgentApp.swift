//
//  KiCadAgentApp.swift
//  KiCadAgent
//
//  Phase 161 — App Shell Foundation
//
//  macOS 27+ Liquid Glass chat shell. Entry point for the v6.0 KiCad Agent app.
//  ponytail: SwiftUI App lifecycle (no AppDelegate legacy). Multi-window via WindowGroup.
//

import SwiftUI
import SwiftData
import OSLog

/// Entry point for the KiCad Agent macOS app.
///
/// Architecture:
/// - SwiftUI App protocol (no AppDelegate legacy)
/// - WindowGroup scene (multi-window via cmd+N, automatic state restoration)
/// - In-memory SwiftData container (Track E adds CloudKit sync)
/// - Daemon recovery UI surfaced via `AppRootView`
@main
struct KiCadAgentApp: App {
    /// Structured logger for the app shell. Bundled daemon gets its own logger.
    private static let logger = Logger.appShell

    /// Daemon supervisor. Tracks daemon lifecycle (spawn, health, shutdown).
    /// ponytail: Phase 162 wires real daemon spawn. For now, returns `.notStarted`.
    @State private var daemonSupervisor: DaemonSupervisor = DaemonSupervisor()

    var body: some Scene {
        WindowGroup {
            AppRootView()
                .environment(daemonSupervisor)
                .frame(minWidth: 900, minHeight: 600)
                .onAppear {
                    // APP-01 augmentation: spawn daemon on launch; if it fails within
                    // 5 seconds, AppRootView surfaces recovery UI (no silent hang).
                    KiCadAgentApp.logger.info("KiCadAgent launching — macOS 27 Liquid Glass shell")
                    daemonSupervisor.start()
                }
                .onDisappear {
                    // APP-05 augmentation placeholder: 5s shutdown timeout + force-kill
                    // lands in Phase 162 when real daemon process exists.
                    daemonSupervisor.shutdown()
                }
        }
        .windowResizability(.contentMinSize)
        .windowToolbarStyle(.unified(showsTitle: true))
        .commands {
            // ponytail: cmd+N handled natively by WindowGroup. Add app-level commands here.
            CommandGroup(after: .newItem) {
                // Reserved for Phase 163 onboarding: "Open KiCad Project…"
            }
        }
        .modelContainer(for: [Project.self, Conversation.self])
    }
}

/// Convenience Logger extension — keeps subsystem consistent across files.
extension Logger {
    /// Subsystem for the Swift app shell. Daemon uses a separate subsystem.
    static let appShell = Logger(subsystem: "com.kicadagent.app", category: "appShell")
    static let models = Logger(subsystem: "com.kicadagent.app", category: "models")
    static let ui = Logger(subsystem: "com.kicadagent.app", category: "ui")
}
