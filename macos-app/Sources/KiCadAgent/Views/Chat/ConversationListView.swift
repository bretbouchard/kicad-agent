//
//  ConversationListView.swift
//  KiCadAgent
//
//  Phase 175 — Chat Interface
//
//  Conversation history list with search. Filters by title + fork badge.
//
//  CHAT-05: scroll, search, copy from full conversation history.
//

import SwiftUI

/// Conversation list with search filter.
struct ConversationListView: View {
    let conversations: [Conversation]
    let selectedId: Binding<UUID?>
    let onSelect: (Conversation) -> Void
    let onNewConversation: () -> Void

    @State private var searchText: String = ""

    var body: some View {
        VStack(spacing: 0) {
            header
            searchField
            list
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Conversation list")
    }

    private var header: some View {
        HStack {
            Text("Conversations")
                .font(Typography.title)
                .accessibilityAddTraits(.isHeader)
            Spacer()
            Button(action: onNewConversation) {
                Image(systemName: "plus.circle.fill")
                    .font(.system(size: 18))
            }
            .buttonStyle(.plain)
            .accessibilityLabel("New conversation")
            .accessibilityHint("Starts a fresh conversation in this project")
        }
        .padding(Spacing.md)
    }

    private var searchField: some View {
        HStack {
            Image(systemName: "magnifyingglass")
                .foregroundStyle(ColorTokens.secondaryText)
            TextField("Search conversations", text: $searchText)
                .textFieldStyle(.plain)
                .accessibilityLabel("Conversation search")
        }
        .padding(Spacing.xs)
        .liquidGlassToolbar()
        .padding(.horizontal, Spacing.md)
        .padding(.bottom, Spacing.xs)
    }

    private var list: some View {
        List {
            ForEach(filteredConversations, id: \.id) { conversation in
                row(for: conversation)
                    .listRowInsets(EdgeInsets())
                    .listRowBackground(Color.clear)
            }
        }
        .listStyle(.plain)
    }

    private func row(for conversation: Conversation) -> some View {
        Button {
            onSelect(conversation)
        } label: {
            VStack(alignment: .leading, spacing: Spacing.xxs) {
                HStack {
                    Text(conversation.title)
                        .font(Typography.heading)
                        .lineLimit(1)
                    if conversation.isFork {
                        Text("FORK")
                            .font(.system(size: 9, weight: .bold))
                            .padding(.horizontal, 4)
                            .padding(.vertical, 1)
                            .background(ColorTokens.warning.opacity(0.2), in: Capsule())
                            .foregroundStyle(ColorTokens.warning)
                    }
                    Spacer()
                }
                Text(conversation.lastActivityAt.formatted(.relative(presentation: .named)))
                    .font(Typography.caption)
                    .foregroundStyle(ColorTokens.tertiaryText)
            }
            .padding(Spacing.md)
            .liquidGlassPanel()
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: CornerRadius.standard)
                    .fill(selectedId.wrappedValue == conversation.id
                          ? Color.accentColor.opacity(0.12)
                          : Color.clear)
            )
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Conversation \(conversation.title)\(conversation.isFork ? ", forked" : "")")
        .accessibilityHint("Tap to open")
    }

    private var filteredConversations: [Conversation] {
        guard !searchText.isEmpty else { return conversations }
        return conversations.filter { $0.title.localizedCaseInsensitiveContains(searchText) }
    }
}
