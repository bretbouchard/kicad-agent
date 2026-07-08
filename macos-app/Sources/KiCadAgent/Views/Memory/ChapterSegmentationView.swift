//
//  ChapterSegmentationView.swift
//  KiCadAgent
//
//  Phase 179 — Decision Timeline UI
//
//  LLM-suggested chapter editor with 10-chapter cap. Run-on conversations
//  can be segmented for readability.
//
//  TT-05: chapter segmentation.
//

import SwiftUI

/// Editor for chapter boundaries (max 10).
struct ChapterSegmentationView: View {
    @Binding var chapters: [TimelineChapter]
    let onRegenerate: () -> Void

    @State private var newChapterTitle: String = ""

    private let maxChapters = 10

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            header
            chapterList
            addChapterRow
            actionRow
        }
        .padding(Spacing.lg)
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Chapter segmentation")
        .accessibilityHint("Group timeline entries into chapters (max 10)")
    }

    private var header: some View {
        HStack {
            VStack(alignment: .leading, spacing: Spacing.xxs) {
                Text("Chapters")
                    .font(Typography.title)
                    .accessibilityAddTraits(.isHeader)
                Text("\(chapters.count) / \(maxChapters) used")
                    .font(Typography.caption)
                    .foregroundStyle(chapterCountColor)
            }
            Spacer()
            Button("Regenerate Suggestions", action: onRegenerate)
                .buttonStyle(.bordered)
                .disabled(chapters.count >= maxChapters)
                .accessibilityHint("Asks LLM to suggest chapter boundaries based on content")
        }
    }

    private var chapterList: some View {
        List {
            ForEach(chapters) { chapter in
                ChapterRow(chapter: chapter, onDelete: { deleteChapter(chapter) })
            }
        }
        .listStyle(.plain)
        .frame(minHeight: 200)
    }

    private var addChapterRow: some View {
        HStack {
            TextField("New chapter title", text: $newChapterTitle)
                .textFieldStyle(.roundedBorder)
                .accessibilityLabel("New chapter title")
            Button("Add") {
                addChapter()
            }
            .buttonStyle(.bordered)
            .disabled(newChapterTitle.isEmpty || chapters.count >= maxChapters)
        }
    }

    private var actionRow: some View {
        HStack {
            Spacer()
            Text("Chapters cap enforced (T-179 spam prevention)")
                .font(Typography.caption)
                .foregroundStyle(ColorTokens.tertiaryText)
        }
    }

    private var chapterCountColor: Color {
        chapters.count >= maxChapters ? ColorTokens.destructive : ColorTokens.secondaryText
    }

    private func addChapter() {
        guard chapters.count < maxChapters, !newChapterTitle.isEmpty else { return }
        let lastIndex = chapters.last?.endIndex ?? -1
        chapters.append(TimelineChapter(
            id: UUID(),
            title: newChapterTitle,
            startIndex: lastIndex + 1,
            endIndex: lastIndex + 10 // arbitrary initial span
        ))
        newChapterTitle = ""
    }

    private func deleteChapter(_ chapter: TimelineChapter) {
        chapters.removeAll { $0.id == chapter.id }
    }
}

private struct ChapterRow: View {
    let chapter: TimelineChapter
    let onDelete: () -> Void

    var body: some View {
        HStack {
            VStack(alignment: .leading) {
                Text(chapter.title)
                    .font(Typography.heading)
                Text("Entries \(chapter.startIndex + 1) – \(chapter.endIndex + 1)")
                    .font(Typography.caption)
                    .foregroundStyle(ColorTokens.tertiaryText)
            }
            Spacer()
            Button(role: .destructive, action: onDelete) {
                Image(systemName: "trash")
            }
            .buttonStyle(.borderless)
            .accessibilityLabel("Delete chapter \(chapter.title)")
        }
        .padding(.vertical, Spacing.xxs)
    }
}
