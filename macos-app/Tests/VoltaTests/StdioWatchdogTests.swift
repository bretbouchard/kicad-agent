//
//  StdioWatchdogTests.swift
//  VoltaTests
//
//  Phase 167 — Stdio MCP Client
//
//  Tests for the RPC-aware stdio watchdog.
//
//  Coverage:
//    - Constants match PITFALL 2 spec (30s silence, 5s poll)
//    - trackRequestStart/End update pendingCount
//    - resetActivity updates lastActivityAt
//    - Audit entry emitted BEFORE kill (DAEM-02)
//    - Kill fires within 35s when daemon hangs (CI-friendly: use the
//      direct checkTimeouts() method instead of waiting 30s)
//    - No false positives when no requests pending
//

import Testing
import Foundation
@testable import Volta

@MainActor
@Suite("StdioWatchdog")
struct StdioWatchdogTests {

    // MARK: - Constants (PITFALL 2 — stdio buffering deadlock)

    @Test("Default silence timeout is 30 seconds (PITFALL 2)")
    func silenceTimeoutConstant() {
        #expect(StdioWatchdog.defaultSilenceTimeout == .seconds(30))
    }

    @Test("Default check interval is 5 seconds")
    func checkIntervalConstant() {
        #expect(StdioWatchdog.defaultCheckInterval == .seconds(5))
    }

    // MARK: - Request tracking

    @Test("trackRequestStart adds to pending")
    func trackStartAddsPending() {
        let wd = StdioWatchdog()
        #expect(wd.pendingCount == 0)
        wd.trackRequestStart(id: "abc", method: "ping")
        #expect(wd.pendingCount == 1)
        wd.trackRequestStart(id: "def", method: "list_operations")
        #expect(wd.pendingCount == 2)
    }

    @Test("trackRequestEnd removes from pending")
    func trackEndRemovesPending() {
        let wd = StdioWatchdog()
        wd.trackRequestStart(id: "abc", method: "ping")
        wd.trackRequestStart(id: "def", method: "list_operations")
        #expect(wd.pendingCount == 2)
        wd.trackRequestEnd(id: "abc")
        #expect(wd.pendingCount == 1)
        #expect(wd.pendingRequests["abc"] == nil)
        #expect(wd.pendingRequests["def"] != nil)
    }

    @Test("Pending requests carry metadata")
    func pendingMetadataPresent() {
        let wd = StdioWatchdog()
        wd.trackRequestStart(id: "abc", method: "ping", paramsByteSize: 42)
        let req = wd.pendingRequests["abc"]
        #expect(req?.method == "ping")
        #expect(req?.paramsByteSize == 42)
        #expect(req?.id == "abc")
    }

    // MARK: - Activity tracking

    @Test("resetActivity lowers silenceElapsed")
    func resetActivityUpdatesTimestamp() async throws {
        let wd = StdioWatchdog()
        let before = wd.silenceElapsed
        try await Task.sleep(for: .milliseconds(20))
        let after = wd.silenceElapsed
        #expect(after > before)
        wd.resetActivity()
        #expect(wd.silenceElapsed < after)
    }

    @Test("trackRequestStart resets activity")
    func trackStartResetsActivity() async throws {
        let wd = StdioWatchdog()
        try await Task.sleep(for: .milliseconds(30))
        let stale = wd.silenceElapsed
        wd.trackRequestStart(id: "x", method: "m")
        #expect(wd.silenceElapsed < stale)
    }

    // MARK: - Timeout detection (CI-friendly; no 30s wait)

    @Test("checkTimeouts is a no-op when no requests pending")
    func noTimeoutWhenEmpty() {
        let wd = StdioWatchdog()
        var fired = false
        wd.onTimeout = { _, _ in fired = true }
        wd.checkTimeouts()  // no requests → never fires
        #expect(fired == false)
    }

    @Test("checkTimeouts does not fire within deadline")
    func noTimeoutWithinDeadline() {
        let wd = StdioWatchdog()
        wd.trackRequestStart(id: "abc", method: "ping")
        var fired = false
        wd.onTimeout = { _, _ in fired = true }
        wd.checkTimeouts()  // just started → within 30s deadline
        #expect(fired == false)
    }

