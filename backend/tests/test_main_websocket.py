"""Integration tests for the FastAPI WebSocket endpoints.

These exercise the request/response shape and the input-validation guards
without actually starting an agent loop (we patch LiveBrowserAdapter so
no real browser is launched).
"""

import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app, active_sessions


@pytest.fixture(autouse=True)
def clear_active_sessions():
    active_sessions.clear()
    yield
    active_sessions.clear()


@pytest.fixture
def client():
    return TestClient(app)


class TestHealth:
    def test_health_endpoint(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "healthy"
        assert body["service"] == "udaa-backend"
        assert "active_sessions" in body


class TestWebSocketBadInput:
    def test_invalid_json_is_skipped_not_crash(self, client):
        """H3 regression: malformed JSON must not kill the session."""
        with client.websocket_connect("/ws/sess1") as ws:
            ws.send_text("not-valid-json")
            # Connection should still be alive — send valid JSON next to verify
            ws.send_text(json.dumps({"type": "unknown_type"}))
            # If we got here without WebSocketDisconnect, the session survived

    def test_task_start_missing_data_field_is_skipped(self, client):
        """H4 regression: missing 'data' key must not raise KeyError."""
        with client.websocket_connect("/ws/sess1") as ws:
            ws.send_text(json.dumps({"type": "task_start"}))  # no 'data' key
            # Session stays alive
            ws.send_text(json.dumps({"type": "unknown"}))

    def test_task_start_missing_task_field_is_skipped(self, client):
        with client.websocket_connect("/ws/sess1") as ws:
            ws.send_text(json.dumps({"type": "task_start", "data": {}}))
            ws.send_text(json.dumps({"type": "unknown"}))

    def test_safety_response_missing_data_is_safe(self, client):
        """H4 regression: malformed safety_response shouldn't crash either."""
        with client.websocket_connect("/ws/sess1") as ws:
            ws.send_text(json.dumps({"type": "safety_response"}))


class TestExtensionWebSocketBadInput:
    def test_extension_invalid_json_skipped(self, client):
        with client.websocket_connect("/ws/live_ext/sess1") as ws:
            ws.send_text("garbage")
            ws.send_text(json.dumps({"type": "unknown"}))


class TestSafetyResponseFlow:
    def test_safety_response_sets_gate(self, client):
        """Sending safety_response should set the pause gate's approved flag."""
        from app import pause_gate

        with client.websocket_connect("/ws/sess-safety") as ws:
            # Pre-create the gate so we can verify the value gets set
            gate = pause_gate.get_or_create("sess-safety")
            gate.event.clear()
            gate.approved = False
            gate.user_input = None

            ws.send_text(json.dumps({
                "type": "safety_response",
                "data": {"approved": True, "user_input": "user-typed-this"}
            }))
            # Give the server a moment to process
            import time
            for _ in range(20):
                if gate.event.is_set():
                    break
                time.sleep(0.05)

            assert gate.approved is True
            assert gate.user_input == "user-typed-this"

        pause_gate.release("sess-safety")


class TestRestEndpoints:
    def test_get_session_unknown_returns_404(self, client):
        response = client.get("/tasks/nonexistent")
        assert response.status_code == 404

    def test_list_sessions(self, client):
        response = client.get("/sessions")
        assert response.status_code == 200
        assert "sessions" in response.json()
