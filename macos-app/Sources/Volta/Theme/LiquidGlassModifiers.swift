//
//  LiquidGlassModifiers.swift
//  Volta
//
//  Phase 161 — App Shell Foundation
//  Phase 171 — Reduce Transparency awareness (A11Y-06)
//
//  Reusable Liquid Glass style modifiers.
//
//  On macOS 26.x SDK: `.background(.regularMaterial)` produces the canonical
//  translucent Liquid Glass material. The dedicated `.glassEffect()` modifier
//  ships with the macOS 27 SDK and will be added when Xcode 27 lands
//  (Phase 162 — Python Daemon Bundling will re-baseline against SDK 27).
//
//  APP-07: All modifiers honor system appearance automatically (system materials
//  adapt to light/dark). A11Y-06: Reduce Transparency respected — when the user
//  enables "Reduce Transparency" in System Settings → Accessibility → Display,
//  materials swap to opaque colors so content remains legible.
//

import SwiftUI

/// Liquid Glass style wrappers — single source of truth for the visual language.
extension View {
    /// Standard Liquid Glass panel — sidebar items, cards, chat bubbles.
    /// Respects Reduce Transparency (A11Y-06): swaps material → opaque background.
    func liquidGlassPanel(corner: CGFloat = CornerRadius.standard) -> some View {
        modifier(LiquidGlassPanelModifier(corner: corner, prominence: .standard))
    }

    /// Prominent Liquid Glass panel — sheets, modals, hero cards.
    /// Respects Reduce Transparency (A11Y-06).
    func liquidGlassHero(corner: CGFloat = CornerRadius.large) -> some View {
        modifier(LiquidGlassPanelModifier(corner: corner, prominence: .hero))
    }

    /// Toolbar-style Liquid Glass strip — used for in-content toolbars.
    /// Respects Reduce Transparency (A11Y-06).
    func liquidGlassToolbar(corner: CGFloat = CornerRadius.small) -> some View {
        modifier(LiquidGlassPanelModifier(corner: corner, prominence: .toolbar))
    }

    /// Apply focus ring consistent with Liquid Glass.
    func liquidGlassFocus() -> some View {
        self.focusEffectDisabled(false)
    }
}

/// Prominence levels — each maps to a different material / opacity combo.
private enum LiquidGlassProminence {
    case standard
    case hero
    case toolbar
}

/// Single ViewModifier handling all Liquid Glass panel variants.
/// Centralizes Reduce Transparency logic (A11Y-06).
private struct LiquidGlassPanelModifier: ViewModifier {
    let corner: CGFloat
    let prominence: LiquidGlassProminence
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency

    func body(content: Content) -> some View {
        let shape = RoundedRectangle(cornerRadius: corner, style: .continuous)

        // When user enables Reduce Transparency, materials become opaque.
        // Apple HIG: respect this preference absolutely — no exceptions.
        if reduceTransparency {
            content
                .padding(padding)
                .background(Color(nsColor: .controlBackgroundColor), in: shape)
                .overlay(
                    shape.strokeBorder(Color.primary.opacity(strokeOpacity), lineWidth: strokeWidth)
                )
        } else {
            content
                .padding(padding)
                .background(material, in: shape)
                .overlay(
                    shape.strokeBorder(Color.primary.opacity(strokeOpacity), lineWidth: strokeWidth)
                )
                .shadow(color: shadowColor, radius: shadowRadius, y: shadowY)
        }
    }

    private var padding: EdgeInsets {
        switch prominence {
        case .standard: return EdgeInsets(top: Spacing.md, leading: Spacing.md, bottom: Spacing.md, trailing: Spacing.md)
        case .hero: return EdgeInsets(top: Spacing.lg, leading: Spacing.lg, bottom: Spacing.lg, trailing: Spacing.lg)
        case .toolbar: return EdgeInsets(top: Spacing.xxs, leading: Spacing.sm, bottom: Spacing.xxs, trailing: Spacing.sm)
        }
    }

    private var material: Material {
        switch prominence {
        case .standard: return .regular
        case .hero: return .ultraThin
        case .toolbar: return .thin
        }
    }

    private var strokeOpacity: Double {
        switch prominence {
        case .standard: return 0.08
        case .hero: return 0.10
        case .toolbar: return 0.06
        }
    }

    private var strokeWidth: CGFloat {
        switch prominence {
        case .standard: return StrokeWidth.hairline
        case .hero: return StrokeWidth.thin
        case .toolbar: return StrokeWidth.hairline
        }
    }

    private var shadowColor: Color { Color.black.opacity(prominence == .hero ? 0.08 : 0) }
    private var shadowRadius: CGFloat { prominence == .hero ? 12 : 0 }
    private var shadowY: CGFloat { prominence == .hero ? 4 : 0 }
}
