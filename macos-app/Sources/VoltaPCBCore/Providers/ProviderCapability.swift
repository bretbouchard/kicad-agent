//
//  ProviderCapability.swift
//  VoltaPCBCore
//
//  Phase 1 / Task 0 — VoltaPCBCore Foundation
//
//  Capabilities a provider can declare. Drives UI filtering ("show only
//  providers with pricing") and merge-engine priority ("prefer providers
//  that have first-party specifications over aggregators").
//
//  ponytail: String-raw enum so capability sets serialize cleanly to JSON
//  for cache persistence and provider manifests.
//

import Foundation

/// Capabilities a provider can declare. Used for UI filtering and merge priority.
public enum ProviderCapability: String, Sendable, CaseIterable {
    case pricing
    case stock
    case specifications
    case datasheets
    case footprints
    case symbols
    case models3D
    case assemblyData
    case offlineCache
}
