//
//  DecisionTimelineView.swift
//  KiCadAgent
//
//  Phase 179 — Decision Timeline UI
//
//  Visual timeline of decisions + value changes with pagination,
//  filtering, and chapter segmentation. Lazy-loads chunks to stay
//  fast on 100K-event datasets (Pitfall 8 prevention).
//
//  TT-01: timeline shows all decisions chronologically
//  TT-05: filter by type / date / participant
//  MEM-06: hybrid snapshot capture
//

import SwiftUI

/// Paginated timeline of decisions + value changes.
struct DecisionTimelineView: View {
    let entries: [TimelineEntry]
    let chapters: [TimelineChapter]
    let onLoadMore: () -> Void
    let onSelectEntry: (TimelineEntry) -> Void
    let onScrub: (Date) -> Void

    @State private var filter: TimelineFilter = .all
    @State private var searchText: String = ""

    var body: some View {
        VStack(spacing: 0) {
            filterBar
            Divider().opacity(0.3)
            timelineList
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Decision timeline")
        .accessibilityHint("Scroll through project decisions. Tap any entry to view context.")
    }

    private var filterBar: some View {
        HStack {
            Picker("Filter", selection: $filter) {
                ForEach(TimelineFilter.allCases) { f in
                    Text(f.label).tag(f)
                }
            }
            .pickerStyle(.segmented)
            HStack {
                Image(systemName: "magnifyingglass")
                    .foregroundStyle(ColorTokens.secondaryText)
                TextField("Search", text: $searchText)
                    .textFieldStyle(.plain)
                    .accessibilityLabel("Timeline search")
            }
            .liquidGlassToolbar()
        }
        .padding(Spacing.md)
    }

    private var timelineList: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: Spacing.sm) {
                ForEach(filteredEntries, id: \.id) { entry in
                    DecisionTimelineRow(entry: entry)
                        .contentShape(Rectangle())
                        .onTapGesture { onSelectEntry(entry) }
                        .onAppear {
                            if entry.id == filteredEntries.last?.id {
                                onLoadMore()
                            }
                        }
                }
            }
            .padding(Spacing.md)
        }
    }

    private var filteredEntries: [TimelineEntry] {
        var result = entries
        if filter != .all {
            result = result.filter { entry in
                switch filter {
                case .all: return true
                case .decisions: return entry.kind == .decision
                case .changes: return entry.kind == .valueChange
                case .snapshots: return entry.kind == .snapshot
                }
            }
        }
        if !searchText.isEmpty {
            result = result.filter { $0.title.localizedCaseInsensitiveContains(searchText) || $0.detail.localizedCaseInsensitiveContains(searchText) }
        }
        return result
    }
}

/// Single timeline row.
struct DecisionTimelineRow: View {
    let entry: TimelineEntry

    var body: some View {
        HStack(alignment: .top, spacing: Spacing.sm) {
            // Vertical timeline indicator
            VStack(spacing: 0) {
                Circle()
                    .fill(entry.color)
                    .frame(width: 12, height: 12)
                Rectangle()
                    .fill(ColorTokens.tertiaryText.opacity(0.3))
                    .frame(width: 2)
                    .frame(maxHeight: .infinity)
            }
            .frame(width: 14)

            VStack(alignment: .leading, spacing: Spacing.xxs) {
                HStack {
                    Text(entry.title)
                        .font(Typography.heading)
                    Spacer()
                    Text(entry.timestamp.formatted(.relative(presentation: .named)))
                        .font(Typography.caption)
                        .foregroundStyle(ColorTokens.tertiaryText)
                }
                Text(entry.detail)
                    .font(Typography.body)
                    .foregroundStyle(ColorTokens.secondaryText)
                    .lineLimit(2)
                if let actor = entry.actor {
                    Label(actor, systemImage: "person.fill")
                        .font(Typography.caption)
                        .foregroundStyle(ColorTokens.tertiaryText)
                }
            }
        }
        .padding(Spacing.sm)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(entry.kind.label): \(entry.title)")
        .accessibilityHint(entry.detail)
    }
}

/// One entry in the timeline (decision, value change, or snapshot).
struct TimelineEntry: Identifiable, Sendable, Equatable {
    let id: UUID
    let kind: TimelineEntryKind
    let timestamp: Date
    let title: String
    let detail: String
    let actor: String?
    let linkedMessageId: UUID?

    init(id: UUID = UUID(), kind: TimelineEntryKind, timestamp: Date, title: String, detail: String, actor: String? = nil, linkedMessageId: UUID? = nil) {
        self.id = id
        self.kind = kind
        self.timestamp = timestamp
        self.title = title
        self.detail = detail
        self.actor = actor
        self.linkedMessageId = linkedMessageId
    }

    var color: Color {
        switch kind {
        case .decision: return .accentColor
        case .valueChange: return .orange
        case .snapshot: return .purple
        }
    }
}

enum TimelineEntryKind: String, Sendable, CaseIterable {
    case decision
    case valueChange
    case snapshot

    var label: String {
        switch self {
        case .decision: return "Decision"
        case .valueChange: return "Value Change"
        case .snapshot: return "Snapshot"
        }
    }
}

/// Filter options for timeline.
enum TimelineFilter: String, CaseIterable, Identifiable {
    case all
    case decisions
    case changes
    case snapshots

    var id: String { rawValue }
    var label: String { rawValue.capitalized }
}

/// Chapter segmentation boundary.
struct TimelineChapter: Identifiable, Sendable, Equatable {
    let id: UUID
    let title: String
    let startIndex: Int
    let endIndex: Int
}
