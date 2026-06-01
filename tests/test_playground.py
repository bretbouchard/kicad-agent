"""TDD tests for Phase 51: Interactive Playground."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kicad_agent.playground.app import create_app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app(tmp_path):
    """Create a playground app with a temp upload directory."""
    return create_app(upload_dir=tmp_path)


@pytest.fixture
def client(app):
    """Synchronous test client for the playground app."""
    return TestClient(app)


@pytest.fixture
def minimal_sch():
    """Minimal .kicad_sch content."""
    return b"(kicad_sch (version 20230121) (generator eeschema)\n  (paper \"A4\")\n)"


# ---------------------------------------------------------------------------
# TestPlaygroundAPI
# ---------------------------------------------------------------------------


class TestPlaygroundAPI:
    """Tests for REST API endpoints."""

    def test_list_operations(self, client):
        """GET /api/operations returns list of operation types."""
        resp = client.get("/api/operations")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_upload_schematic(self, client, minimal_sch):
        """POST /api/upload accepts .kicad_sch file."""
        resp = client.post(
            "/api/upload",
            files={"file": ("test.kicad_sch", minimal_sch, "text/plain")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "session_id" in data
        assert data["filename"] == "test.kicad_sch"
        assert data["size"] == len(minimal_sch)

    def test_upload_pcb(self, client):
        """POST /api/upload accepts .kicad_pcb file."""
        content = b"(kicad_pcb (version 20221018) (generator pcbnew))"
        resp = client.post(
            "/api/upload",
            files={"file": ("board.kicad_pcb", content, "text/plain")},
        )
        assert resp.status_code == 200
        assert "session_id" in resp.json()

    def test_upload_rejects_non_kicad(self, client):
        """POST /api/upload rejects non-KiCad extensions."""
        resp = client.post(
            "/api/upload",
            files={"file": ("evil.exe", b"malware", "application/octet-stream")},
        )
        assert resp.status_code == 415

    def test_upload_rejects_path_traversal(self, client):
        """POST /api/upload rejects path traversal in filename."""
        resp = client.post(
            "/api/upload",
            files={"file": ("../../../etc/passwd", b"root:", "text/plain")},
        )
        assert resp.status_code == 400

    def test_upload_rejects_backslash_traversal(self, client):
        """POST /api/upload rejects backslash path traversal."""
        resp = client.post(
            "/api/upload",
            files={"file": ("..\\..\\windows\\system32", b"data", "text/plain")},
        )
        assert resp.status_code == 400

    def test_upload_rejects_oversized(self, client):
        """POST /api/upload rejects files over 10MB."""
        big_content = b"x" * (11 * 1024 * 1024)
        resp = client.post(
            "/api/upload",
            files={"file": ("big.kicad_sch", big_content, "text/plain")},
        )
        assert resp.status_code == 413

    def test_upload_stores_with_uuid_name(self, client, minimal_sch, tmp_path):
        """Uploaded files are stored with UUID-based names."""
        resp = client.post(
            "/api/upload",
            files={"file": ("test.kicad_sch", minimal_sch, "text/plain")},
        )
        data = resp.json()
        session_id = data["session_id"]

        # File should exist in upload dir with UUID name
        stored = list(tmp_path.glob(f"{session_id}.kicad_sch"))
        assert len(stored) == 1

    def test_execute_validates_operation(self, client):
        """POST /api/execute validates operation JSON."""
        # Invalid op_type should return 400
        resp = client.post(
            "/api/execute",
            json={"operation": {"op_type": "nonexistent_op"}},
        )
        assert resp.status_code == 400

    def test_execute_accepts_valid_schema(self, client):
        """POST /api/execute accepts a valid operation schema."""
        resp = client.post(
            "/api/execute",
            json={"operation": {
                "op_type": "list_net_classes",
                "target_file": "test.kicad_dru",
            }},
        )
        # Returns 200 (operation result, even if file doesn't exist)
        assert resp.status_code == 200
        data = resp.json()
        assert "result" in data

    def test_erc_requires_session(self, client):
        """POST /api/erc with invalid session returns 404."""
        resp = client.post(
            "/api/erc",
            json={"session_id": "nonexistent"},
        )
        assert resp.status_code == 404

    def test_drc_requires_session(self, client):
        """POST /api/drc with invalid session returns 404."""
        resp = client.post(
            "/api/drc",
            json={"session_id": "nonexistent"},
        )
        assert resp.status_code == 404

    def test_preview_requires_session(self, client):
        """GET /api/preview/{sid} with invalid session returns 404."""
        resp = client.get("/api/preview/nonexistent")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# TestPlaygroundWebSocket
# ---------------------------------------------------------------------------


class TestPlaygroundWebSocket:
    """Tests for WebSocket endpoint."""

    def test_ws_connect_sends_welcome(self, client):
        """WebSocket /ws sends connected message on connect."""
        with client.websocket_connect("/ws") as ws:
            data = ws.receive_json()
            assert data["type"] == "connected"

    def test_ws_ping_pong(self, client):
        """WebSocket responds to ping with pong."""
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # welcome
            ws.send_json({"action": "ping"})
            data = ws.receive_json()
            assert data["type"] == "pong"

    def test_ws_unknown_action(self, client):
        """WebSocket returns error for unknown action."""
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # welcome
            ws.send_json({"action": "unknown_action"})
            data = ws.receive_json()
            assert data["type"] == "error"
            assert "Unknown action" in data["message"]


# ---------------------------------------------------------------------------
# TestPlaygroundCLI
# ---------------------------------------------------------------------------


class TestPlaygroundCLI:
    """Tests for CLI integration."""

    def test_playground_importable(self):
        """Playground module is importable."""
        from kicad_agent.playground import create_app
        assert callable(create_app)

    def test_create_app_returns_fastapi(self):
        """create_app returns a FastAPI instance."""
        from fastapi import FastAPI
        app = create_app()
        assert isinstance(app, FastAPI)

    def test_create_app_with_custom_dir(self, tmp_path):
        """create_app accepts custom upload directory."""
        app = create_app(upload_dir=tmp_path)
        assert app.state.upload_dir == tmp_path

    def test_create_app_configures_max_size(self):
        """create_app respects max_upload_mb parameter."""
        app = create_app(max_upload_mb=5)
        assert app.state.max_upload_bytes == 5 * 1024 * 1024


# ---------------------------------------------------------------------------
# TestStaticFiles
# ---------------------------------------------------------------------------


class TestStaticFiles:
    """Tests for static frontend files."""

    def test_index_html_exists(self):
        """index.html exists in static directory."""
        static_dir = Path(__file__).parent.parent / "src" / "kicad_agent" / "playground" / "static"
        assert (static_dir / "index.html").is_file()

    def test_app_js_exists(self):
        """app.js exists in static directory."""
        static_dir = Path(__file__).parent.parent / "src" / "kicad_agent" / "playground" / "static"
        assert (static_dir / "app.js").is_file()

    def test_style_css_exists(self):
        """style.css exists in static directory."""
        static_dir = Path(__file__).parent.parent / "src" / "kicad_agent" / "playground" / "static"
        assert (static_dir / "style.css").is_file()

    def test_index_html_contains_playground(self):
        """index.html contains playground UI structure."""
        static_dir = Path(__file__).parent.parent / "src" / "kicad_agent" / "playground" / "static"
        content = (static_dir / "index.html").read_text()
        assert "playground" in content.lower()
        assert "upload" in content.lower()

    def test_app_js_contains_playground_app(self):
        """app.js contains PlaygroundApp class."""
        static_dir = Path(__file__).parent.parent / "src" / "kicad_agent" / "playground" / "static"
        content = (static_dir / "app.js").read_text()
        assert "class PlaygroundApp" in content

    def test_style_css_contains_playground(self):
        """style.css contains playground styling."""
        static_dir = Path(__file__).parent.parent / "src" / "kicad_agent" / "playground" / "static"
        content = (static_dir / "style.css").read_text()
        assert ".playground" in content
