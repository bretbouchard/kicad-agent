//
//  KCTaskPromptFormatter.swift
//  KiCadAgent
//
//  Phase D — Multi-Task Prompt Formatter
//
//  Bridges the Python task_router into the Swift app. Given a classified
//  KCTask, prepares the KCPrompt with:
//    1. Task-specific system prompt (SKIDL rules, theory expert, SPICE expert)
//    2. Task prefix on the user message ([CODEGEN], [THEORY], [SPICE])
//    3. Appropriate max_tokens per task type
//
//  This formatter runs AFTER KCTaskClassifier classifies the intent and
//  BEFORE the provider processes the prompt. It is a pure function —
//  no state, no I/O, no side effects.
//

import Foundation

enum KCTaskPromptFormatter {

    /// Format a prompt for the model based on the classified task type.
    /// Returns a new KCPrompt with system prompt, prefix, and max tokens set.
    ///
    /// - Parameters:
    ///   - prompt: The original user prompt
    ///   - task: The classified task (from KCTaskClassifier)
    /// - Returns: A formatted prompt ready for the provider
    static func format(_ prompt: KCPrompt, for task: KCTask) -> KCPrompt {
        var formatted = prompt

        // 1. Set task-specific system prompt (only if user didn't provide one)
        if formatted.systemPrompt == nil || formatted.systemPrompt?.isEmpty == true {
            formatted.systemPrompt = systemPrompt(for: task.taskType)
        }

        // 2. Add task prefix to the last user message
        if let prefix = taskPrefix(for: task.taskType) {
            formatted.messages = formatted.messages.map { msg in
                if msg.role == .user {
                    return KCMessage(role: .user, content: "[\(prefix)] \(msg.content)")
                }
                return msg
            }
        }

        // 3. Set max tokens if not already specified
        if formatted.maxTokens == nil {
            formatted.maxTokens = maxTokens(for: task.taskType)
        }

        return formatted
    }

    // MARK: - Task-Specific Configuration

    /// The prompt prefix for a task type. nil = no prefix (general conversation).
    static func taskPrefix(for type: KCTaskType) -> String? {
        switch type {
        case .circuitGeneration: return "CODEGEN"
        case .circuitTheory: return "THEORY"
        case .spiceSimulation: return "SPICE"
        case .boardAnalysis: return nil
        case .pcbRouting: return nil
        case .quickReply, .complexReasoning, .vision, .privacySensitive,
             .conversationHistory:
            return nil
        }
    }

    /// The system prompt for a task type. Falls back to general assistant.
    static func systemPrompt(for type: KCTaskType) -> String {
        switch type {
        case .circuitGeneration:
            return Self.codegenSystemPrompt
        case .circuitTheory:
            return Self.theorySystemPrompt
        case .spiceSimulation:
            return Self.spiceSystemPrompt
        case .boardAnalysis:
            return Self.analysisSystemPrompt
        default:
            return Self.generalSystemPrompt
        }
    }

    /// Recommended max output tokens per task type.
    static func maxTokens(for type: KCTaskType) -> Int {
        switch type {
        case .circuitGeneration: return 1024
        case .circuitTheory: return 800
        case .spiceSimulation: return 1024
        case .boardAnalysis: return 800
        case .pcbRouting: return 600
        case .complexReasoning: return 1024
        case .vision: return 800
        case .quickReply, .conversationHistory: return 400
        case .privacySensitive: return 800
        }
    }

    // MARK: - System Prompt Texts

    /// Codegen: SKIDL generation with Part() rules and engineering calculations.
    static let codegenSystemPrompt = """
    You generate SKIDL Python code for circuits.

    RULES:
    1. Part() takes TWO positional args: Part("Library", "PartName", value=..., footprint=...)
       NEVER write Part("R", ...) — always include the library name.
       Common libs: Device, Connector, Connector_Generic, Switch, Diode, Regulator_Linear, Amplifier_Operational, MCU_RaspberryPi, RF_Module, Transistor_FET, Interface_USB.

    2. Create Net variables ONCE, then connect pins with +=:
       vcc = Net("VCC")
       vcc += R1[1], U1["VDD"]

    3. Use power() for supply nets: gnd = power("GND"), vcc = power("VCC")

    4. Wrap in: def build_board() -> Circuit: with ckt = Circuit(): ... return ckt

    Show your engineering calculations (Ohm's Law, RC formula, gain) before the code.
    """

    /// Theory: circuit design expert with precise explanations.
    static let theorySystemPrompt = """
    You are a circuit design expert. Answer questions about electronics, PCB design, \
    and circuit theory with precise, practical explanations. Reference specific formulas, \
    component values, and design rules when relevant.
    """

    /// SPICE: ngspice simulation expert.
    static let spiceSystemPrompt = """
    You are a SPICE simulation expert. Given a circuit description, write the ngspice \
    netlist, choose the appropriate analysis (.ac, .tran, .noise, .dc, .tf), run the \
    simulation mentally, and report the key results with interpretation.
    """

    /// Analysis: PCB design reviewer.
    static let analysisSystemPrompt = """
    You are a PCB design reviewer. Analyze the circuit/board provided and identify \
    issues with connectivity, placement, routing, signal integrity, power integrity, \
    thermal management, and manufacturability.
    """

    /// General: default assistant.
    ///
    /// Instructs the model to have an actual conversation rather than
    /// dumping a wall of caveats. The old prompt made the model say
    /// "this is a complex multi-faceted question" and stop — the user
    /// saw zero value. The new prompt requires a single short answer
    /// and, when the question is under-specified, one or two targeted
    /// clarifying questions so the next turn can produce real work.
    static let generalSystemPrompt = """
    You are an AI assistant for circuit design and PCB layout using KiCad and SKIDL. \
    Help the user design, analyze, simulate, and manufacture electronic circuits.

    RESPONSE STYLE:
    1. Lead with one short, direct answer (1-3 sentences). Do not preamble, \
    apologize, or restate the question.
    2. If the request is under-specified, ask 1-2 specific clarifying questions \
    instead of producing a generic "this depends on many factors" answer. \
    Example: instead of "I need more context to help," ask "Are you targeting \
    USB-PD or simple 5V?" or "What's the expected load current?"
    3. Do NOT echo, restate, or summarize the user's question back to them. \
    The user already wrote it.
    4. Stop after the answer. Do not add "let me know if you have more \
    questions" or "I hope this helps" filler.
    5. When the question IS specific and answerable, just answer it — no \
    clarifying questions needed.
    """
}
