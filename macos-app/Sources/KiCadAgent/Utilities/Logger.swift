//
//  Logger.swift
//  KiCadAgent
//
//  Phase 161 — App Shell Foundation
//
//  Structured logging wrapper using OSLog.
//
//  ponytail: thin convenience layer over `Logger.appShell` extension declared
//  in KiCadAgentApp.swift. Keep here so non-App files have a clear import path.
//  No custom log levels — defer to OSLog (default, info, debug, warn, error, fault).
//

import OSLog

/// Logging convenience. Real loggers are exposed as static properties on
/// `Logger` in `KiCadAgentApp.swift`:
///
/// ```swift
/// Logger.appShell.info("…")
/// Logger.models.error("…")
/// Logger.ui.debug("…")
/// ```
///
/// Subsystem: `com.kicadagent.app`
///
/// Categories:
/// - `appShell` — App/scene lifecycle, daemon supervisor
/// - `models` — SwiftData model creation/mutation
/// - `ui` — SwiftUI view lifecycle, accessibility events
///
/// To view in Console.app: filter subsystem=`com.kicadagent.app`.
enum AppLogging {
    /// One subsystem for the whole app shell. Daemon will use a sibling subsystem.
    static let subsystem = "com.kicadagent.app"
}
