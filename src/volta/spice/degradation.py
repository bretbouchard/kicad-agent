"""Phase 158: SPICE degradation scorer.

Computes pre-route vs post-route degradation — a physical reward signal
for AI training (Phase 159 TRAIN-04). Catches parasitic-induced failures
that geometry-only RES scores cannot detect.
"""
from __future__ import annotations

from volta.spice.types import DegradationReport, SimulationResult, AnalysisType


def compute_degradation(
    pre_route: SimulationResult,
    post_route: SimulationResult,
) -> DegradationReport:
    """Compute the degradation between pre-route and post-route simulation.

    Args:
        pre_route: Simulation result before routing (ideal).
        post_route: Simulation result after routing (with parasitics).

    Returns:
        DegradationReport with deltas and overall score.
    """
    gain_delta = 0.0
    bw_delta_pct = 0.0
    noise_delta = 0.0
    thd_delta = 0.0

    # AC analysis degradation.
    pre_ac = pre_route.get_analysis(AnalysisType.AC)
    post_ac = post_route.get_analysis(AnalysisType.AC)
    if pre_ac and post_ac:
        if pre_ac.gain_db is not None and post_ac.gain_db is not None:
            gain_delta = post_ac.gain_db - pre_ac.gain_db
        if pre_ac.bandwidth_hz and post_ac.bandwidth_hz:
            bw_delta_pct = (
                (post_ac.bandwidth_hz - pre_ac.bandwidth_hz) / pre_ac.bandwidth_hz * 100
            )

    # Noise analysis degradation.
    pre_noise = pre_route.get_analysis(AnalysisType.NOISE)
    post_noise = post_route.get_analysis(AnalysisType.NOISE)
    if pre_noise and post_noise:
        if pre_noise.noise_floor_v_sqrt_hz and post_noise.noise_floor_v_sqrt_hz:
            import math
            if pre_noise.noise_floor_v_sqrt_hz > 0:
                noise_delta = 20 * math.log10(
                    post_noise.noise_floor_v_sqrt_hz / pre_noise.noise_floor_v_sqrt_hz
                )

    # Compute overall score (1.0 = no degradation, 0.0 = severe).
    score = 1.0
    score -= max(0, -gain_delta) * 0.1        # -0.1 per dB of gain loss
    score -= max(0, -bw_delta_pct) * 0.005    # -0.005 per % BW loss
    score -= max(0, noise_delta) * 0.05       # -0.05 per dB noise increase
    score = max(0.0, min(1.0, score))

    return DegradationReport(
        gain_delta_db=gain_delta,
        bandwidth_delta_pct=bw_delta_pct,
        noise_delta_db=noise_delta,
        thd_delta_pct=thd_delta,
        sim_score=score,
    )
