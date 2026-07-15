//
//  Starters.swift
//  Volta
//
//  Phase 242 — First-run Onboarding
//
//  Three starter projects shown on the first onboarding step. Picking
//  one creates a real `Project` in SwiftData and pre-fills the chat
//  compose bar with a canonical prompt so the user sees the
//  end-to-end flow without having to think of their own hardware
//  intent first.
//
//  ponytail: starters are *content*, not *code*. No business logic
//  here. Just an enum of {name, icon, blurb, prompt} so the view
//  layer can render and the parent's "create project" closure can
//  use the prompt directly.
//

import Foundation

/// A starter project the onboarding tour offers to new users.
struct OnboardingStarter: Identifiable, Equatable, Sendable {
    let id: String
    let name: String
    let iconSystemName: String
    let blurb: String
    /// Canonical prompt the user can send verbatim to see the
    /// end-to-end flow. Kept terse (≤ 200 chars) so the chat
    /// compose bar's preview shows the whole thing.
    let prompt: String

    static let all: [OnboardingStarter] = [
        OnboardingStarter(
            id: "led-blinker",
            name: "LED Blinker",
            iconSystemName: "lightbulb.fill",
            blurb: "555-timer astable, 1 Hz blink, single LED. The 'hello world' of analog.",
            prompt: "Design a 555-timer LED blinker that pulses once per second."
        ),
        OnboardingStarter(
            id: "esp32-breakout",
            name: "ESP32 Breakout",
            iconSystemName: "cpu.fill",
            blurb: "USB-C, BOOT + RESET buttons, 3V3 LDO. Breadboard-friendly.",
            prompt: "Design an ESP32-WROOM-32 dev board with USB-C and BOOT/RESET buttons."
        ),
        OnboardingStarter(
            id: "opamp-preamp",
            name: "Op-amp Preamp",
            iconSystemName: "waveform",
            blurb: "20 dB non-inverting, single supply, audio in / out.",
            prompt: "Design a 20 dB non-inverting op-amp preamp on a single 9V supply."
        )
    ]
}
