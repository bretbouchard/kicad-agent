//
//  ProviderBanner.swift
//  Volta
//
//  Phase 164 — LLM Provider Protocol (Task 6)
//
//  Per MOD-06 augmentation: Devices without Apple Intelligence see a banner
//  explaining local-only mode + link to add API key. Per Pitfall 3:
//  FoundationModels unavailable is the trigger; MLX is the fallback.
//
//  Three states:
//    - hidden: at least one local provider available, FoundationModels works
//    - local-only: FoundationModels down, MLX/Mock available
//    - nothing: no providers available at all (rare; user must act)
//

import SwiftUI
import OSLog

/// Banner shown above the chat shell when FoundationModels isn't available.
/// Compact, dismissable per session, deep-links to Settings when applicable.
struct ProviderBanner: View {
    /// Snapshot of what the banner should say. ProviderRegistry builds this
    /// so the banner doesn't need its own async probes on every render.
    let state: BannerState

    /// Dismiss action (store a session-scoped flag).
    var onDismiss: () -> Void = {}

    /// Deep-link to BYOK settings (Phase 166 wires the destination).
    var onAddAPIKey: (() -> Void)? = nil

    var body: some View {
        if !state.shouldShow { EmptyView() } else {
            HStack(alignment: .top, spacing: Spacing.sm) {
                Image(systemName: state.iconName)
                    .font(Typography.body)
                    .foregroundStyle(state.accentColor)
                    .accessibilityHidden(true)

                VStack(alignment: .leading, spacing: Spacing.xxs) {
                    Text(state.title)
                        .font(Typography.heading)
                        .foregroundStyle(Color.primary)
                    Text(state.message)
                        .font(Typography.caption)
                        .foregroundStyle(ColorTokens.secondaryText)
                        .fixedSize(horizontal: false, vertical: true)
                }

                Spacer(minLength: Spacing.sm)

                if let onAddAPIKey = onAddAPIKey {
                    Button("Add API Key", action: onAddAPIKey)
                        .buttonStyle(.bordered)
                        .controlSize(.small)
                        .accessibilityHint("Opens Settings to add a cloud provider API key")
                }

                Button {
                    onDismiss()
                } label: {
                    Image(systemName: "xmark")
                        .font(Typography.caption)
                        .foregroundStyle(ColorTokens.secondaryText)
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Dismiss banner")
                .accessibilityHint("Hide this banner until the next session")
            }
            .padding(.horizontal, Spacing.md)
            .padding(.vertical, Spacing.sm)
            .background(state.backgroundColor)
            .overlay(
                Rectangle()
                    .fill(state.accentColor.opacity(0.3))
                    .frame(height: StrokeWidth.hairline),
                alignment: .top
            )
            .accessibilityElement(children: .combine)
            .accessibilityLabel("\(state.title). \(state.message)")
        }
    }
}

// MARK: - BannerState

extension ProviderBanner {
    /// ponytail: precomputed banner shape — banner just renders.
    /// Avoids async probes inside the view body.
    enum BannerState: Equatable {
        /// Hide the banner.
        case hidden
        /// FoundationModels unavailable, but MLX or another local works.
        case localOnlyMode(providerName: String, appleIntelligenceReason: String)
        /// No providers available. User must act.
        case noProvidersAvailable

        var shouldShow: Bool {
            self != .hidden
        }

        var title: String {
            switch self {
            case .hidden: return ""
            case .localOnlyMode: return "Local-only mode"
            case .noProvidersAvailable: return "No AI providers available"
            }
        }

        var message: String {
            switch self {
            case .hidden: return ""
            case .localOnlyMode(let providerName, let reason):
                return "Apple Intelligence isn't available (\(reason)). Using \(providerName). Add an API key for cloud models."
            case .noProvidersAvailable:
                return "No AI providers are ready. Add an API key or download a local model to start."
            }
        }

        var iconName: String {
            switch self {
            case .hidden: return ""
            case .localOnlyMode: return "cpu"
            case .noProvidersAvailable: return "exclamationmark.triangle.fill"
            }
        }

        var accentColor: Color {
            switch self {
            case .hidden: return .clear
            case .localOnlyMode: return ColorTokens.warning
            case .noProvidersAvailable: return ColorTokens.destructive
            }
        }

        var backgroundColor: Color {
            accentColor.opacity(0.1)
        }
    }
}

// MARK: - Preview

#if DEBUG
#Preview("Hidden") {
    ProviderBanner(state: .hidden)
        .padding()
}

#Preview("Local-only mode") {
    ProviderBanner(
        state: .localOnlyMode(
            providerName: "MLX: gemma-3-4b",
            appleIntelligenceReason: "Apple Intelligence not enabled"
        )
    )
    .padding()
}

#Preview("No providers available") {
    ProviderBanner(state: .noProvidersAvailable)
        .padding()
}
#endif
