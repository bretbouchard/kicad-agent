//
//  LocalModelStatus.swift
//  Volta
//
//  Phase 245 — Local model lifecycle state enum
//

import Foundation

/// Lifecycle state of the local Volta v2 model + adapter.
enum LocalModelStatus: Equatable {
    case notDownloaded
    case downloading(progress: Double)
    case downloaded
    case downloadFailed(reason: DownloadFailureReason)
    case adapterNotPublished  // 404 on the HF repo
}

enum DownloadFailureReason: Equatable {
    case network(String)      // timeout, DNS, etc.
    case httpStatus(Int)      // non-404 server error
    case fileMissing          // repo exists but adapter_model.safetensors not in it
    case corruptFile(String)  // checksum mismatch or partial download

    var userFacingMessage: String {
        switch self {
        case .network(let s): return "Couldn't reach HuggingFace: \(s)"
        case .httpStatus(let code): return "Server returned HTTP \(code). Try again later."
        case .fileMissing: return "Volta v2 adapter not found in the published repo. Please file a bug."
        case .corruptFile(let s): return "Downloaded file failed verification: \(s)"
        }
    }
}