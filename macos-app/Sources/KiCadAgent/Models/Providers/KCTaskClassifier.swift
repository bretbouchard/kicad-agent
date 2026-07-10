//
//  KCTaskClassifier.swift
//  KiCadAgent
//
//  Phase 165 — Provider Router
//
//  Derives a `KCTask` from a `KCPrompt` using keyword heuristics. The router
//  consumes the result to pick a provider per MOD-02.
//
//  Why heuristics, not an LLM call: routing must be O(1) and free — calling
//  a model to decide which model to use would defeat the purpose. The
//  classifier is intentionally simple: it inspects keywords, attachments,
//  prompt length, and explicit `preferredModel` hints. False positives
//  route to a heavier provider (slightly more expensive), false negatives
//  route to a lighter one (slightly less capable) — both recoverable.
//
//  ponytail: ~80 LOC. Pure function over KCPrompt. No state, no I/O.
//

import Foundation

enum KCTaskClassifier {

    /// Classify a prompt into a `KCTask`.
    ///
    /// Order of precedence (first match wins):
    ///   1. Privacy marker in the system prompt or user content
    ///   2. Vision attachments OR explicit vision-model hint
    ///   3. Generation keywords (SKIDL, schematic, footprint, route)
    ///   4. Analysis keywords (ERC, DRC, BOM, explain)
    ///   5. Length-based complexity: long prompt → complexReasoning
    ///   6. Default → quickReply
    static func classify(_ prompt: KCPrompt) -> KCTask {
        let combined = combinedText(prompt)
        let lower = combined.lowercased()

        // 1. Privacy markers. Explicit > heuristic. Per MOD-02: ALWAYS local.
        if hasPrivacyMarker(lower) {
            return KCTask(
                taskType: .privacySensitive,
                requiresVision: !prompt.attachments.isEmpty,
                requiresPrivacy: true,
                complexity: complexityFor(length: combined.count)
            )
        }

        // 2. Vision. Attachments OR explicit vision-model hint.
        let wantsVision = !prompt.attachments.isEmpty
            || hasVisionHint(lower)
            || hasVisionHint(prompt.preferredModel?.lowercased() ?? "")
        if wantsVision {
            return KCTask(
                taskType: .vision,
                requiresVision: true,
                requiresPrivacy: false,
                complexity: complexityFor(length: combined.count)
            )
        }

        // 3. Generation keywords.
        if hasGenerationKeyword(lower) {
            return KCTask(
                taskType: .circuitGeneration,
                requiresVision: false,
                requiresPrivacy: false,
                complexity: max(0.7, complexityFor(length: combined.count))
            )
        }

        // 4. Routing-strategy keywords (vision-driven per Phase 98).
        if hasRoutingKeyword(lower) {
            return KCTask(
                taskType: .pcbRouting,
                requiresVision: false, // attachments would have tripped case 2
                requiresPrivacy: false,
                complexity: max(0.7, complexityFor(length: combined.count))
            )
        }

        // 4b. SPICE simulation keywords.
        if hasSPICEKeyword(lower) {
            return KCTask(
                taskType: .spiceSimulation,
                requiresVision: false,
                requiresPrivacy: false,
                complexity: max(0.7, complexityFor(length: combined.count))
            )
        }

        // 4c. Circuit theory keywords.
        if hasTheoryKeyword(lower) {
            return KCTask(
                taskType: .circuitTheory,
                requiresVision: false,
                requiresPrivacy: false,
                complexity: max(0.4, complexityFor(length: combined.count))
            )
        }

        // 5. Analysis keywords.
        if hasAnalysisKeyword(lower) {
            return KCTask(
                taskType: .boardAnalysis,
                requiresVision: false,
                requiresPrivacy: false,
                complexity: max(0.4, complexityFor(length: combined.count))
            )
        }

        // 6. Summarization keywords.
        if hasSummarizationKeyword(lower) {
            return KCTask(
                taskType: .conversationHistory,
                requiresVision: false,
                requiresPrivacy: false,
                complexity: max(0.3, complexityFor(length: combined.count))
            )
        }

        // 7. Long prompt → complex reasoning.
        let complexity = complexityFor(length: combined.count)
        if complexity >= 0.6 {
            return KCTask(
                taskType: .complexReasoning,
                requiresVision: false,
                requiresPrivacy: false,
                complexity: complexity
            )
        }

        // 8. Default.
        return KCTask(
            taskType: .quickReply,
            requiresVision: false,
            requiresPrivacy: false,
            complexity: complexity
        )
    }

