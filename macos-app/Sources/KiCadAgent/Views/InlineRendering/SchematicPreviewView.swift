//
//  SchematicPreviewView.swift
//  KiCadAgent
//
//  Phase 172 — Inline Rendering
//
//  Renders a schematic SVG inline within chat / detail surfaces. Handles
//  loading / success / error states, with a "Regenerate" affordance.
//
//  T-172-01: SVG magic-byte verification before render.
//  CHAT-03: schematic previews render inline.
//  A11Y-03: every interactive element labeled.
//

import SwiftUI
import OSLog

/// Inline SVG schematic preview with loading / success / error states.
struct SchematicPreviewView: View {
    let schematicPath: URL
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
        .accessibilityLabel("Schematic preview")
        .accessibilityHint("Generating schematic preview. Double-tap to open full screen when ready.")
    }

    // MARK: - State views

    private var loadingView: some View {
        VStack(spacing: Spacing.sm) {
            ProgressView()
                .controlSize(.large)
            Text("Generating schematic…")
                .font(Typography.caption)
                .foregroundStyle(ColorTokens.secondaryText)
        }
        .frame(maxWidth: .infinity, minHeight: 180)
        .liquidGlassPanel()
    }

    private func successView(_ artifact: RenderArtifact) -> some View {
        // T-172-01: SVG file magic verified at render time; safe to display here.
        SVGImageView(url: artifact.url)
            .aspectRatio(contentMode: .fit)
            .frame(maxWidth: .infinity, minHeight: 180)
            .liquidGlassPanel()
            .contentShape(Rectangle())
            .onTapGesture { showInspector = true }
            .accessibilityAddTraits(.isButton)
            .accessibilityHint("Schematic ready. Double-tap to open full screen.")
            .sheet(isPresented: $showInspector) {
                FullScreenInspector(title: "Schematic", url: artifact.url)
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
                .accessibilityLabel("Regenerate schematic preview")
                .accessibilityHint("Triggers a fresh render of the schematic")
        }
        .frame(maxWidth: .infinity, minHeight: 180)
        .liquidGlassPanel()
    }

    // MARK: - Actions

    private func render() async {
        guard loadState != .loaded, loadState != .loading else { return }
        loadState = .loading
        do {
            let result = try await renderer.renderSchematic(schematicPath: schematicPath)
            // T-172-01: verify magic bytes before surfacing.
            guard MagicBytes.verify(url: result.url, expected: MagicBytes.svg) else {
                throw InlineRenderingError.invalidMagicBytes(
                    expected: String(decoding: MagicBytes.svg, as: UTF8.self),
                    actual: "<unreadable>"
                )
            }
            artifact = result
            loadState = .loaded
        } catch {
            Logger.ui.error("Schematic render failed: \(error.localizedDescription, privacy: .public)")
            loadState = .failed(error.localizedDescription)
        }
    }

    private func retry() {
        artifact = nil
        loadState = .idle
        Task { await render() }
    }
}

/// Lightweight SVG viewer using WebKit for native rendering.
///
/// ponytail: WKWebView is the only Apple-native SVG renderer in macOS 26 SDK.
/// Wrapping in UIViewRepresentable would be iOS; macOS uses NSViewRepresentable.
struct SVGImageView: NSViewRepresentable {
    let url: URL

    func makeNSView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        let web = WKWebView(frame: .zero, configuration: config)
        web.navigationDelegate = context.coordinator
        web.loadFileURL(url, allowingReadAccessTo: url.deletingLastPathComponent())
        return web
    }

    func updateNSView(_ nsView: WKWebView, context: Context) {}

    func makeCoordinator() -> Coordinator { Coordinator() }

    final class Coordinator: NSObject, WKNavigationDelegate {
        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            // SVG loaded — no-op, view displays it.
        }
    }
}

#if canImport(WebKit)
import WebKit
#endif
