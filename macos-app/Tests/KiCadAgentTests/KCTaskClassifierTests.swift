//
//  KCTaskClassifierTests.swift
//  KiCadAgentTests
//
//  Phase 165 — Provider Router
//
//  Tests for KCTaskClassifier heuristics + KCTask value type.
//

import Testing
import Foundation
@testable import KiCadAgent

@Suite("KCTaskClassifier")
struct KCTaskClassifierTests {

    // MARK: - Privacy

    @Test("Privacy marker triggers privacySensitive routing")
    func privacyMarkerDetected() {
        let prompt = KCPrompt.user("Design a circuit. [confidential]")
        let task = KCTaskClassifier.classify(prompt)
        #expect(task.taskType == .privacySensitive)
        #expect(task.requiresPrivacy)
    }

    @Test("NDA marker triggers privacySensitive routing")
    func ndaMarkerDetected() {
        let prompt = KCPrompt.user("Under NDA — what's the best layout?")
        let task = KCTaskClassifier.classify(prompt)
        #expect(task.taskType == .privacySensitive)
    }

    @Test("Proprietary marker triggers privacySensitive routing")
    func proprietaryMarkerDetected() {
        let prompt = KCPrompt.user("This is proprietary — please analyze")
        let task = KCTaskClassifier.classify(prompt)
        #expect(task.taskType == .privacySensitive)
    }

    // MARK: - Vision

    @Test("Image attachment triggers vision routing")
    func attachmentTriggersVision() {
        let attachment = KCAttachment.png(Data([0x89, 0x50, 0x4E, 0x47]))
        let prompt = KCPrompt(
            messages: [KCMessage(role: .user, content: "what's in this schematic")],
            attachments: [attachment]
        )
        let task = KCTaskClassifier.classify(prompt)
        #expect(task.taskType == .vision)
        #expect(task.requiresVision)
    }

    @Test("'screenshot' keyword triggers vision routing")
    func screenshotKeywordTriggersVision() {
        let prompt = KCPrompt.user("Look at this screenshot of the PCB")
        let task = KCTaskClassifier.classify(prompt)
        #expect(task.taskType == .vision)
    }

    @Test("Explicit preferredModel vision hint triggers vision routing")
    func visionPreferredModelTriggersVision() {
        let prompt = KCPrompt.user("analyze this board", preferredModel: "gpt-4o-vision")
        let task = KCTaskClassifier.classify(prompt)
        #expect(task.taskType == .vision)
    }

    // MARK: - Generation

    @Test("SKIDL generation keyword triggers circuitGeneration")
    func skidlKeywordTriggersGeneration() {
        let prompt = KCPrompt.user("Please generate SKIDL for an RC filter")
        let task = KCTaskClassifier.classify(prompt)
        #expect(task.taskType == .circuitGeneration)
        #expect(task.complexity >= 0.7)
    }

    @Test("'create a schematic' triggers circuitGeneration")
    func createSchematicKeywordTriggersGeneration() {
        let prompt = KCPrompt.user("Create a schematic for a distortion pedal")
        let task = KCTaskClassifier.classify(prompt)
        #expect(task.taskType == .circuitGeneration)
    }

    // MARK: - Routing

    @Test("Routing-strategy keyword triggers pcbRouting")
    func routingKeywordTriggersPcbRouting() {
        let prompt = KCPrompt.user("Plan a routing strategy for this 4-layer board")
        let task = KCTaskClassifier.classify(prompt)
        #expect(task.taskType == .pcbRouting)
    }

    @Test("Auto-route keyword triggers pcbRouting")
    func autoRouteKeywordTriggersPcbRouting() {
        let prompt = KCPrompt.user("Please auto-route this board")
        let task = KCTaskClassifier.classify(prompt)
        #expect(task.taskType == .pcbRouting)
    }

    // MARK: - Analysis

    @Test("ERC keyword triggers boardAnalysis")
    func ercKeywordTriggersAnalysis() {
        let prompt = KCPrompt.user("What does this ERC violation mean?")
        let task = KCTaskClassifier.classify(prompt)
        #expect(task.taskType == .boardAnalysis)
    }

