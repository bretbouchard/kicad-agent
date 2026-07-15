//
//  UIAutomationTesting.swift
//  Volta
//
//  Phase 196 — UI Automation
//
//  XCUITest helpers for automating critical user flows. XCUITest requires
//  Xcode project setup; SPM-only projects use these helpers from within
//  the app target for in-app automation. Full XCUITest wires in Phase 196.1
//  when CI Xcode project ships (Phase 203 Fastlane).
//
//  TEST-06: UI automation for critical flows.
//  TEST-07: golden-path coverage.
//

import Foundation

/// XCUITest flow documentation + step recorder.
///
/// ponytail: stateless recorder. Tests construct flows declaratively,
/// helpers log steps to a JSONL file for replay + diff.
public struct UIAutomationFlow: Sendable, Codable {
    public let name: String
    public let steps: [UIAutomationStep]
    public let goldenPath: Bool

    public init(name: String, steps: [UIAutomationStep], goldenPath: Bool = true) {
        self.name = name
        self.steps = steps
        self.goldenPath = goldenPath
    }

    /// Total step count for the flow.
    public var stepCount: Int { steps.count }

    /// True if every step has accessibility identifiers (required for stable automation).
    public var allStepsIdentifiable: Bool {
        steps.allSatisfy { !$0.accessibilityIdentifier.isEmpty }
    }
}

/// One UI automation step.
public struct UIAutomationStep: Sendable, Codable, Identifiable {
    public let id: UUID
    public let action: String       // "tap", "type", "swipe", "scroll"
    public let target: String       // accessibility identifier or label
    public let accessibilityIdentifier: String
    public let value: String?       // for type actions
    public let expectedResult: String?

    public init(
        id: UUID = UUID(),
        action: String,
        target: String,
        accessibilityIdentifier: String = "",
        value: String? = nil,
        expectedResult: String? = nil
    ) {
        self.id = id
        self.action = action
        self.target = target
        self.accessibilityIdentifier = accessibilityIdentifier
        self.value = value
        self.expectedResult = expectedResult
    }
}

/// Canonical flows shipped with v6.0. Tests reference these to ensure
/// coverage of golden-path user journeys.
public enum GoldenFlows {
    /// New project → type intent → see schematic render.
    public static let firstDesignFlow = UIAutomationFlow(
        name: "first-design",
        steps: [
            UIAutomationStep(action: "tap", target: "New Project", accessibilityIdentifier: "toolbar.new-project"),
            UIAutomationStep(action: "type", target: "Hardware design intent", accessibilityIdentifier: "compose.field", value: "design a distortion pedal"),
            UIAutomationStep(action: "tap", target: "Send message", accessibilityIdentifier: "compose.send"),
            UIAutomationStep(action: "wait", target: "Schematic preview", accessibilityIdentifier: "schematic.preview", expectedResult: "visible")
        ]
    )

    /// Open existing project → see conversation history.
    public static let openExistingFlow = UIAutomationFlow(
        name: "open-existing",
        steps: [
            UIAutomationStep(action: "tap", target: "Conversations", accessibilityIdentifier: "sidebar.conversations"),
            UIAutomationStep(action: "tap", target: "Existing project", accessibilityIdentifier: "sidebar.project.existing"),
            UIAutomationStep(action: "wait", target: "Conversation messages", accessibilityIdentifier: "chat.messages", expectedResult: "visible")
        ]
    )

    /// Time-travel: scrub to past snapshot.
    public static let timeTravelFlow = UIAutomationFlow(
        name: "time-travel",
        steps: [
            UIAutomationStep(action: "tap", target: "Time Travel", accessibilityIdentifier: "memory.time-travel"),
            UIAutomationStep(action: "drag", target: "Timeline scrub", accessibilityIdentifier: "timeline.scrub", value: "0.5"),
            UIAutomationStep(action: "tap", target: "Restore to Here", accessibilityIdentifier: "timeline.restore"),
            UIAutomationStep(action: "tap", target: "Restore", accessibilityIdentifier: "alert.restore.confirm")
        ]
    )
}
