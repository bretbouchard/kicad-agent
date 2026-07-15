//
//  ProjectGenealogyView.swift
//  Volta
//
//  Phase 186 — Project Genealogy
//
//  Visualizes a project's family tree of branches. Shows forks, false
//  starts, explorations, and rollbacks as a graph.
//
//  GEN-01/02/03/04/05: genealogy visualization requirements.
//

import SwiftUI

/// Family tree visualization for project branches.
struct ProjectGenealogyView: View {
    let branches: [ProjectBranch]
    let onSelectBranch: (ProjectBranch) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Divider().opacity(0.3)
            tree
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Project genealogy")
        .accessibilityHint("Visualizes branches, forks, and false starts")
    }

    private var header: some View {
        HStack {
            VStack(alignment: .leading, spacing: Spacing.xxs) {
                Text("Project Family Tree")
                    .font(Typography.title)
                    .accessibilityAddTraits(.isHeader)
                Text("\(branches.count) branches")
                    .font(Typography.caption)
                    .foregroundStyle(ColorTokens.secondaryText)
            }
            Spacer()
        }
        .padding(Spacing.md)
    }

    @ViewBuilder
    private var tree: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Spacing.xs) {
                ForEach(rootBranches) { branch in
                    branchNodeView(branch, depth: 0)
                }
            }
            .padding(Spacing.lg)
        }
    }

    /// Recursive branch node — returns AnyView to break opaque-type recursion.
    private func branchNodeView(_ branch: ProjectBranch, depth: Int) -> AnyView {
        let children = childrenOf(branch)
        return AnyView(VStack(alignment: .leading, spacing: Spacing.xs) {
            HStack(spacing: Spacing.sm) {
                Image(systemName: branch.branchType.icon)
                    .foregroundStyle(branch.branchType.color)
                    .font(.system(size: 16))
                VStack(alignment: .leading, spacing: 0) {
                    Text(branch.label)
                        .font(Typography.heading)
                    Text(branch.branchType.label)
                        .font(Typography.caption)
                        .foregroundStyle(ColorTokens.tertiaryText)
                }
                Spacer()
                if let outcome = branch.outcome {
                    OutcomeBadge(outcome: outcome)
                }
            }
            .padding(.leading, CGFloat(depth) * Spacing.lg)
            .padding(Spacing.sm)
            .background(branchColor(branch).opacity(0.05), in: RoundedRectangle(cornerRadius: CornerRadius.standard))
            .contentShape(Rectangle())
            .onTapGesture { onSelectBranch(branch) }

            ForEach(children) { child in
                branchNodeView(child, depth: depth + 1)
            }
        })
    }

    private var rootBranches: [ProjectBranch] {
        branches.filter { $0.parentBranchId == nil }
    }

    private func childrenOf(_ parent: ProjectBranch) -> [ProjectBranch] {
        branches.filter { $0.parentBranchId == parent.id }
    }

    private func branchColor(_ branch: ProjectBranch) -> Color {
        branch.branchType.color
    }
}

extension BranchType {
    var label: String {
        switch self {
        case .fork: return "Fork"
        case .falseStart: return "False Start"
        case .exploration: return "Exploration"
        case .rollback: return "Rollback"
        case .continuation: return "Continuation"
        }
    }

    var icon: String {
        switch self {
        case .fork: return "tuningfork"
        case .falseStart: return "xmark.circle"
        case .exploration: return "compass"
        case .rollback: return "arrow.uturn.backward.circle"
        case .continuation: return "arrow.right.circle"
        }
    }

    var color: Color {
        switch self {
        case .fork: return .accentColor
        case .falseStart: return ColorTokens.destructive
        case .exploration: return ColorTokens.warning
        case .rollback: return .purple
        case .continuation: return ColorTokens.success
        }
    }
}

/// Outcome pill for a branch.
struct OutcomeBadge: View {
    let outcome: BranchOutcome

    var body: some View {
        Text(outcome.label)
            .font(.system(size: 9, weight: .semibold))
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(outcome.color.opacity(0.18), in: Capsule())
            .foregroundStyle(outcome.color)
            .accessibilityLabel("Outcome: \(outcome.label)")
    }
}

extension BranchOutcome {
    var label: String {
        switch self {
        case .active: return "ACTIVE"
        case .merged: return "MERGED"
        case .abandoned: return "ABANDONED"
        case .superseded: return "SUPERSEDED"
        }
    }

    var color: Color {
        switch self {
        case .active: return ColorTokens.success
        case .merged: return .accentColor
        case .abandoned: return ColorTokens.destructive
        case .superseded: return ColorTokens.warning
        }
    }
}
