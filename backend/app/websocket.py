"""WebSocket connection manager and message routing."""

import asyncio
import json
import logging
from typing import Any
from fastapi import WebSocket
from starlette.websockets import WebSocketState

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages WebSocket connections per session."""

    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}
        self.extension_connections: dict[str, WebSocket] = {}
        # One send at a time per socket: narration audio, screenshots and
        # status updates come from different tasks, and overlapping sends
        # on one socket fail.
        self._send_locks: dict[int, asyncio.Lock] = {}
        # What a dashboard needs to redraw a running task after a reload or a
        # network drop: the plan, each step's latest state, and the status.
        self._replay: dict[str, dict] = {}

    async def _send(self, ws: WebSocket, text: str):
        lock = self._send_locks.setdefault(id(ws), asyncio.Lock())
        async with lock:
            await ws.send_text(text)

    @staticmethod
    def _closed(ws: WebSocket) -> bool:
        return ws.client_state != WebSocketState.CONNECTED or ws.application_state != WebSocketState.CONNECTED

    async def connect(self, session_id: str, websocket: WebSocket):
        """Accept and register a WebSocket connection, and catch it up on a running task."""
        await websocket.accept()
        self.active_connections[session_id] = websocket
        logger.info(f"WebSocket connected: session={session_id}")
        for message in self._replay_messages(session_id):
            await self.send_message(session_id, message)

    def _remember(self, session_id: str, message: dict[str, Any]):
        kind = message.get("type")
        if kind == "plan":
            replay = self._replay.setdefault(session_id, {})
            if not (message.get("data") or {}).get("revision"):
                replay.clear()        # a new task's plan: forget the old one
            replay["plan"] = message
            replay.setdefault("steps", {}).clear()
        elif kind == "step_update" and session_id in self._replay:
            number = (message.get("data") or {}).get("number")
            self._replay[session_id].setdefault("steps", {})[number] = message
        elif kind == "status_update" and session_id in self._replay:
            if (message.get("data") or {}).get("status") in ("cancelled", "completed"):
                self._replay.pop(session_id, None)
            else:
                self._replay[session_id]["status"] = message
        elif kind in ("task_complete", "error"):
            self._replay.pop(session_id, None)

    def _replay_messages(self, session_id: str) -> list[dict]:
        replay = self._replay.get(session_id) or {}
        messages = [replay["plan"]] if "plan" in replay else []
        messages += list((replay.get("steps") or {}).values())
        if "status" in replay:
            messages.append(replay["status"])
        return messages

    def disconnect(self, session_id: str, websocket: WebSocket | None = None):
        """Remove a WebSocket connection (only `websocket`, if given, not a newer one)."""
        current = self.active_connections.get(session_id)
        if current is not None and (websocket is None or current is websocket):
            del self.active_connections[session_id]
            self._send_locks.pop(id(current), None)
            logger.info(f"WebSocket disconnected: session={session_id}")

    def get_connection(self, session_id: str) -> WebSocket | None:
        """Get the WebSocket for a session."""
        return self.active_connections.get(session_id)

    async def connect_extension(self, session_id: str, websocket: WebSocket):
        """Accept and register a WebSocket connection from the Chrome Extension."""
        await websocket.accept()
        self.extension_connections[session_id] = websocket
        logger.info(f"Extension WebSocket connected: session={session_id}")

    def disconnect_extension(self, session_id: str, websocket: WebSocket | None = None):
        """Remove an Extension WebSocket connection (only `websocket`, if given)."""
        current = self.extension_connections.get(session_id)
        if current is not None and (websocket is None or current is websocket):
            del self.extension_connections[session_id]
            self._send_locks.pop(id(current), None)
            logger.info(f"Extension WebSocket disconnected: session={session_id}")

    async def send_to_extension(self, session_id: str, message: dict[str, Any]):
        """Send a JSON command to the Chrome Extension."""
        await self._send_extension(session_id, message)

    async def _send_extension(self, session_id: str, message: dict):
        ws = self.extension_connections.get(session_id)
        if ws:
            try:
                await self._send(ws, json.dumps(message))
            except Exception as e:
                logger.error(f"Failed to send to extension {session_id}: {e!r}")
                if self._closed(ws):
                    self.disconnect_extension(session_id, ws)

    async def broadcast_to_extension(self, session_id: str, message: dict):
        """Broadcast a message as JSON text to the Chrome Extension."""
        await self._send_extension(session_id, message)

    async def send_message(self, session_id: str, message: dict[str, Any]):
        """Send a JSON message to a specific session."""
        self._remember(session_id, message)
        ws = self.active_connections.get(session_id)
        if ws:
            try:
                await self._send(ws, json.dumps(message))
            except Exception as e:
                # One failed message must not cut the dashboard off for good:
                # forget the socket only if it has really closed.
                logger.error(f"Failed to send to session {session_id}: {e!r}")
                if self._closed(ws):
                    self.disconnect(session_id, ws)

    async def send_screenshot(self, session_id: str, screenshot_b64: str, step: int):
        """Send a screenshot update to the frontend."""
        await self.send_message(session_id, {
            "type": "screenshot_update",
            "data": {
                "screenshot": screenshot_b64,
                "step": step,
            }
        })

    async def send_action(self, session_id: str, action: dict, step: int):
        """Send an action execution update."""
        await self.send_message(session_id, {
            "type": "action_executed",
            "data": {
                "action": action,
                "step": step,
            }
        })

    async def send_narration(self, session_id: str, text: str, speak: bool = True):
        """Narration text for the dashboard. `speak` False: the narrator is
        already saying it, so the dashboard only shows it (one voice)."""
        await self.send_message(session_id, {
            "type": "narration",
            "data": {"text": text, "speak": speak}
        })

    async def send_audio_narration(self, session_id: str, audio_b64: str):
        """Send live audio narration chunk (base64) from the Live API."""
        await self.send_message(session_id, {
            "type": "audio_narration",
            "data": {"audio": audio_b64,
                     "encoding": "pcm",
                     "sample_rate": 24000,
                     }
        })

    async def send_action_preview(self, session_id: str, preview_text: str):
        """Send a plain English preview of the next action before it executes."""
        await self.send_message(session_id, {
            "type": "action_preview",
            "data": {"text": preview_text}
        })
        await self.send_to_extension(session_id, {
            "type": "action_preview",
            "text": preview_text
        })

    async def send_status(self, session_id: str, status: str, detail: str = "", grandparents_mode: bool = False):
        """Send agent status update."""
        # Send to main frontend UI
        await self.send_message(session_id, {
            "type": "status_update",
            "data": {"status": status, "detail": detail}
        })
        # Extension — FIXED: was "type": "status", now "type": "UDAA_STATUS"
        # content_script.js listens for "UDAA_STATUS" — "status" was silently ignored
        await self.broadcast_to_extension(session_id, {
            "type": "UDAA_STATUS",
            "payload": {
                "status": status,
                "message": detail,
                "grandparents_mode": grandparents_mode
            }
        })

    async def send_safety_confirm(self, session_id: str, action: dict, request_id: str):
        """Request user confirmation for a safety-flagged action."""
        await self.send_message(session_id, {
            "type": "safety_confirm",
            "data": {
                "action": action,
                "request_id": request_id,
            }
        })

    async def send_task_complete(self, session_id: str, summary: str):
        """Notify the frontend that the task is complete."""
        # 1. Dashboard
        await self.send_message(session_id, {
            "type": "task_complete",
            "data": {"summary": summary}
        })
        # 2. Extension overlay — use UDAA_STATUS which content_script.js listens for
        await self.broadcast_to_extension(session_id, {
            "type": "UDAA_STATUS",
            "payload": {
                "status": "completed",
                "message": f"All done! {summary}" if summary else "Task complete.",
                "grandparents_mode": False
            }
        })

    async def send_error(self, session_id: str, error: str):
        """Send an error message."""
        await self.send_message(session_id, {
            "type": "error",
            "data": {"message": error}
        })


    async def send_pause_prompt(self, session_id: str, data: dict):
        """Send a prompt that pauses the loop and waits for user input."""
        await self.send_message(session_id, {
            "type": "pause_prompt",
            "data": data,
        })
        # Extension — FIXED: was "type": "status", now "type": "UDAA_STATUS"
        await self.broadcast_to_extension(session_id, {
            "type": "UDAA_STATUS",
            "payload": {
                "status": "active",
                "message": "Waiting for your input...",
                "grandparents_mode": False
            }
        })

    async def send_ack(self, session_id: str, text: str, speak: bool = True):
        """A short reply straight after a task arrives ("Sure, opening that now")."""
        await self.send_message(session_id, {"type": "ack", "data": {"text": text, "speak": speak}})

    async def send_quick_reply(self, session_id: str, text: str):
        """An answer that needed no browser work."""
        await self.send_message(session_id, {"type": "quick_reply", "data": {"text": text}})

    async def send_plan(self, session_id: str, steps: list[dict], revision: int = 0):
        """The list of steps HandOff will follow (sent again after each re-plan)."""
        await self.send_message(session_id, {
            "type": "plan",
            "data": {"steps": steps, "revision": revision},
        })

    async def send_step_update(self, session_id: str, number: int, state: str, detail: str = ""):
        """Progress on one step: state is "working", "done", "retrying" or "failed"."""
        await self.send_message(session_id, {
            "type": "step_update",
            "data": {"number": number, "state": state, "detail": detail},
        })

# Singleton connection manager
manager = ConnectionManager()