    @Test("checkTimeouts fires onTimeout when deadline exceeded")
    func timeoutFiresPastDeadline() async throws {
        let wd = StdioWatchdog()
        wd.silenceTimeout = .milliseconds(50)  // tighten for CI

        wd.trackRequestStart(id: "abc", method: "ping", paramsByteSize: 99)
        var firedId: String?
        var firedElapsedMs: Int?
        wd.onTimeout = { req, elapsed in
            firedId = req.id
            let ms = Int(elapsed.components.seconds) * 1000
                + Int(elapsed.components.attoseconds / 1_000_000_000_000_000)
            firedElapsedMs = ms
        }

        // Wait past the deadline.
        try await Task.sleep(for: .milliseconds(80))
        wd.checkTimeouts()

        #expect(firedId == "abc")
        #expect(firedElapsedMs ?? 0 >= 50)
    }

    // MARK: - DAEM-02 audit log before kill

    @Test("Audit entry is emitted BEFORE onTimeout fires (DAEM-02)")
    func auditEntryBeforeKill() async throws {
        let wd = StdioWatchdog()
        wd.silenceTimeout = .milliseconds(50)

        var eventOrder: [String] = []
        wd.auditSink = { event, fields in
            eventOrder.append("audit:\(event)")
            // Verify the audit entry has the expected fields.
            #expect(fields["request_id"] as? String == "abc")
            #expect(fields["method"] as? String == "ping")
            #expect(fields["event"] as? String == "stdio_watchdog_timeout")
        }
        wd.onTimeout = { _, _ in
            eventOrder.append("kill")
        }

        wd.trackRequestStart(id: "abc", method: "ping")
        try await Task.sleep(for: .milliseconds(80))
        wd.checkTimeouts()

        // Audit MUST come before kill (DAEM-02: audit survives crash).
        #expect(eventOrder.count == 2)
        #expect(eventOrder[0] == "audit:stdio_watchdog_timeout")
        #expect(eventOrder[1] == "kill")
    }

    @Test("Audit entry includes request metadata for post-incident forensics")
    func auditEntryMetadata() async throws {
        let wd = StdioWatchdog()
        wd.silenceTimeout = .milliseconds(30)

        var capturedFields: [String: Any]?
        wd.auditSink = { _, fields in capturedFields = fields }
        wd.onTimeout = { _, _ in }

        wd.trackRequestStart(id: "req-789", method: "list_operations", paramsByteSize: 256)
        try await Task.sleep(for: .milliseconds(50))
        wd.checkTimeouts()

        guard let fields = capturedFields else {
            Issue.record("audit sink not called")
            return
        }
        #expect(fields["event"] as? String == "stdio_watchdog_timeout")
        #expect(fields["request_id"] as? String == "req-789")
        #expect(fields["method"] as? String == "list_operations")
        #expect(fields["params_byte_size"] as? Int == 256)
        #expect(fields["pending_count"] as? Int == 1)
        // pid may surface as Int or NSNumber depending on JSON path; just
        // verify it's present and numeric.
        let pid = fields["pid"]
        #expect(pid is NSNumber || pid is Int)
        #expect((fields["elapsed_ms"] as? Int ?? 0) > 0)
    }

    // MARK: - Lifecycle

    @Test("start is idempotent")
    func startIdempotent() {
        let wd = StdioWatchdog()
        wd.start()
        let started = wd.pollerTask != nil
        wd.start()  // no-op — should not replace the existing task
        #expect(started)
        #expect(wd.pollerTask != nil)
        wd.stop()
    }

    @Test("stop clears pending requests and cancels poller")
    func stopClearsState() {
        let wd = StdioWatchdog()
        wd.start()
        wd.trackRequestStart(id: "a", method: "x")
        wd.trackRequestStart(id: "b", method: "y")
        #expect(wd.pendingCount == 2)

        wd.stop()

        #expect(wd.pendingCount == 0)
        #expect(wd.pollerTask == nil)
    }
}
