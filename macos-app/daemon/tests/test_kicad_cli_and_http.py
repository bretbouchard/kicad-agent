"""
test_kicad_cli_and_http.py — Phase 163 handler tests.

Coverage:
    kicad_cli_check
        - .ready path (mocked which + version)
        - .wrong_version path (KiCad 9.x detected)
        - .not_installed path (no kicad-cli anywhere)
        - version parsing edge cases (labeled output, partial, garbage)
    external_http_status
        - default state (disabled, no token, no failures)
        - after enabling
    external_http_regenerate_token
        - returns base64url token of expected length
        - resets failed-auth counter
        - generates different tokens across calls
    external_http_set_enabled
        - happy path toggle on/off
        - auto-generates token on enable
        - rejects non-bool
        - rejects missing field
    DAEM-08 auto-revoke
        - 9 failures: no revoke
        - 10 failures: revoke + disable + new token
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from handlers import (
    HandlerContext,
    HANDLERS,
    kicad_cli_check,
    external_http_status,
    external_http_regenerate_token,
    external_http_set_enabled,
    get_handler,
    registered_methods,
    KICAD_CANDIDATE_PATHS,
    KICAD_MINIMUM_VERSION,
    _parse_version,
    _split_version,
)
from protocol import RpcError, INVALID_PARAMS


# =============================================================================
# Fixtures
# =============================================================================

class _FakeAudit:
    """Captures log_event calls for assertions."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def log_event(self, event: str, **fields: Any) -> None:
        self.events.append((event, dict(fields)))

    def log_rpc(self, method: str, **fields: Any) -> None:
        pass


@pytest.fixture
def ctx() -> HandlerContext:
    return HandlerContext(executor_factory=lambda: None, audit=_FakeAudit())


@pytest.fixture
def ctx_no_audit() -> HandlerContext:
    return HandlerContext(executor_factory=lambda: None, audit=None)


# =============================================================================
# kicad_cli_check
# =============================================================================

