//
//  CollaborationActivityFeed.swift
//  Volta
//
//  Phase 189 — Collaboration UI
//
//  Activity feed for shared projects. Shows collaborator actions in real
//  time. Includes permissions management UI.
//
//  COLLAB-05/06/07/08/10: activity feed + permissions requirements.
//  LIVE-03/04/05: live collaboration UI requirements.
//

import SwiftUI

/// Activity feed for a shared project.
struct CollaborationActivityFeed: View {
    let events: [CollaborationEvent]
    let participants: [Participant]
    let onManagePermissions: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            participantsHeader
            Divider().opacity(0.3)
            eventsList
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Collaboration activity feed")
        .accessibilityHint("Shows recent participant actions and current permissions")
    }

    private var participantsHeader: some View {
        HStack(spacing: Spacing.sm) {
            participantsStack
            VStack(alignment: .leading, spacing: 0) {
                Text("\(participants.count) participants")
                    .font(Typography.heading)
                Text(participants.map(\.displayName).joined(separator: ", "))
                    .font(Typography.caption)
                    .foregroundStyle(ColorTokens.tertiaryText)
                    .lineLimit(1)
            }
            Spacer()
            Button("Manage Permissions", action: onManagePermissions)
                .buttonStyle(.bordered)
                .accessibilityHint("Open permissions panel")
        }
        .padding(Spacing.md)
    }

    private var participantsStack: some View {
        HStack(spacing: -8) {
            ForEach(participants.prefix(4)) { participant in
                Circle()
                    .fill(participant.isLocal ? ColorTokens.action : ColorTokens.success)
                    .frame(width: 28, height: 28)
                    .overlay(
                        Text(String(participant.displayName.prefix(2).uppercased()))
                            .font(.system(size: 10, weight: .bold))
                            .foregroundStyle(.white)
                    )
                    .overlay(Circle().stroke(.white, lineWidth: 2))
            }
        }
        .accessibilityHidden(true)
    }

    private var eventsList: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: Spacing.xs) {
                if events.isEmpty {
                    Text("No activity yet")
                        .font(Typography.body)
                        .foregroundStyle(ColorTokens.tertiaryText)
                        .padding(Spacing.md)
                } else {
                    ForEach(events, id: \.id) { event in
                        CollaborationEventRow(event: event)
                    }
                }
            }
            .padding(Spacing.md)
        }
    }
}

/// One row in the activity feed.
struct CollaborationEventRow: View {
    let event: CollaborationEvent

    var body: some View {
        HStack(alignment: .top, spacing: Spacing.sm) {
            Image(systemName: event.kind.icon)
                .foregroundStyle(event.kind.color)
                .frame(width: 20)
            VStack(alignment: .leading, spacing: Spacing.xxs) {
                Text(event.summary)
                    .font(Typography.body)
                HStack(spacing: Spacing.xxs) {
                    Text(event.participantName)
                        .font(Typography.caption.weight(.semibold))
                    Text("·")
                    Text(event.timestamp.formatted(.relative(presentation: .named)))
                        .font(Typography.caption)
                }
                .foregroundStyle(ColorTokens.tertiaryText)
            }
            Spacer()
        }
        .padding(Spacing.xs)
        .liquidGlassPanel()
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(event.participantName) \(event.summary)")
    }
}

/// One collaboration event (decision, change, message, join/leave).
struct CollaborationEvent: Identifiable, Sendable, Equatable {
    let id: UUID
    let kind: CollaborationEventKind
    let participantName: String
    let summary: String
    let timestamp: Date

    init(id: UUID = UUID(), kind: CollaborationEventKind, participantName: String, summary: String, timestamp: Date = .now) {
        self.id = id
        self.kind = kind
        self.participantName = participantName
        self.summary = summary
        self.timestamp = timestamp
    }
}

enum CollaborationEventKind: String, Sendable, Equatable {
    case decision
    case change
    case message
    case joined
    case left

    var icon: String {
        switch self {
        case .decision: return "checkmark.seal"
        case .change: return "pencil.line"
        case .message: return "bubble.left"
        case .joined: return "arrow.down.to.line"
        case .left: return "arrow.up.and.right.and.arrow.down.and.left"
        }
    }

    var color: Color {
        switch self {
        case .decision: return ColorTokens.success
        case .change: return ColorTokens.warning
        case .message: return .accentColor
        case .joined: return ColorTokens.success
        case .left: return ColorTokens.tertiaryText
        }
    }
}
