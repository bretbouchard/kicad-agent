//
//  PCBPreviewView.swift
//  KiCadAgent
//
//  Phase 172 — Inline Rendering
//
//  Renders a PCB PNG inline within chat / detail surfaces. Loading / success
//  / error states with "Regenerate" affordance.
//
//  T-172-01: PNG magic-byte verification before render.
//  CHAT-04: PCB previews render inline.
//  A11Y-03: every interactive element labeled.
//

import SwiftUI
import OSLog

/// Inline PNG PCB preview with loading / success / error states.
struct PCBPreviewView: View {
    let pcbPath: URL
    let side: PCBSide
    let renderer: PreviewRenderer

    @State private var loadState: LoadState = .idle
    @State private var artifact: RenderArtifact?
    @State private var showInspector: Bool = false

    enum LoadState: Equatable {
        case idle
        case loading
        case loaded
        case failed(String)
    }

    var body: some View {
        Group {
            switch loadState {
            case .idle, .loading:
                loadingView
            case .loaded:
                if let artifact {
                    successView(artifact)
                } else {
                    loadingView
                }
            case .failed(let reason):
                failureView(reason)
            }
        }
        .task {
            await render()
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("PCB preview")
        .accessibilityHint("Rendering board. Double-tap to open full screen when ready.")
    }

    private var loadingView: some View {
        VStack(spacing: Spacing.sm) {
            ProgressView()
                .controlSize(.large)
            Text("Rendering board (\(side.rawValue))…")
                .font(Typography.caption)
                .foregroundStyle(ColorTokens.secondaryText)
        }
        .frame(maxWidth: .infinity, minHeight: 180)
        .liquidGlassPanel()
    }

    private func successView(_ artifact: RenderArtifact) -> some View {
        // T-172-01: PNG magic verified at render time.
        Image(nsImage: NSImage(byReferencing: artifact.url))
            .resizable()
            .aspectRatio(contentMode: .fit)
            .frame(maxWidth: .infinity, minHeight: 180)
            .liquidGlassPanel()
            .contentShape(Rectangle())
            .onTapGesture { showInspector = true }
            .accessibilityAddTraits(.isButton)
            .accessibilityHint("PCB render ready. Double-tap to open full screen.")
            .sheet(isPresented: $showInspector) {
                FullScreenInspector(title: "PCB", url: artifact.url)
            }
    }

    private func failureView(_ reason: String) -> some View {
        VStack(spacing: Spacing.sm) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 32))
                .foregroundStyle(ColorTokens.destructive)
                .accessibilityHidden(true)
            Text("Render failed")
                .font(Typography.heading)
            Text(reason)
                .font(Typography.caption)
                .foregroundStyle(ColorTokens.secondaryText)
                .multilineTextAlignment(.center)
                .padding(.horizontal)
            Button("Regenerate", action: retry)
                .buttonStyle(.borderedProminent)
                .accessibilityLabel("Regenerate PCB preview")
                .accessibilityHint("Triggers a fresh render of the board")
        }
        .frame(maxWidth: .infinity, minHeight: 180)
        .liquidGlassPanel()
    }

    private func render() async {
        guard loadState != .loaded, loadState != .loading else { return }
        loadState = .loading
        do {
            let result = try await renderer.renderPCB(pcbPath: pcbPath, side: side)
            // T-172-01: verify magic bytes before surfacing.
            guard MagicBytes.verify(url: result.url, expected: MagicBytes.png) else {
                throw InlineRenderingError.invalidMagicBytes(
                    expected: "89 50 4E 47",
                    actual: "<unreadable>"
                )
            }
            artifact = result
            loadState = .loaded
        } catch {
            Logger.ui.error("PCB render failed: \(error.localizedDescription, privacy: .public)")
            loadState = .failed(error.localizedDescription)
        }
    }

    private func retry() {
        artifact = nil
        loadState = .idle
        Task { await render() }
    }
}