class TestKicadCliCheck:
    def test_returns_not_installed_when_which_finds_nothing(
        self, ctx: HandlerContext
    ) -> None:
        with patch("handlers.shutil.which", return_value=None), \
             patch("handlers.os.path.isfile", return_value=False):
            result = kicad_cli_check({}, ctx)
        assert result == {"status": "not_installed"}

    def test_returns_ready_when_v10_detected(
        self, ctx: HandlerContext
    ) -> None:
        with patch("handlers.shutil.which", return_value="/usr/local/bin/kicad-cli"), \
             patch("handlers._run_version_check", return_value="10.0.3\n"):
            result = kicad_cli_check({}, ctx)
        assert result["status"] == "ready"
        assert result["path"] == "/usr/local/bin/kicad-cli"
        assert result["version"] == "10.0.3"

    def test_returns_ready_for_v11(self, ctx: HandlerContext) -> None:
        with patch("handlers.shutil.which", return_value="/x/kicad-cli"), \
             patch("handlers._run_version_check", return_value="11.0.0\n"):
            result = kicad_cli_check({}, ctx)
        assert result["status"] == "ready"
        assert result["version"] == "11.0.0"

    def test_returns_wrong_version_for_v9(self, ctx: HandlerContext) -> None:
        with patch("handlers.shutil.which", return_value="/x/kicad-cli"), \
             patch("handlers._run_version_check", return_value="9.0.2\n"):
            result = kicad_cli_check({}, ctx)
        assert result["status"] == "wrong_version"
        assert result["found"] == "9.0.2"
        assert result["minimum"] == "10.0.0"

    def test_returns_not_installed_when_version_unparseable(
        self, ctx: HandlerContext
    ) -> None:
        with patch("handlers.shutil.which", return_value="/x/kicad-cli"), \
             patch("handlers._run_version_check", return_value="garbage\n"):
            result = kicad_cli_check({}, ctx)
        assert result == {"status": "not_installed"}

    def test_returns_not_installed_when_spawn_fails(
        self, ctx: HandlerContext
    ) -> None:
        # kicad-cli exists on disk but version check fails (corrupt binary).
        with patch("handlers.shutil.which", return_value="/x/kicad-cli"), \
             patch("handlers._run_version_check", return_value=None):
            result = kicad_cli_check({}, ctx)
        assert result == {"status": "not_installed"}

    def test_falls_back_to_candidate_paths(self, ctx: HandlerContext) -> None:
        # shutil.which returns None but a candidate path exists.
        def fake_isfile(path: str) -> bool:
            return path == "/Applications/KiCad/kicad-cli"

        def fake_access(path: str, mode: int) -> bool:
            return path == "/Applications/KiCad/kicad-cli"

        with patch("handlers.shutil.which", return_value=None), \
             patch("handlers.os.path.isfile", side_effect=fake_isfile), \
             patch("handlers.os.access", side_effect=fake_access), \
             patch("handlers._run_version_check", return_value="10.0.0\n"):
            result = kicad_cli_check({}, ctx)
        assert result["status"] == "ready"
        assert result["path"] == "/Applications/KiCad/kicad-cli"

    def test_parsing_handles_labeled_output(self, ctx: HandlerContext) -> None:
        """kicad-cli prints 'KiCad CLI 10.0.3' — we should still parse 10.0.3."""
        with patch("handlers.shutil.which", return_value="/x/kicad-cli"), \
             patch("handlers._run_version_check",
                   return_value="KiCad Command Line Interface\nVersion: 10.0.3\n"):
            result = kicad_cli_check({}, ctx)
        assert result["status"] == "ready"
        assert result["version"] == "10.0.3"

    def test_parsing_handles_v_prefix(self, ctx: HandlerContext) -> None:
        with patch("handlers.shutil.which", return_value="/x/kicad-cli"), \
             patch("handlers._run_version_check", return_value="v10.0.3\n"):
            result = kicad_cli_check({}, ctx)
        assert result["status"] == "ready"

    def test_parsing_handles_partial_version(self, ctx: HandlerContext) -> None:
        with patch("handlers.shutil.which", return_value="/x/kicad-cli"), \
             patch("handlers._run_version_check", return_value="10.0\n"):
            result = kicad_cli_check({}, ctx)
        assert result["status"] == "ready"
        assert result["version"] == "10.0.0"

    def test_real_kicad_cli_if_installed(self, ctx: HandlerContext) -> None:
        """If the test host has kicad-cli installed, exercise the real path."""
        import shutil as _shutil
        if not _shutil.which("kicad-cli"):
            pytest.skip("No kicad-cli on test host")
        result = kicad_cli_check({}, ctx)
        # Should be ready (any dev machine with kicad-cli is on 10+).
        assert result["status"] == "ready"


# =============================================================================
# _parse_version / _split_version helpers
# =============================================================================

class TestVersionParsing:
    def test_split_version_full(self) -> None:
        assert _split_version("10.0.3") == (10, 0, 3)

    def test_split_version_major_minor(self) -> None:
        assert _split_version("10.0") == (10, 0, 0)

    def test_split_version_major_only(self) -> None:
        assert _split_version("10") == (10, 0, 0)

    def test_split_version_with_suffix(self) -> None:
        # "10.0.3+debug" → (10, 0, 3)
        assert _split_version("10.0.3+debug") == (10, 0, 3)

    def test_split_version_no_leading_int(self) -> None:
        assert _split_version("abc") is None

    def test_parse_version_from_text(self) -> None:
        assert _parse_version("KiCad CLI 10.0.3") == (10, 0, 3)

    def test_parse_version_handles_v_prefix(self) -> None:
        assert _parse_version("v10.0.3") == (10, 0, 3)

    def test_parse_version_empty(self) -> None:
        assert _parse_version("") is None

    def test_parse_version_no_digits(self) -> None:
        assert _parse_version("no version here") is None

    def test_parse_version_finds_in_blob(self) -> None:
        text = "kicad-cli\nVersion: 10.0.3\nCompiled: 2026-07-07"
        assert _parse_version(text) == (10, 0, 3)

    def test_minimum_version_is_10(self) -> None:
        assert KICAD_MINIMUM_VERSION == (10, 0, 0)

    def test_candidate_paths_includes_standard_locations(self) -> None:
        assert "/Applications/KiCad/kicad-cli" in KICAD_CANDIDATE_PATHS
        assert "/usr/local/bin/kicad-cli" in KICAD_CANDIDATE_PATHS
        assert "/opt/homebrew/bin/kicad-cli" in KICAD_CANDIDATE_PATHS


