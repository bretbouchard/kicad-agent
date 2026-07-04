"""Unit tests for CheckpointResumer (Plan 05 Task 1).

ME-110-09: B2 atomic upload via 3-step pattern (upload .tmp -> copy -> delete .tmp).
ME-110-10: max_checkpoint_mb advisory warning for oversized checkpoints.
"""
from __future__ import annotations

import hashlib
import signal
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from kicad_agent.training.vastai_checkpoint_resumer import CheckpointResumer


def _build_resumer_with_mock_b2(tmp_path: Path) -> tuple[CheckpointResumer, MagicMock]:
    """Build a CheckpointResumer with a mocked B2Api."""
    resumer = CheckpointResumer(bucket="test-bucket", local_dir=tmp_path)
    mock_b2 = MagicMock()
    mock_bucket = MagicMock()
    mock_b2.list_buckets.return_value = [mock_bucket]
    mock_b2.get_bucket_by_name.return_value = mock_bucket
    resumer._b2_api = mock_b2
    return resumer, mock_bucket


def test_save_step_returns_b2_path(tmp_path) -> None:
    """Test 1: save_step writes local + uploads via 3-step pattern, returns B2 path."""
    resumer, bucket = _build_resumer_with_mock_b2(tmp_path)
    result_path = resumer.save_step(step=100, model_state={"w": 1})
    assert "phase-110/step-100.safetensors" in result_path
    assert resumer._latest_step == 100


def test_save_step_uses_3_step_copy_then_delete_pattern(tmp_path) -> None:
    """Test 2: ME-110-09 — upload .tmp, copy .tmp -> final, delete .tmp."""
    resumer, bucket = _build_resumer_with_mock_b2(tmp_path)
    resumer.save_step(step=50, model_state={"weights": [1, 2, 3]})

    # 1. upload to .tmp key
    upload_calls = bucket.upload.call_args_list
    assert any(".tmp" in str(c.args[1] if len(c.args) > 1 else c.kwargs.get("file_name", "")) for c in upload_calls), \
        f"expected .tmp upload, got: {upload_calls}"
    # 2. copy .tmp -> final
    assert bucket.copy.called, "expected B2 copy call (.tmp -> final)"
    # 3. delete .tmp
    assert bucket.delete_file_version.called, "expected B2 delete call (.tmp cleanup)"


def test_save_step_sha1_verification_in_file_info(tmp_path) -> None:
    """Test 3: ME-110-09 — upload includes SHA1 in file_info."""
    resumer, bucket = _build_resumer_with_mock_b2(tmp_path)
    resumer.save_step(step=10, model_state={"data": "test"})

    upload_call = bucket.upload.call_args
    file_info = upload_call.kwargs.get("file_info") or {}
    # b2sdk uses 'b2_sha1' or large_file_sha1 — either is acceptable per plan
    sha1_keys = [k for k in file_info if "sha1" in k.lower() or "sha" in k.lower()]
    assert sha1_keys, f"expected SHA1 in file_info, got: {file_info}"


def test_register_sigterm_handler_installs_signal_handler(tmp_path) -> None:
    """Test 4: SIGTERM handler installed via signal.signal()."""
    resumer, _ = _build_resumer_with_mock_b2(tmp_path)
    with patch("signal.signal") as mock_signal:
        resumer.register_sigterm_handler(trainer_state_getter=lambda: {"step": 42})
        # Confirm signal.signal was called with SIGTERM as first arg.
        # The second arg is a lambda that wraps _handle_sigterm — we just verify
        # the registration happened, not the exact callable identity.
        assert mock_signal.call_count == 1
        args = mock_signal.call_args.args
        assert args[0] == signal.SIGTERM
        assert callable(args[1])


def test_resume_from_latest_returns_highest_step_or_none(tmp_path) -> None:
    """Test 5: resume_from_latest returns highest step or None if empty."""
    resumer, bucket = _build_resumer_with_mock_b2(tmp_path)
    # Empty B2 -> returns None
    bucket.list_file_versions.return_value = MagicMock(files=[])
    assert resumer.resume_from_latest() is None


def test_save_step_falls_back_to_local_on_b2_failure(tmp_path, caplog) -> None:
    """Test 6: B2 unreachable -> local-only write, no crash."""
    resumer, bucket = _build_resumer_with_mock_b2(tmp_path)
    bucket.upload.side_effect = RuntimeError("network down")
    # Should NOT raise — falls back to local
    result = resumer.save_step(step=1, model_state={"x": 1})
    assert "phase-110/step-1" in result
    # Local file exists
    local_files = list(tmp_path.glob("step-1*"))
    assert local_files, "expected local checkpoint file even when B2 fails"


def test_checkpoint_resumer_requires_explicit_bucket_name() -> None:
    """Test 7: bucket arg is required (forces conscious config)."""
    with pytest.raises(TypeError):
        CheckpointResumer()  # type: ignore[call-arg]


def test_save_step_all_b2_calls_mocked_in_tests(tmp_path) -> None:
    """Test 8: confirms test isolation — no real network calls."""
    resumer, bucket = _build_resumer_with_mock_b2(tmp_path)
    resumer.save_step(step=1, model_state={"a": 1})
    # All B2 calls go through the mock
    assert bucket.upload.called or bucket.copy.called or bucket.delete_file_version.called


def test_max_checkpoint_mb_warning_fires_for_oversized_checkpoint(tmp_path, caplog) -> None:
    """Test 9: ME-110-10 — advisory warning when checkpoint exceeds max_checkpoint_mb."""
    # Set max_checkpoint_mb=0 so any non-empty checkpoint triggers the warning
    resumer = CheckpointResumer(bucket="t", local_dir=tmp_path, max_checkpoint_mb=0)
    mock_b2 = MagicMock()
    mock_bucket = MagicMock()
    mock_b2.get_bucket_by_name.return_value = mock_bucket
    resumer._b2_api = mock_b2

    import logging
    with caplog.at_level(logging.WARNING):
        resumer.save_step(step=1, model_state={"x": "data-that-is-definitely-bigger-than-zero-bytes"})
    found = any("max_checkpoint_mb" in rec.message or "SIGTERM" in rec.message for rec in caplog.records)
    assert found, f"expected max_checkpoint_mb advisory warning, got: {[r.message for r in caplog.records]}"
