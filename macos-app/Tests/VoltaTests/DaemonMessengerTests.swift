//
//  DaemonMessengerTests.swift
//  VoltaTests
//
//  Phase 162 — Python Daemon Bundling
//
//  Tests for the JSON-RPC 2.0 stdio messenger. These tests exercise the
//  pure-routing layer (`ingest(line:)` ↔ `call`) without depending on
//  real subprocess pipes — those are covered by ProcessManagerTests.
//

import Testing
import Foundation
@testable import Volta

@MainActor
@Suite("DaemonMessenger")
struct DaemonMessengerTests {

    // MARK: - Routing

    @Test("Malformed JSON response is dropped, not crashed")
    func malformedJsonDropped() async throws {
        let messenger = DaemonMessenger()
        messenger.ingest(line: "not json at all")
        messenger.ingest(line: "")
        messenger.ingest(line: "{broken")
        // survival is the assertion
        #expect(Bool(true))
    }

    @Test("Heartbeat notification calls onHeartbeat")
    func heartbeatResetsWatchdog() async throws {
        let messenger = DaemonMessenger()
        let counter = HeartbeatCounter()
        messenger.onHeartbeat = { @MainActor in
            counter.count += 1
        }
        let heartbeat = #"{"jsonrpc":"2.0","method":"heartbeat","params":{}}"#
        messenger.ingest(line: heartbeat)
        messenger.ingest(line: heartbeat)
        try await Task.sleep(for: .milliseconds(50))
        #expect(counter.count == 2)
    }

    @Test("Id-less non-heartbeat messages are dropped")
    func idlessNonHeartbeatDropped() async throws {
        let messenger = DaemonMessenger()
        // A notification with no id and not "heartbeat" method.
        messenger.ingest(line: #"{"jsonrpc":"2.0","method":"unhandled"}"#)
        // survival is the assertion
        #expect(Bool(true))
    }

    @Test("Broken pipe surfaces when no stdin attached")
    func brokenPipeThrows() async throws {
        let messenger = DaemonMessenger()
        do {
            _ = try await messenger.call("ping", [:])
            Issue.record("call should have thrown brokenPipe")
        } catch DaemonMessengerError.brokenPipe {
            // expected
        } catch {
            Issue.record("unexpected error: \(error)")
        }
    }

    // MARK: - Heartbeat helper

    @Test("_testSimulateHeartbeat invokes callback")
    func simulateHeartbeatHelper() async throws {
        let messenger = DaemonMessenger()
        let counter = HeartbeatCounter()
        messenger.onHeartbeat = { @MainActor in
            counter.count += 1
        }
        messenger._testSimulateHeartbeat()
        #expect(counter.count == 1)
    }
}

// MARK: - Helpers

@MainActor
private final class HeartbeatCounter {
    var count: Int = 0
}