# =============================================================================
# external_http_status
# =============================================================================

class TestExternalHttpStatus:
    def test_default_state_is_disabled(self, ctx: HandlerContext) -> None:
        result = external_http_status({}, ctx)
        assert result["enabled"] is False
        assert result["port"] == 8080
        assert result["has_token"] is False
        assert result["failed_auth_count"] == 0
        assert result["auto_revoked"] is False
        assert result["bind"] == "127.0.0.1"

    def test_reflects_enabled_state(self, ctx: HandlerContext) -> None:
        ctx.external_http_enabled = True
        ctx.regenerate_external_http_token()
        result = external_http_status({}, ctx)
        assert result["enabled"] is True
        assert result["has_token"] is True

    def test_never_returns_token_value(self, ctx: HandlerContext) -> None:
        """DAEM-08: the token is never serialized through this handler."""
        ctx.regenerate_external_http_token()
        result = external_http_status({}, ctx)
        assert "token" not in result
        assert "auth_token" not in result

    def test_reflects_failed_auth_count(self, ctx: HandlerContext) -> None:
        for _ in range(3):
            ctx.record_external_http_auth_failure()
        result = external_http_status({}, ctx)
        assert result["failed_auth_count"] == 3


# =============================================================================
# external_http_regenerate_token
# =============================================================================

class TestExternalHttpRegenerateToken:
    def test_returns_new_token(self, ctx: HandlerContext) -> None:
        result = external_http_regenerate_token({}, ctx)
        assert "token" in result
        assert isinstance(result["token"], str)
        assert result["length"] == len(result["token"])
        assert result["length"] >= 40  # 32 bytes base64url ≈ 43 chars

    def test_token_is_url_safe_base64(self, ctx: HandlerContext) -> None:
        result = external_http_regenerate_token({}, ctx)
        token = result["token"]
        # URL-safe base64 alphabet only: A-Z a-z 0-9 - _
        import re
        assert re.match(r"^[A-Za-z0-9_-]+$", token), \
            f"Token contains non-base64url chars: {token}"

    def test_token_persists_in_ctx(self, ctx: HandlerContext) -> None:
        result = external_http_regenerate_token({}, ctx)
        assert ctx.external_http_token == result["token"]

    def test_regenerate_produces_different_tokens(self, ctx: HandlerContext) -> None:
        t1 = external_http_regenerate_token({}, ctx)["token"]
        t2 = external_http_regenerate_token({}, ctx)["token"]
        assert t1 != t2

    def test_regenerate_resets_failed_auth(self, ctx: HandlerContext) -> None:
        ctx.external_http_failed_auth_count = 5
        external_http_regenerate_token({}, ctx)
        assert ctx.external_http_failed_auth_count == 0

    def test_logs_audit_event(self, ctx: HandlerContext) -> None:
        external_http_regenerate_token({}, ctx)
        audit = ctx.audit
        assert audit is not None
        events = [e for e in audit.events if e[0] == "external_http_token_regen"]
        assert len(events) == 1

    def test_works_without_audit(self, ctx_no_audit: HandlerContext) -> None:
        """Audit logger is optional — handler must not crash without it."""
        result = external_http_regenerate_token({}, ctx_no_audit)
        assert "token" in result


# =============================================================================
# external_http_set_enabled
# =============================================================================

