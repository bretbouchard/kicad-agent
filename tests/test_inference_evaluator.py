"""Tests for end-to-end inference evaluation."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from kicad_agent.inference.best_of_n import ScoredChain


class TestEvaluationReport:
    """Tests for EvaluationReport dataclass."""

    def test_evaluation_report_frozen(self):
        """EvaluationReport is immutable (frozen dataclass)."""
        from kicad_agent.inference.evaluator import EvaluationReport

        report = EvaluationReport(
            n_test_files=1,
            avg_latency_s=1.0,
            avg_composite_score=0.7,
            avg_format_score=0.8,
            avg_quality_score=0.6,
            avg_accuracy_score=0.7,
            best_of_n_improvement=40.0,
            single_sample_mean=0.5,
            best_of_n_mean=0.7,
            per_file_results=({"file": "test.kicad_pcb", "score": 0.7},),
        )
        with pytest.raises(FrozenInstanceError):
            report.avg_latency_s = 2.0  # type: ignore[misc]

    def test_evaluation_report_to_text(self):
        """to_text produces readable summary with scores."""
        from kicad_agent.inference.evaluator import EvaluationReport

        report = EvaluationReport(
            n_test_files=3,
            avg_latency_s=2.5,
            avg_composite_score=0.75,
            avg_format_score=0.80,
            avg_quality_score=0.70,
            avg_accuracy_score=0.75,
            best_of_n_improvement=25.0,
            single_sample_mean=0.60,
            best_of_n_mean=0.75,
            per_file_results=(),
        )
        text = report.to_text()

        assert "3" in text  # n_test_files
        assert "0.75" in text  # avg_composite_score
        assert "25" in text  # best_of_n_improvement
        assert "0.60" in text  # single_sample_mean


class TestRunE2EEvaluation:
    """Tests for run_e2e_evaluation function."""

    def test_run_e2e_returns_report(self):
        """run_e2e_evaluation returns EvaluationReport with valid metrics."""
        from unittest.mock import patch

        from kicad_agent.inference.evaluator import run_e2e_evaluation

        single_chain = ScoredChain(
            chain_text="single chain",
            format_score=0.6,
            quality_score=0.5,
            accuracy_score=0.6,
            composite_score=0.567,
            generation_time_s=1.0,
        )
        best_chain = ScoredChain(
            chain_text="best chain",
            format_score=0.8,
            quality_score=0.7,
            accuracy_score=0.8,
            composite_score=0.767,
            generation_time_s=1.2,
        )

        with patch(
            "kicad_agent.inference.wrapper.InferenceWrapper.analyze"
        ) as mock_analyze, patch(
            "kicad_agent.inference.evaluator.Path.exists", return_value=True,
        ):
            # First call (single baseline), then second call (best-of-N)
            mock_analyze.side_effect = [single_chain, best_chain]

            report = run_e2e_evaluation(
                test_files=["test.kicad_pcb"],
                n_best=4,
            )

        assert report.n_test_files == 1
        assert report.avg_composite_score > 0
        assert report.per_file_results is not None
        assert len(report.per_file_results) == 1

    def test_run_e2e_computes_improvement(self):
        """best_of_n_improvement is percentage over single-sample baseline.

        Single-sample scores 0.5, best-of-N scores 0.7.
        Improvement = (0.7 - 0.5) / 0.5 * 100 = 40%
        """
        from unittest.mock import patch

        from kicad_agent.inference.evaluator import run_e2e_evaluation

        single_chain = ScoredChain(
            chain_text="single",
            format_score=0.5,
            quality_score=0.5,
            accuracy_score=0.5,
            composite_score=0.5,
            generation_time_s=1.0,
        )
        best_chain = ScoredChain(
            chain_text="best",
            format_score=0.7,
            quality_score=0.7,
            accuracy_score=0.7,
            composite_score=0.7,
            generation_time_s=1.5,
        )

        with patch(
            "kicad_agent.inference.wrapper.InferenceWrapper.analyze"
        ) as mock_analyze, patch(
            "kicad_agent.inference.evaluator.Path.exists", return_value=True,
        ):
            mock_analyze.side_effect = [single_chain, best_chain]

            report = run_e2e_evaluation(
                test_files=["board.kicad_pcb"],
                n_best=4,
            )

        assert report.single_sample_mean == pytest.approx(0.5, abs=0.01)
        assert report.best_of_n_mean == pytest.approx(0.7, abs=0.01)
        assert report.best_of_n_improvement == pytest.approx(40.0, abs=1.0)

    def test_run_e2e_empty_files(self):
        """Empty test_files returns report with n_test_files=0."""
        from kicad_agent.inference.evaluator import run_e2e_evaluation

        report = run_e2e_evaluation(test_files=[])

        assert report.n_test_files == 0
        assert report.avg_composite_score == 0.0
        assert report.avg_latency_s == 0.0
        assert report.best_of_n_improvement == 0.0
        assert report.per_file_results == ()