    @Test("DRC keyword triggers boardAnalysis")
    func drcKeywordTriggersAnalysis() {
        let prompt = KCPrompt.user("Explain this DRC error to me")
        let task = KCTaskClassifier.classify(prompt)
        #expect(task.taskType == .boardAnalysis)
    }

    @Test("BOM keyword triggers boardAnalysis")
    func bomKeywordTriggersAnalysis() {
        let prompt = KCPrompt.user("Summarize the BOM for this project")
        let task = KCTaskClassifier.classify(prompt)
        #expect(task.taskType == .boardAnalysis)
    }

    // MARK: - Summarization

    @Test("TLDR triggers conversationHistory")
    func tldrTriggersSummarization() {
        let prompt = KCPrompt.user("TLDR of the discussion above")
        let task = KCTaskClassifier.classify(prompt)
        #expect(task.taskType == .conversationHistory)
    }

    // MARK: - Complexity ramp

    @Test("Long prompt escalates to complexReasoning")
    func longPromptEscalates() {
        let long = String(repeating: "I need to design a complex multi-stage amplifier with detailed tradeoffs. ", count: 80)
        let prompt = KCPrompt.user(long)
        let task = KCTaskClassifier.classify(prompt)
        #expect(task.taskType == .complexReasoning)
        #expect(task.complexity >= 0.6)
    }

    @Test("Short prompt stays at quickReply")
    func shortPromptStaysQuickReply() {
        let prompt = KCPrompt.user("What's an LED?")
        let task = KCTaskClassifier.classify(prompt)
        #expect(task.taskType == .quickReply)
        #expect(task.complexity <= 0.3)
    }

    // MARK: - Default

    @Test("Default for unrecognized short prompts is quickReply")
    func defaultQuickReply() {
        let prompt = KCPrompt.user("hi there")
        let task = KCTaskClassifier.classify(prompt)
        #expect(task.taskType == .quickReply)
        #expect(!task.requiresVision)
        #expect(!task.requiresPrivacy)
    }

    // MARK: - Privacy precedence over vision

    @Test("Privacy marker wins over vision attachment")
    func privacyWinsOverVision() {
        let attachment = KCAttachment.png(Data([0x89, 0x50, 0x4E, 0x47]))
        let prompt = KCPrompt(
            messages: [KCMessage(role: .user, content: "[confidential] analyze this")],
            attachments: [attachment]
        )
        let task = KCTaskClassifier.classify(prompt)
        // Privacy wins; vision is recorded as a sub-flag.
        #expect(task.taskType == .privacySensitive)
        #expect(task.requiresPrivacy)
        #expect(task.requiresVision)
    }
}

@Suite("KCTask value type")
struct KCTaskTypeTests {

    @Test("KCTaskType.preferenceCategory maps pipeline stages onto the four user-visible categories")
    func preferenceCategoryMapping() {
        #expect(KCTaskType.quickReply.preferenceCategory == .quickReply)
        #expect(KCTaskType.complexReasoning.preferenceCategory == .complexReasoning)
        #expect(KCTaskType.vision.preferenceCategory == .vision)
        #expect(KCTaskType.privacySensitive.preferenceCategory == .privacySensitive)

        // Internal pipeline stages collapse onto user-visible categories.
        #expect(KCTaskType.circuitGeneration.preferenceCategory == .complexReasoning)
        #expect(KCTaskType.pcbRouting.preferenceCategory == .vision)
        #expect(KCTaskType.boardAnalysis.preferenceCategory == .complexReasoning)
        #expect(KCTaskType.conversationHistory.preferenceCategory == .complexReasoning)
    }

    @Test("KCTask complexity accepts valid range (0.0–1.0)")
    func complexityValidRange() {
        // Valid ranges only. Precondition failures abort the process and
        // can't be caught via `throws:` — we verify only the happy path here
        // and trust the precondition to fire on out-of-range values.
        _ = KCTask(taskType: .quickReply, complexity: 0.0)
        _ = KCTask(taskType: .quickReply, complexity: 0.5)
        _ = KCTask(taskType: .quickReply, complexity: 1.0)
    }

    @Test("KCTaskType.displayName is non-empty for every case")
    func displayNameNonEmpty() {
        for kind in KCTaskType.allCases {
            #expect(!kind.displayName.isEmpty)
            #expect(!kind.roleDescription.isEmpty)
        }
    }
}
