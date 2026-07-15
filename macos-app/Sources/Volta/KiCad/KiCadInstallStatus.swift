//
//  KiCadInstallStatus.swift
//  Volta
//
//  Phase 163 — KiCad CLI Integration
//
//  The status the detector returns. Carries enough info for the onboarding
//  view to render a helpful message and for AppRootView to gate the main
//  workflow on `.ready` (APP-04 augmentation: app cannot start main
//  workflow without KiCad).
//
//  ponytail: enum-with-associated-values is the right sum type here.
//  No subclassing, no protocols, no factory — just three cases.
//

import Foundation

/// Result of probing the user's system for an external KiCad 10+ install.
///
/// Per PROJECT.md "Out of Scope (Locked Exclusions)": kicad-cli is NOT
/// bundled (GPLv3 blocks App Store). The app requires an external install
/// and gates the main workflow on `.ready`.
enum KiCadInstallStatus: Equatable, Sendable {
    /// No `kicad-cli` found in PATH, `/Applications/KiCad/kicad-cli`, or
    /// `/usr/local/bin/kicad-cli`. User needs to install KiCad 10+.
    case notInstalled

    /// `kicad-cli` exists but its version is older than 10.0 (e.g. KiCad 9.0).
    /// The associated string is the parsed version string (e.g. "9.0.2").
    case wrongVersion(found: String)

    /// KiCad 10+ is installed at `path` and reports `version`. App can
    /// safely invoke it for ERC/DRC/render/export.
    case ready(path: String, version: String)

    /// Minimum supported version. KiCad 10+ per PROJECT.md.
    static let minimumSupported = Version(major: 10, minor: 0, patch: 0)

    /// True only on `.ready` — the only state from which main workflow can start.
    var isReady: Bool {
        if case .ready = self { return true }
        return false
    }

    /// One-line human-readable description for logs and debug UIs.
    var debugDescription: String {
        switch self {
        case .notInstalled:
            return "KiCad CLI not found"
        case .wrongVersion(let v):
            return "KiCad CLI found but version \(v) is older than 10.0"
        case .ready(let path, let version):
            return "KiCad CLI ready at \(path) (version \(version))"
        }
    }
}

/// Parsed semantic version. KiCad version strings look like `10.0.3`.
///
/// ponytail: a tiny value type. Do not pull in a SemVer library for three ints.
struct Version: Equatable, Comparable, Sendable {
    let major: Int
    let minor: Int
    let patch: Int

    init(major: Int, minor: Int = 0, patch: Int = 0) {
        self.major = major
        self.minor = minor
        self.patch = patch
    }

    /// Parse a version string like "10.0.3", "10.0", or "10".
    /// Non-numeric components default to 0. Returns nil if the string
    /// has no leading integer at all.
    static func parse(_ string: String) -> Version? {
        let trimmed = string.trimmingCharacters(in: .whitespacesAndNewlines)
        // Tolerate a leading 'v' (some tools print "v10.0.3").
        let withoutV = trimmed.hasPrefix("v") ? String(trimmed.dropFirst()) : trimmed
        let parts = withoutV.split(separator: ".").prefix(3)
        var ints: [Int] = []
        for part in parts {
            // Stop at any non-digit suffix (e.g. "10.0.3+debug" → [10, 0, 3]).
            let numericPrefix = part.prefix { $0.isNumber }
            guard let n = Int(numericPrefix) else { break }
            ints.append(n)
        }
        guard !ints.isEmpty else { return nil }
        return Version(
            major: ints[0],
            minor: ints.count > 1 ? ints[1] : 0,
            patch: ints.count > 2 ? ints[2] : 0
        )
    }
}

extension Version {
    static func < (lhs: Version, rhs: Version) -> Bool {
        if lhs.major != rhs.major { return lhs.major < rhs.major }
        if lhs.minor != rhs.minor { return lhs.minor < rhs.minor }
        return lhs.patch < rhs.patch
    }
}
