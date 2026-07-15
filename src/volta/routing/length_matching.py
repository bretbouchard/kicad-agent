"""Sawtooth length matching engine for differential pair equalization.

Adds triangular sawtooth bumps along a path to increase its total length
by a target delta. Uses a measure-and-refine loop to converge on the
exact target. Bumps are perpendicular to the path direction at each
insertion point.

Each sawtooth bump replaces a straight segment of length ``2 * half_pitch``
with two diagonal legs forming a triangle. This adds less extra length per
bump than a U-shaped accordion at the same amplitude and pitch.

Results are immutable LengthMatchResult frozen dataclasses.

Usage:
    from volta.routing.length_matching import add_sawtooth_matching

    result = add_sawtooth_matching(path, target_delta_mm=5.0)
    print(f"Added {result.num_bumps} bumps, delta={result.achieved_delta_mm}")
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from volta.routing.geometry import (
    _direction_at,
    _interpolate_path,
    _path_length,
)


@dataclass(frozen=True)
class LengthMatchResult:
    """Immutable result of sawtooth length matching.

    Attributes:
        path: Path with sawtooth bumps inserted.
        target_delta_mm: Requested additional length in mm.
        achieved_delta_mm: Actual additional length added in mm.
        num_bumps: Number of sawtooth bumps inserted.
        valid: True if achieved_delta is close to target_delta.
    """

    path: tuple[tuple[float, float], ...]
    target_delta_mm: float
    achieved_delta_mm: float
    num_bumps: int
    valid: bool


def _sawtooth_extra_length(amplitude: float, half_pitch: float) -> float:
    """Compute the extra length added by a single sawtooth bump.

    Each bump replaces a straight segment of length ``2 * half_pitch``
    with two diagonal legs forming a triangle (start -> peak -> end).

    Args:
        amplitude: Perpendicular height of the triangle in mm.
        half_pitch: Half the bump width along the path in mm.

    Returns:
        Extra length added beyond the straight segment (always >= 0).
    """
    leg = math.hypot(half_pitch, amplitude)
    return 2 * leg - 2 * half_pitch


def _generate_sawtooth_bumps(
    path: tuple[tuple[float, float], ...],
    num_bumps: int,
    amplitude: float,
    bump_pitch: float,
    margin: float,
    total_len: float,
) -> tuple[tuple[float, float], ...]:
    """Generate sawtooth bumps along a path at given amplitude.

    Each bump is a triangle with 3 points: start, peak, end. The peak
    is offset perpendicular to the path direction at the bump center.

    Args:
        path: Original path waypoints.
        num_bumps: Number of bumps to insert.
        amplitude: Perpendicular height of each bump.
        bump_pitch: Distance between bump centers along the path.
        margin: Start/end margin along the path.
        total_len: Total arc length of the path.

    Returns:
        New path tuple with sawtooth bumps inserted.
    """
    if amplitude < 1e-9 or num_bumps < 1:
        return path

    half_pitch = bump_pitch * 0.5
    usable_length = total_len - 2.0 * margin
    spacing_between = usable_length / num_bumps
    bump_positions = [
        margin + spacing_between * (i + 0.5) for i in range(num_bumps)
    ]

    new_points: list[tuple[float, float]] = [path[0]]

    for bp in bump_positions:
        # Find center point and direction at bump center.
        center_pts = _interpolate_path(path, [bp])
        center = center_pts[0]
        ux, uy, px, py = _direction_at(path, bp)

        # Start and end of the bump span along the path.
        start_pts = _interpolate_path(path, [max(0.0, bp - half_pitch)])
        start_pt = start_pts[0]

        end_pts = _interpolate_path(path, [min(total_len, bp + half_pitch)])
        end_pt = end_pts[0]

        # Triangle peak: center point offset perpendicular.
        peak_x = center[0] + px * amplitude
        peak_y = center[1] + py * amplitude

        # 3 points per bump: start, peak, end.
        new_points.append((round(start_pt[0], 6), round(start_pt[1], 6)))
        new_points.append((round(peak_x, 6), round(peak_y, 6)))
        new_points.append((round(end_pt[0], 6), round(end_pt[1], 6)))

    new_points.append(path[-1])
    return tuple(new_points)


def add_sawtooth_matching(
    path: tuple[tuple[float, float], ...],
    target_delta_mm: float,
    spacing_mm: float = 1.0,
    max_detour_ratio: float = 3.0,
) -> LengthMatchResult:
    """Add sawtooth bumps to a path to increase its length by a target delta.

    Uses a measure-and-refine loop: generate bumps at an estimated
    amplitude, measure the actual length change, and adjust amplitude
    proportionally. Up to 10 refinement iterations ensure convergence.

    Args:
        path: Original path as ordered tuple of (x, y) waypoints.
        target_delta_mm: Additional length to add in mm. If 0 or negative,
            returns the original path unchanged.
        spacing_mm: Minimum bump spacing in mm. Defaults to 1.0mm.
        max_detour_ratio: Maximum amplitude as a multiple of half_pitch.
            Caps bump height for manufacturing safety. Defaults to 3.0.

    Returns:
        LengthMatchResult with bumped path and convergence information.
    """
    # Edge case: no delta requested or degenerate path.
    if target_delta_mm <= 0 or len(path) < 2:
        return LengthMatchResult(
            path=path,
            target_delta_mm=target_delta_mm,
            achieved_delta_mm=0.0,
            num_bumps=0,
            valid=False,
        )

    total_len = _path_length(path)
    if total_len < 1e-9:
        return LengthMatchResult(
            path=path,
            target_delta_mm=target_delta_mm,
            achieved_delta_mm=0.0,
            num_bumps=0,
            valid=False,
        )

    # Bump geometry.
    bump_pitch = max(spacing_mm, 0.5)
    half_pitch = bump_pitch * 0.5
    max_amplitude = half_pitch * max_detour_ratio  # Per threat model T-36-06.

    # Margin at each end of the path.
    margin = bump_pitch * 0.5
    usable_length = total_len - 2.0 * margin
    if usable_length < bump_pitch:
        # Path too short for even one bump.
        return LengthMatchResult(
            path=path,
            target_delta_mm=target_delta_mm,
            achieved_delta_mm=0.0,
            num_bumps=0,
            valid=False,
        )

    num_bumps = int(usable_length / bump_pitch)
    num_bumps = min(num_bumps, 50)  # Safety cap.
    if num_bumps < 1:
        return LengthMatchResult(
            path=path,
            target_delta_mm=target_delta_mm,
            achieved_delta_mm=0.0,
            num_bumps=0,
            valid=False,
        )

    # Estimate initial amplitude: divide target delta equally among bumps.
    extra_per_bump = target_delta_mm / num_bumps
    amplitude = _amplitude_for_extra(extra_per_bump, half_pitch)
    amplitude = min(amplitude, max_amplitude)

    # Add small overshoot so proportional scaling converges from above.
    effective_target = target_delta_mm * 1.01

    # Measure-and-refine loop (per threat model T-36-05: max 10 iterations).
    for _ in range(10):
        bumped = _generate_sawtooth_bumps(
            path, num_bumps, amplitude, bump_pitch, margin, total_len
        )
        actual_delta = _path_length(bumped) - total_len

        if actual_delta < effective_target - 0.01:
            # Not enough -- increase amplitude.
            if amplitude >= max_amplitude:
                break
            if actual_delta > 0:
                amplitude = min(
                    max_amplitude,
                    amplitude * (effective_target / actual_delta),
                )
            else:
                amplitude = max_amplitude
        elif actual_delta > effective_target + 0.01:
            # Too much -- reduce amplitude.
            if actual_delta > 0:
                amplitude = max(
                    0.0,
                    amplitude * (effective_target / actual_delta),
                )
        else:
            # Close enough.
            break

    # Final generation at refined amplitude.
    final_path = _generate_sawtooth_bumps(
        path, num_bumps, amplitude, bump_pitch, margin, total_len
    )
    achieved_delta = _path_length(final_path) - total_len

    # Valid if achieved is close to target (within 10% or 0.5mm).
    tolerance = max(0.5, target_delta_mm * 0.1)
    is_valid = abs(achieved_delta - target_delta_mm) <= tolerance

    return LengthMatchResult(
        path=final_path,
        target_delta_mm=target_delta_mm,
        achieved_delta_mm=round(achieved_delta, 4),
        num_bumps=num_bumps,
        valid=is_valid,
    )


def _amplitude_for_extra(extra_per_bump: float, half_pitch: float) -> float:
    """Estimate amplitude needed for a given extra length per bump.

    Solves the equation: extra = 2 * hypot(half_pitch, amp) - 2 * half_pitch
    for amplitude.

    Args:
        extra_per_bump: Desired extra length per bump in mm.
        half_pitch: Half the bump width along the path in mm.

    Returns:
        Estimated amplitude in mm.
    """
    if extra_per_bump <= 0:
        return 0.0
    # extra = 2 * sqrt(hp^2 + a^2) - 2*hp
    # extra + 2*hp = 2 * sqrt(hp^2 + a^2)
    # (extra + 2*hp) / 2 = sqrt(hp^2 + a^2)
    # ((extra + 2*hp) / 2)^2 = hp^2 + a^2
    # a = sqrt(((extra + 2*hp) / 2)^2 - hp^2)
    target_leg = (extra_per_bump + 2 * half_pitch) / 2
    under_sqrt = target_leg ** 2 - half_pitch ** 2
    if under_sqrt <= 0:
        return 0.0
    return math.sqrt(under_sqrt)
