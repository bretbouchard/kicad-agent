//
//  PreviewFileWatcher.swift
//  Phase 238 — Debounced file system watcher
//
//  Watches a file using DispatchSource and emits a single debounced
//  callback after writes settle. Used by the Schematic / PCB preview
//  views to auto-refresh when the underlying .kicad_sch or .kicad_pcb
//  changes (e.g. user edits in another app).
//
//  ponytail: DispatchSource.makeFileSystemObjectSource — no external
//  dependency (no FSEvents wrapper, no kqueue, no third-party).
//  Cancellation via deinit-cleanup pattern.
//

import Foundation
import OSLog

/// Watches a single file for changes, emitting a debounced callback.
final class PreviewFileWatcher {
    private let url: URL
    private let onChange: @Sendable () -> Void
    private let debounce: TimeInterval
    private let queue = DispatchQueue(label: "PreviewFileWatcher", qos: .utility)
    private var source: DispatchSourceFileSystemObject?
    private var debounceWorkItem: DispatchWorkItem?
    private var fileDescriptor: Int32 = -1
    private let log = Logger(subsystem: "KiCadAgent", category: "PreviewFileWatcher")

    init(
        url: URL,
        debounce: TimeInterval = 0.25,
        onChange: @escaping @Sendable () -> Void
    ) {
        self.url = url
        self.debounce = debounce
        self.onChange = onChange
    }

    deinit {
        stop()
    }

    /// Start watching. Idempotent — calling on an already-running watcher
    /// is a no-op.
    func start() {
        guard source == nil else { return }
        let path = url.path
        fileDescriptor = open(path, O_EVTONLY)
        guard fileDescriptor >= 0 else {
            log.error("Could not open \(path, privacy: .public) for watching")
            return
        }
        let src = DispatchSource.makeFileSystemObjectSource(
            fileDescriptor: fileDescriptor,
            eventMask: [.write, .extend, .delete, .rename],
            queue: queue
        )
        src.setEventHandler { [weak self] in
            self?.handleEvent()
        }
        src.setCancelHandler { [weak self] in
            guard let self = self else { return }
            if self.fileDescriptor >= 0 {
                close(self.fileDescriptor)
                self.fileDescriptor = -1
            }
        }
        src.resume()
        source = src
        log.debug("Watching \(path, privacy: .public)")
    }

    /// Stop watching. Idempotent.
    func stop() {
        debounceWorkItem?.cancel()
        debounceWorkItem = nil
        source?.cancel()
        source = nil
    }

    private func handleEvent() {
        // Cancel any pending debounce — start the timer over.
        debounceWorkItem?.cancel()
        let work = DispatchWorkItem { [weak self] in
            guard let self = self else { return }
            self.log.debug("Change detected for \(self.url.lastPathComponent, privacy: .public)")
            self.onChange()
        }
        debounceWorkItem = work
        queue.asyncAfter(deadline: .now() + debounce, execute: work)
    }
}
