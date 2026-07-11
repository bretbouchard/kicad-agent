//
//  RouterStreamProvider.swift
//  KiCadAgent
//
//  Phase 211 — Chat → Router → Stream Pipeline
//
//  Bridges KiCadModelRouter to the ChatStreamProvider protocol.
//  The router returns AsyncThrowingStream<KCToken, Error>; ChatView
//  wants AsyncThrowingStream<String, Error>. This adapter maps
//  .text tokens to String and drops .usage/.done tokens.
//

import Foundation

/// Production ChatStreamProvider backed by KiCadModelRouter.
///
/// Wraps the router's `generate(from:)` call and extracts text tokens
/// for the chat UI. Cost/usage metadata is available via the closure
/// callback after streaming completes.
struct RouterStreamProvider: ChatStreamProvider {
    let router: KiCadModelRouter

    /// Called with the final usage stats when streaming completes.
    /// The view uses this to persist token counts + cost to SwiftData.
    var onUsage: (@Sendable (KCUsage) -> Void)?

    func stream(prompt: String, attachments: [ImageAttachment]) -> AsyncThrowingStream<String, Error> {
        let router = router
        let usageCallback = onUsage

        return AsyncThrowingStream { continuation in
            Task { @MainActor in
                do {
                    // Build a KCPrompt from the user text
                    let kcPrompt = KCPrompt.user(prompt)

                    // Route through the provider pipeline
                    let tokenStream = try await router.generate(from: kcPrompt)

                    for try await token in tokenStream {
                        switch token {
                        case .text(let text):
                            continuation.yield(text)
                        case .usage(let usage):
                            usageCallback?(usage)
                        case .done:
                            break
                        case .toolCall:
                            break
                        }
                    }
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
        }
    }
}
