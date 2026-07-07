//
//  LiquidGlassModifiers.swift
//  KiCadAgent
//
//  Phase 161 — App Shell Foundation
//
//  Reusable Liquid Glass style modifiers.
//
//  On macOS 26.x SDK: `.background(.regularMaterial)` produces the canonical
//  translucent Liquid Glass material. The dedicated `.glassEffect()` modifier
//  ships with the macOS 27 SDK and will be added when Xcode 27 lands
//  (Phase 162 — Python Daemon Bundling will re-baseline against SDK 27).
//
//  APP-07: All modifiers honor system appearance automatically (system materials
//  adapt to light/dark). A11Y-06: Reduce Transparency respected via system material.
//

import SwiftUI

/// Liquid Glass style wrappers — single source of truth for the visual language.
extension View {
    /// Standard Liquid Glass panel — sidebar items, cards, chat bubbles.
    func liquidGlassPanel(corner: CGFloat = CornerRadius.standard) -> some View {
        self
            .padding(Spacing.md)
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: corner, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: corner, style: .continuous)
                    .strokeBorder(Color.primary.opacity(0.08), lineWidth: StrokeWidth.hairline)
            )
    }

    /// Prominent Liquid Glass panel — sheets, modals, hero cards.
    func liquidGlassHero(corner: CGFloat = CornerRadius.large) -> some View {
        self
            .padding(Spacing.lg)
            .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: corner, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: corner, style: .continuous)
                    .strokeBorder(Color.primary.opacity(0.10), lineWidth: StrokeWidth.thin)
            )
            .shadow(color: Color.black.opacity(0.08), radius: 12, y: 4)
    }

    /// Toolbar-style Liquid Glass strip — used for in-content toolbars.
    func liquidGlassToolbar(corner: CGFloat = CornerRadius.small) -> some View {
        self
            .padding(.horizontal, Spacing.sm)
            .padding(.vertical, Spacing.xxs)
            .background(.thinMaterial, in: RoundedRectangle(cornerRadius: corner, style: .continuous))
    }

    /// Apply focus ring consistent with Liquid Glass.
    func liquidGlassFocus() -> some View {
        self.focusEffectDisabled(false)
    }
}