    // MARK: - Text extraction

    private static func combinedText(_ prompt: KCPrompt) -> String {
        var parts: [String] = []
        if let sys = prompt.systemPrompt, !sys.isEmpty { parts.append(sys) }
        for message in prompt.messages { parts.append(message.content) }
        return parts.joined(separator: "\n")
    }

    // MARK: - Keyword banks

    private static func hasPrivacyMarker(_ text: String) -> Bool {
        let markers = [
            "privacy-sensitive",
            "privacy sensitive",
            "do not send to cloud",
            "confidential",
            "nda ",
            "proprietary",
            "[private]",
            "[confidential]"
        ]
        return markers.contains { text.contains($0) }
    }

    private static func hasVisionHint(_ text: String) -> Bool {
        let hints = [
            "vision",
            "look at this image",
            "see the screenshot",
            "analyze the render",
            "screenshot",
            "render",
            ".png",
            ".jpg",
            ".jpeg"
        ]
        return hints.contains { text.contains($0) }
    }

    private static func hasGenerationKeyword(_ text: String) -> Bool {
        let keywords = [
            "generate skidl",
            "emit skidl",
            "generate a schematic",
            "create a schematic",
            "generate circuit",
            "create circuit",
            "synthesize circuit",
            "design a circuit",
            "build a schematic",
            "emit netlist",
            "generate footprint",
            "create footprint"
        ]
        return keywords.contains { text.contains($0) }
    }

    private static func hasRoutingKeyword(_ text: String) -> Bool {
        let keywords = [
            "route this board",
            "routing strategy",
            "trace routing",
            "auto-route",
            "auto route",
            "autoroute",
            "freerouting",
            "route the pcb"
        ]
        return keywords.contains { text.contains($0) }
    }

    private static func hasSPICEKeyword(_ text: String) -> Bool {
        let keywords = [
            "simulate", "simulation", "spice", "ngspice",
            "ac analysis", "dc sweep", "transient analysis",
            "noise analysis", "monte carlo", "worst case",
            "verify the gain", "verify gain", "measure the",
            "frequency response", "bode plot",
            "check the -3db", "cutoff frequency",
            "run analysis", "plot response", "frequency sweep"
        ]
        return keywords.contains { text.contains($0) }
    }

    private static func hasTheoryKeyword(_ text: String) -> Bool {
        let questionWords = ["why", "how do", "how does", "what is", "what are",
                             "explain", "difference between", "when should"]
        let circuitWords = ["capacitor", "resistor", "inductor", "diode", "mosfet",
                            "opamp", "op amp", "ground", "impedance", "decoupling",
                            "pull-up", "pull-up", "pull-down", "trace", "via",
                            "plane", "emi", "emc", "thermal", "noise", "bandwidth",
                            "slew rate", "gain", "feedback", "stability",
                            "esr", "esl", "srf", "gbw", "thd", "snr",
                            "ohm", "kirchhoff", "impedance matching",
                            "signal integrity", "power integrity", "ground loop",
                            "crosstalk", "reflection", "termination",
                            "heatsink", "junction temp", "derating", "power dissipation",
                            "buck", "boost", "ldo", "switching regulator",
                            "zener", "schottky", "tvz", "esd", "flyback diode"]
        return questionWords.contains { qw in text.contains(qw) }
            && circuitWords.contains { cw in text.contains(cw) }
    }

    private static func hasAnalysisKeyword(_ text: String) -> Bool {
        let keywords = [
            "erc ",
            "drc ",
            "explain the error",
            "explain the violation",
            "summarize the bom",
            "bill of materials",
            "what does this mean",
            "analyze the board"
        ]
        return keywords.contains { text.contains($0) }
    }

    private static func hasSummarizationKeyword(_ text: String) -> Bool {
        let keywords = [
            "summarize this conversation",
            "summarise this conversation",
            "tldr",
            "tl;dr",
            "recap the discussion",
            "summarize our discussion"
        ]
        return keywords.contains { text.contains($0) }
    }

    /// ponytail: linear ramp. ≤200 chars → 0.2, ≥4000 chars → 1.0.
    /// These thresholds are conservative — they catch the long-context
    /// cases without misrouting a normal "what's an LED?" question.
    private static func complexityFor(length: Int) -> Double {
        if length <= 200 { return 0.2 }
        if length >= 4000 { return 1.0 }
        let span = Double(length - 200) / Double(4000 - 200)
        return 0.2 + span * 0.8
    }
}
