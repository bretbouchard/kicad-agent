//
//  KiCadAgentApp.swift
//  KiCadAgent
//
//  Phase 161 — App Shell Foundation
//
//  macOS 27+ Liquid Glass chat shell. Entry point for the v6.0 KiCad Agent app.
//  ponytail: SwiftUI App lifecycle (no AppDelegate legacy). Multi-window via WindowGroup.
//
//  Phase 220: KiCad CLI is no longer a hard requirement. The app runs on the
//  local MLX engine; KiCad CLI is only invoked for optional ERC/DRC when present.
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
#if os(macOS)
    @State private var daemonSupervisor: DaemonSupervisor = DaemonSupervisor()
#endif

    /// Multi-window registry. Phase 171 — tracks open project windows + cap.
    @State private var windowManager: WindowManager = WindowManager()

    /// Phase 210 — Provider registry for LLM routing (local + cloud).
    @StateObject private var providerRegistry = ProviderRegistry()

    /// Phase 211 — Model router for LLM generation. Built from registry.
    @StateObject private var modelRouter = KiCadModelRouter()

    /// Phase 210 — Local model manager (downloads, scans, registers).
    @State private var localModelManager: LocalModelManager?

    var body: some Scene {
        WindowGroup {
            AppRootView()
                #if os(macOS)
                .environment(daemonSupervisor)
                #endif
                .environment(windowManager)
                .environmentObject(providerRegistry)
                .environmentObject(modelRouter)
                .sheet(isPresented: Binding(
                    get: { localModelManager?.showDownloadSheet ?? false },
                    set: { _ in }
                )) {
                    if let manager = localModelManager {
                        ModelDownloadView(
                            localModelManager: manager
                        ) {
                            manager.onDownloadComplete()
                        }
                    }
                }
                .frame(minWidth: 900, minHeight: 600)
                .onAppear {
                    // APP-01 augmentation: spawn daemon on launch; if it fails within
                    // 5 seconds, AppRootView surfaces recovery UI (no silent hang).
                    KiCadAgentApp.logger.info("Volta PCB launching — macOS 27 Liquid Glass shell")
                    #if os(macOS)
                    // Grab focus from the launching terminal. Without this, the SPM
                    // binary inherits the terminal's tty and TextField keystrokes
                    // land in the terminal instead of the app window.
                    NSApp.setActivationPolicy(.regular)
                    NSApp.activate(ignoringOtherApps: true)
                    daemonSupervisor.start()
                    #endif
                    // Phase 210: scan for local model, show download prompt if missing.
                    localModelManager = LocalModelManager(registry: providerRegistry)
                }
                .onDisappear {
                    // APP-05 augmentation placeholder: 5s shutdown timeout + force-kill
                    // lands in Phase 162 when real daemon process exists.
                    #if os(macOS)
                    daemonSupervisor.shutdown()
                    #endif
                }
        }
        .windowResizability(.contentMinSize)
        .windowToolbarStyle(.unified(showsTitle: true))
        .commands {
            // ponytail: cmd+N handled natively by WindowGroup. Add app-level commands here.
        }
        .modelContainer(for: ModelSchemaRegistry.v600Schema)
    }
}

/// Phase 176 / 177 — central schema registry.
///
/// Keeps the `ModelContainer(for:)` argument stable across app lifecycle so
/// CloudKit sync schema additions are explicit (Pitfall 4 prevention).
enum ModelSchemaRegistry {
    /// v6.0.0 frozen schema. Adding a model here REQUIRES a VersionedSchema
    /// bump per Phase 177 CloudKit constraints (no auto-migration).
    static let v600Schema: [any PersistentModel.Type] = [
        Project.self,
        Conversation.self,
        Message.self,
        Decision.self,
        ValueChange.self,
        ProjectSnapshot.self,
        OnboardingState.self,
    ]

    /// Schema version tag for CloudKit Optionals — bump on every schema change.
    static let versionTag = "v6.0.0"

    /// Construct a ModelContainer for the v6.0.0 schema with the given config.
    /// Helper to avoid variadic-spreading the array at every call site.
    static func makeContainer(configuration: ModelConfiguration) throws -> ModelContainer {
        try ModelContainer(
            for: Project.self, Conversation.self, Message.self, Decision.self,
                 ValueChange.self, ProjectSnapshot.self, OnboardingState.self,
            configurations: configuration
        )
    }
}

/// Convenience Logger extension — keeps subsystem consistent across files.
extension Logger {
    /// Subsystem for the Swift app shell. Daemon uses a separate subsystem.
    static let appShell = Logger(subsystem: "com.kicadagent.app", category: "appShell")
    static let models = Logger(subsystem: "com.kicadagent.app", category: "models")
    static let ui = Logger(subsystem: "com.kicadagent.app", category: "ui")
    static let kicad = Logger(subsystem: "com.kicadagent.app", category: "kicad")
    static let stream = Logger(subsystem: "com.kicadagent.app", category: "stream")
}
