//
//  ModelDownloadView.swift
//  KiCadAgent
//
//  Phase 210 — Gemma 4 12B Model Download UI
//
//  Shown on first launch (or when no MLX model is detected). Downloads
//  the base Gemma 4 12B model + Volta PCB LoRA adapter (~8 GB total)
//  to the sandbox container.
//

import SwiftUI
import OSLog

/// State machine for the model download flow.
enum ModelDownloadState: Equatable {
    case notStarted
    case fetchingManifest
    case downloading(fileName: String, progress: Double)
    case verifying(fileName: String)
    case completed
    case failed(message: String)
}

/// SwiftUI view for downloading the Volta PCB intelligence model.
/// Shows VRAM check, download progress, and skip option.
struct ModelDownloadView: View {
    @State private var state: ModelDownloadState = .notStarted
    @State private var downloadTask: Task<Void, Never>?
    @Environment(\.dismiss) private var dismiss

    /// Called when download completes successfully.
    var onComplete: (() -> Void)?

    /// Metal VRAM in GB for the UI display.
    private var vramGB: UInt64 {
        MTLCreateSystemDefaultDevice()?.recommendedMaxWorkingSetSize ?? 0
    }

    private var hasEnoughVRAM: Bool {
        vramGB >= 16 * 1024 * 1024 * 1024  // 16 GB recommended for 12B
    }

    private var meetsMinimum: Bool {
        vramGB >= 3 * 1024 * 1024 * 1024  // 3 GB hard minimum
    }

    var body: some View {
        VStack(spacing: 24) {
            // Icon
            Image(systemName: "cpu")
                .font(.system(size: 56))
                .foregroundStyle(.tint)
                .symbolEffect(.pulse)

            // Title
            VStack(spacing: 8) {
                Text("Download Volta PCB Intelligence")
                    .font(.title2.bold())

                Text("Gemma 4 12B with Volta PCB LoRA adapter. Generates SKiDL circuits from natural language.")
                    .font(.body)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
            }

            // VRAM check
            VStack(spacing: 4) {
                HStack(spacing: 6) {
                    Image(systemName: meetsMinimum ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                        .foregroundStyle(meetsMinimum ? .green : .orange)
                    Text("GPU Memory: \(vramGB / 1024 / 1024) GB")
                        .font(.callout)
                }
                if !hasEnoughVRAM && meetsMinimum {
                    Text("16 GB recommended for best performance. Download will work but may be slow.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                if !meetsMinimum {
                    Text("Insufficient GPU memory. A Mac with at least 16 GB unified memory is recommended.")
                        .font(.caption)
                        .foregroundStyle(.orange)
                }
            }

            // Download size
            HStack(spacing: 6) {
                Image(systemName: "arrow.down.circle")
                Text("~8 GB download")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }

            // Progress
            if state != .notStarted && state != .completed {
                VStack(spacing: 8) {
                    switch state {
                    case .fetchingManifest:
                        ProgressView("Fetching model manifest...")
                    case .downloading(let file, let progress):
                        VStack(spacing: 6) {
                            ProgressView(value: progress) {
                                Text(file)
                                    .font(.caption)
                                    .lineLimit(1)
                                    .truncationMode(.middle)
                            }
                            Text("\(Int(progress * 100))%")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    case .verifying(let file):
                        ProgressView("Verifying \(file)...")
                    case .failed(let msg):
                        VStack(spacing: 6) {
                            Image(systemName: "xmark.circle.fill")
                                .foregroundStyle(.red)
                            Text(msg)
                                .font(.caption)
                                .foregroundStyle(.red)
                        }
                    default:
                        EmptyView()
                    }
                }
                .padding()
            }

            // Buttons
            HStack(spacing: 16) {
                Button("Skip for now") {
                    dismiss()
                }
                .buttonStyle(.bordered)

                Button("Download") {
                    startDownload()
                }
                .buttonStyle(.borderedProminent)
                .disabled(state == .downloading(fileName: "", progress: 0) || state == .fetchingManifest)
                .disabled(!meetsMinimum)
            }
        }
        .padding(32)
        .frame(maxWidth: 480)
    }

    private func startDownload() {
        downloadTask?.cancel()
        downloadTask = Task {
            let downloader = ModelDownloader()
            for await progress in downloader.download() {
                await MainActor.run {
                    switch progress {
                    case .fetchingManifest:
                        state = .fetchingManifest
                    case .downloadingFile(let name, let p):
                        state = .downloading(fileName: name, progress: p)
                    case .verifyingFile(let name, let success):
                        state = .verifying(fileName: name)
                    case .completed:
                        state = .completed
                        Logger.appShell.info("Model download complete")
                        onComplete?()
                    case .failed(let error):
                        state = .failed(message: error.localizedDescription)
                    }
                }
            }
        }
    }
}
