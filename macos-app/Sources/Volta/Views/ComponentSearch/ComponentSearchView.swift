//
//  ComponentSearchView.swift
//  Volta
//
//  Phase 1 / Task 6 — SwiftUI Search Interface
//
//  Search interface for the multi-source component engine. Delegates to
//  MergeEngine for parallel provider queries and MPN-deduped results.
//

import SwiftUI
import OSLog
import VoltaPCBCore

/// Search interface for components across all registered providers.
struct ComponentSearchView: View {
    @State private var keyword = ""
    @State private var results: [UnifiedComponent] = []
    @State private var isSearching = false
    @State private var selectedComponent: UnifiedComponent?
    @State private var errorMessage: String?

    private let mergeEngine: MergeEngine

    init(mergeEngine: MergeEngine) {
        self.mergeEngine = mergeEngine
    }

    var body: some View {
        VStack(spacing: 0) {
            // Search bar
            HStack {
                Image(systemName: "magnifyingglass")
                    .foregroundStyle(.secondary)
                TextField("Search part number (e.g., STM32F411)", text: $keyword)
                    .textFieldStyle(.plain)
                    .onSubmit { performSearch() }
                if !keyword.isEmpty {
                    Button { keyword = ""; results = [] } label: {
                        Image(systemName: "xmark.circle.fill")
                            .foregroundStyle(.secondary)
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(10)
            .background(.regularMaterial)
            .clipShape(RoundedRectangle(cornerRadius: 10))
            .padding()

            // Status row
            if isSearching {
                HStack {
                    ProgressView().scaleEffect(0.8)
                    Text("Searching providers…")
                        .foregroundStyle(.secondary)
                }
                .padding(.bottom, 8)
            }

            if let errorMessage {
                Label(errorMessage, systemImage: "exclamationmark.triangle")
                    .foregroundStyle(.orange)
                    .padding(.bottom, 8)
            }

            // Results list
            List(results, id: \.id, selection: $selectedComponent) { component in
                ComponentResultRow(component: component)
                    .tag(component)
            }
            .listStyle(.inset)
        }
        .navigationTitle("Components")
        .frame(minWidth: 400, minHeight: 500)
    }

    private func performSearch() {
        guard !keyword.trimmingCharacters(in: .whitespaces).isEmpty else { return }
        isSearching = true
        errorMessage = nil

        Task {
            let searchResults = await mergeEngine.search(keyword: keyword)
            await MainActor.run {
                results = searchResults
                isSearching = false
                if searchResults.isEmpty {
                    errorMessage = "No results found for \"\(keyword)\""
                }
            }
        }
    }
}
