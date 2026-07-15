//
//  DesignTokens.swift
//  Volta
//
//  Phase 161 — App Shell Foundation
//
//  Design tokens for the Liquid Glass visual language.
//
//  Spacing on an 8px grid, hierarchical typography, semantic colors.
//  All values are Swift constants — never hardcode in views.
//
//  ponytail: tokens as enum namespaces. No instances. No runtime config.
//

import SwiftUI

/// Spacing tokens — 8px grid system.
enum Spacing {
    /// 4pt — fine adjustments (icon insets).
    static let xxs: CGFloat = 4
    /// 8pt — base unit.
    static let xs: CGFloat = 8
    /// 12pt — small component padding.
    static let sm: CGFloat = 12
    /// 16pt — standard padding.
    static let md: CGFloat = 16
    /// 24pt — section padding.
    static let lg: CGFloat = 24
    /// 32pt — major section gaps.
    static let xl: CGFloat = 32
    /// 48pt — window margin on large displays.
    static let xxl: CGFloat = 48
}

/// Corner radius tokens.
enum CornerRadius {
    /// 4pt — buttons, chips.
    static let small: CGFloat = 4
    /// 8pt — standard cards, inputs.
    static let standard: CGFloat = 8
    /// 12pt — prominent cards, sheets.
    static let large: CGFloat = 12
    /// 16pt — modals.
    static let xl: CGFloat = 16
}

/// Stroke width tokens.
enum StrokeWidth {
    static let hairline: CGFloat = 0.5
    static let thin: CGFloat = 1
    static let standard: CGFloat = 1.5
    static let emphasis: CGFloat = 2
}

/// Typography tokens — SF Pro family.
///
/// ponytail: defer to SwiftUI's built-in font styles so Dynamic Type scales
/// automatically (A11Y-05). Use semantic roles, not raw sizes.
enum Typography {
    /// Large display — empty state hero.
    static let hero = Font.largeTitle.weight(.bold)
    /// Section title.
    static let title = Font.title.weight(.semibold)
    /// Section header.
    static let heading = Font.headline
    /// Body text.
    static let body = Font.body
    /// Caption / metadata.
    static let caption = Font.caption
    /// Monospace — KiCad IDs, code, file paths.
    static let mono = Font.body.monospaced()
}

/// Semantic color tokens.
///
/// ponytail: built on SwiftUI semantic colors so dark mode, increased contrast,
/// and accessibility settings work automatically (APP-07, A11Y-06, A11Y-07, A11Y-08).
enum ColorTokens {
    /// Standard action color — primary buttons, selected state.
    static let action = Color.accentColor
    /// Destructive actions — delete, abandon.
    static let destructive = Color.red
    /// Warning — non-blocking issue.
    static let warning = Color.orange
    /// Success — verified gate, completed phase.
    static let success = Color.green
    /// Secondary text — captions, metadata.
    static let secondaryText = Color.secondary
    /// Tertiary text — timestamps, IDs.
    static let tertiaryText = Color.secondary.opacity(0.7)
}

/// Window layout tokens.
enum WindowLayout {
    /// Minimum window size — keep chat usable on small laptops.
    static let minWidth: CGFloat = 900
    static let minHeight: CGFloat = 600
    /// Default sidebar width — comfortable for 20-char project names.
    static let sidebarWidth: CGFloat = 260
    static let sidebarMinWidth: CGFloat = 200
    static let sidebarMaxWidth: CGFloat = 400
}
