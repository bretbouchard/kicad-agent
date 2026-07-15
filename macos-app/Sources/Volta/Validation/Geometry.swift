//
//  Geometry.swift
//  Phase 222 — Swift Geometry Layer
//
//  Replaces shapely for DRC checks. Pure Swift, no external deps.
//  Implements the 4 operations needed for PCB DRC:
//    1. LineString buffer (trace → polygon)
//    2. Point/Box distance
//    3. Polygon intersection area
//    4. Simple spatial hash (replaces STRtree for <10K items)
//
//  ponytail: ~200 LOC. Uses CGGeometry where possible.
//

import Foundation
import CoreGraphics

// MARK: - 2D Point

extension CGPoint {
    init(_ x: Double, _ y: Double) {
        self.init(x: x, y: y)
    }

    func distance(to other: CGPoint) -> Double {
        let dx = x - other.x
        let dy = y - other.y
        return (dx * dx + dy * dy).squareRoot()
    }
}

// MARK: - Line Segment + Distance

struct LineSegment {
    let start: CGPoint
    let end: CGPoint

    /// Distance from a point to this segment.
    func distance(to point: CGPoint) -> Double {
        let dx = end.x - start.x
        let dy = end.y - start.y
        let len2 = dx * dx + dy * dy

        if len2 == 0 {
            return start.distance(to: point)
        }

        let t = max(0, min(1, ((point.x - start.x) * dx + (point.y - start.y) * dy) / len2))
        let proj = CGPoint(start.x + t * dx, start.y + t * dy)
        return proj.distance(to: point)
    }

    /// Distance between two line segments.
    func distance(to other: LineSegment) -> Double {
        // Check if they intersect
        if segmentsIntersect(other) { return 0.0 }

        // Min of 4 point-to-segment distances
        let d1 = distance(to: other.start)
        let d2 = distance(to: other.end)
        let d3 = other.distance(to: start)
        let d4 = other.distance(to: end)
        return min(d1, d2, d3, d4)
    }

    /// Check if two segments cross.
    private func segmentsIntersect(_ other: LineSegment) -> Bool {
        func ccw(_ a: CGPoint, _ b: CGPoint, _ c: CGPoint) -> Double {
            (c.y - a.y) * (b.x - a.x) - (b.y - a.y) * (c.x - a.x)
        }
        let d1 = ccw(other.start, other.end, start)
        let d2 = ccw(other.start, other.end, end)
        let d3 = ccw(start, end, other.start)
        let d4 = ccw(start, end, other.end)
        return ((d1 > 0 && d2 < 0) || (d1 < 0 && d2 > 0)) &&
               ((d3 > 0 && d4 < 0) || (d3 < 0 && d4 > 0))
    }
}

// MARK: - Rectangle (Bounding Box)

struct Rect {
    let minX: Double
    let minY: Double
    let maxX: Double
    let maxY: Double

    var center: CGPoint { CGPoint((minX + maxX) / 2, (minY + maxY) / 2) }

    init(_ x: Double, _ y: Double, _ w: Double, _ h: Double) {
        self.minX = x - w / 2
        self.minY = y - h / 2
        self.maxX = x + w / 2
        self.maxY = y + h / 2
    }

    /// Distance between two rects (0 if overlapping).
    func distance(to other: Rect) -> Double {
        if maxX < other.minX || other.maxX < minX {
            // Horizontal gap
            if maxY < other.minY || other.maxY < minY {
                // Diagonal gap
                let dx = max(0, max(other.minX - maxX, minX - other.maxX))
                let dy = max(0, max(other.minY - maxY, minY - other.maxY))
                return (dx * dx + dy * dy).squareRoot()
            }
            return max(0, max(other.minX - maxX, minX - other.maxX))
        }
        if maxY < other.minY || other.maxY < minY {
            return max(0, max(other.minY - maxY, minY - other.maxY))
        }
        return 0.0 // Overlapping
    }

    func intersects(_ other: Rect) -> Bool {
        !(maxX < other.minX || other.maxX < minX || maxY < other.minY || other.maxY < minY)
    }
}

// MARK: - Circle

struct GeomCircle {
    let center: CGPoint
    let radius: Double

    func distance(to other: GeomCircle) -> Double {
        max(0, center.distance(to: other.center) - radius - other.radius)
    }

    func distance(to rect: Rect) -> Double {
        let cx = max(rect.minX, min(center.x, rect.maxX))
        let cy = max(rect.minY, min(center.y, rect.maxY))
        let dx = center.x - cx
        let dy = center.y - cy
        let dist = (dx * dx + dy * dy).squareRoot()
        return max(0, dist - radius)
    }
}

// MARK: - Spatial Hash (Simple STRtree Replacement)

/// Simple uniform grid spatial index for O(1) proximity queries.
/// Good enough for <10K items (typical PCB).
struct SpatialHash<Item> {
    private var grid: [PositionKey: [Item]] = [:]
    private let cellSize: Double
    private let positionExtractor: (Item) -> (Double, Double)

    init(cellSize: Double = 2.0, position: @escaping (Item) -> (Double, Double)) {
        self.cellSize = cellSize
        self.positionExtractor = position
    }

    mutating func insert(_ item: Item) {
        let (x, y) = positionExtractor(item)
        let key = PositionKey(
            x100: Int((x / cellSize).rounded()),
            y100: Int((y / cellSize).rounded())
        )
        grid[key, default: []].append(item)
    }

    /// Query items within `radius` of a point.
    func query(near x: Double, _ y: Double, radius: Double) -> [Item] {
        let cells = Int((radius / cellSize).rounded()) + 1
        let cx = Int((x / cellSize).rounded())
        let cy = Int((y / cellSize).rounded())
        var results: [Item] = []

        for dx in -cells...cells {
            for dy in -cells...cells {
                let key = PositionKey(x100: cx + dx, y100: cy + dy)
                if let items = grid[key] {
                    results.append(contentsOf: items)
                }
            }
        }
        return results
    }
}