class TestExternalHttpSetEnabled:
    def test_enable_sets_flag(self, ctx: HandlerContext) -> None:
        result = external_http_set_enabled({"enabled": True}, ctx)
        assert result == {"enabled": True}
        assert ctx.external_http_enabled is True

    def test_disable_clears_flag(self, ctx: HandlerContext) -> None:
        ctx.external_http_enabled = True
        result = external_http_set_enabled({"enabled": False}, ctx)
        assert result == {"enabled": False}
        assert ctx.external_http_enabled is False

    def test_enable_auto_generates_token(self, ctx: HandlerContext) -> None:
        """First enable must create a token if none exists."""
        assert ctx.external_http_token is None
        external_http_set_enabled({"enabled": True}, ctx)
        assert ctx.external_http_token is not None

    def test_enable_does_not_overwrite_existing_token(
        self, ctx: HandlerContext
    ) -> None:
        existing = ctx.regenerate_external_http_token()
        external_http_set_enabled({"enabled": True}, ctx)
        assert ctx.external_http_token == existing

    def test_missing_enabled_field_raises(self, ctx: HandlerContext) -> None:
        with pytest.raises(RpcError) as exc_info:
            external_http_set_enabled({}, ctx)
        assert exc_info.value.code == INVALID_PARAMS
        assert "enabled" in exc_info.value.message

    def test_non_bool_enabled_raises(self, ctx: HandlerContext) -> None:
        with pytest.raises(RpcError) as exc_info:
            external_http_set_enabled({"enabled": "yes"}, ctx)
        assert exc_info.value.code == INVALID_PARAMS

    def test_non_dict_params_raises(self, ctx: HandlerContext) -> None:
        with pytest.raises(RpcError):
            external_http_set_enabled("not a dict", ctx)

    def test_none_params_raises(self, ctx: HandlerContext) -> None:
        with pytest.raises(RpcError):
            external_http_set_enabled(None, ctx)

    def test_logs_toggle_audit_event(self, ctx: HandlerContext) -> None:
        external_http_set_enabled({"enabled": True}, ctx)
        audit = ctx.audit
        assert audit is not None
        events = [e for e in audit.events if e[0] == "external_http_toggle"]
        assert events[0][1]["enabled"] is True


# =============================================================================
# DAEM-08 auto-revoke
# =============================================================================

class TestAutoRevoke:
    def test_nine_failures_does_not_revoke(self, ctx: HandlerContext) -> None:
        original_token = ctx.regenerate_external_http_token()
        for _ in range(9):
            ctx.record_external_http_auth_failure()
        assert ctx.external_http_enabled is False  # never enabled
        assert ctx.external_http_failed_auth_count == 9
        assert ctx.external_http_auto_revoked is False
        assert ctx.external_http_token == original_token

    def test_ten_failures_triggers_revoke(self, ctx: HandlerContext) -> None:
        ctx.external_http_enabled = True
        original_token = ctx.regenerate_external_http_token()
        for _ in range(10):
            ctx.record_external_http_auth_failure()
        # DAEM-08: 10+ failures auto-revoke + disable.
        assert ctx.external_http_auto_revoked is True
        assert ctx.external_http_enabled is False
        # Token rotates so prior brute-force is invalidated.
        assert ctx.external_http_token != original_token

    def test_eleven_failures_still_revoke_state(self, ctx: HandlerContext) -> None:
        """Once revoked, additional failures don't trigger anything new."""
        ctx.external_http_enabled = True
        for _ in range(11):
            ctx.record_external_http_auth_failure()
        assert ctx.external_http_auto_revoked is True
        assert ctx.external_http_enabled is False

    def test_revoke_logs_audit_event(self, ctx: HandlerContext) -> None:
        ctx.external_http_enabled = True
        for _ in range(10):
            ctx.record_external_http_auth_failure()
        audit = ctx.audit
        assert audit is not None
        events = [e for e in audit.events if e[0] == "external_http_auto_revoke"]
        assert len(events) == 1
        assert events[0][1]["failures"] == 10

    def test_reset_failures_on_successful_auth(self, ctx: HandlerContext) -> None:
        ctx.record_external_http_auth_failure()
        ctx.record_external_http_auth_failure()
        assert ctx.external_http_failed_auth_count == 2
        ctx.reset_external_http_auth_failures()
        assert ctx.external_http_failed_auth_count == 0


# =============================================================================
# Registry
# =============================================================================

class TestRegistry:
    def test_phase_163_methods_registered(self) -> None:
        methods = registered_methods()
        assert "kicad_cli_check" in methods
        assert "external_http_status" in methods
        assert "external_http_regenerate_token" in methods
        assert "external_http_set_enabled" in methods

    def test_get_handler_returns_phase_163_handlers(self) -> None:
        assert get_handler("kicad_cli_check") is kicad_cli_check
        assert get_handler("external_http_status") is external_http_status
        assert (
            get_handler("external_http_regenerate_token")
            is external_http_regenerate_token
        )
        assert get_handler("external_http_set_enabled") is external_http_set_enabled

    def test_handlers_dict_consistent(self) -> None:
        for method, handler in HANDLERS.items():
            assert get_handler(method) is handler
