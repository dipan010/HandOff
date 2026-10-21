"""Live Browser Adapter for communicating with the Chrome Extension."""

import asyncio
import base64
import logging
from typing import Any

from app.browser.base import BrowserAdapter

logger = logging.getLogger(__name__)

class LiveBrowserAdapter(BrowserAdapter):
    """Adapter that delegates browser actions to a connected Chrome Extension via WebSocket."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self._latest_screenshot_bytes: bytes | None = None
        self._latest_screenshot_time: float = 0
        self._latest_url: str = ""
        self._action_result_future: asyncio.Future | None = None
        # The extension's replies carry no request id, so only one action
        # may be waiting for a reply at a time.
        self._action_lock = asyncio.Lock()
        self._page = None  # no page object: the extension does the work
        # How long an action waits for a reconnecting extension before failing.
        self.reconnect_wait = 3.0
        # Set when the extension sees the user click or type in the work tab.
        self.user_input_seen = False
        # True while a task runs: the extension sends the dashboard small live frames.
        self.live_view = False

    @property
    def page(self):
        return self._page

    async def get_current_url(self) -> str:
        res = await self.execute_action("get_current_url", {})
        url = res.get("url") if isinstance(res, dict) else None
        # Fall back to the address sent with the latest screen frame.
        return url if isinstance(url, str) and url else self._latest_url


    def extension_connected(self) -> bool:
        from app.websocket import manager as ws_manager
        return self.session_id in ws_manager.extension_connections

    async def wait_for_extension(self, timeout: float) -> bool:
        """True once the Chrome extension has connected for this session."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while not self.extension_connected():
            if loop.time() >= deadline:
                return False
            await asyncio.sleep(0.1)
        return True

    async def launch(self, start_url: str = ""):
        """Launch a new tab in the user's existing default OS browser."""
        import urllib.parse
        import webbrowser

        # Determine the base URL
        if not start_url:
            base_url = "https://www.google.com"
        else:
            base_url = start_url

        # Parse existing URL to safely append our session query parameter
        parsed_url = urllib.parse.urlparse(base_url)
        query_params = urllib.parse.parse_qs(parsed_url.query)
        query_params['udaa_session_id'] = [self.session_id]

        new_query = urllib.parse.urlencode(query_params, doseq=True)
        final_url = parsed_url._replace(query=new_query).geturl()

        logger.info(f"Opening native browser tab: {final_url}")

        # Opens in a new tab in the user's default active browser
        # Note: Must be run on the main thread, or since it's an async function,
        # using asyncio.to_thread if it blocks, but webbrowser.open is usually non-blocking.
        await asyncio.to_thread(webbrowser.open, final_url, new=2)

        logger.info(f"Triggered Live Chrome Native Tab for session {self.session_id}")

    async def start_live_view(self):
        """Ask the extension to send the dashboard small live frames while the task runs."""
        from app.websocket import manager as ws_manager
        self.live_view = True
        await ws_manager.send_to_extension(self.session_id, {"type": "start_stream"})

    async def capture_screenshot(self, min_timestamp: float = 0) -> bytes:
        """A full-size screenshot of HandOff's tab, taken now.

        The dashboard's live frames are small and not used for this. If the
        tab can't be captured (e.g. it isn't in front), the last full
        screenshot is returned. `min_timestamp` is kept for callers; a
        screenshot taken now is always newer.
        """
        import time
        reply = await self.execute_action("screenshot", {})
        if isinstance(reply, dict) and reply.get("success") and reply.get("image"):
            try:
                self._latest_screenshot_bytes = base64.b64decode(reply["image"])
                self._latest_screenshot_time = time.time()
                self.note_live_frame(reply.get("url"))
            except Exception as e:
                logger.error(f"Failed to decode screenshot: {e}")
        else:
            detail = reply.get("detail") if isinstance(reply, dict) else reply
            logger.warning(f"No screenshot for {self.session_id}: {detail}")
        return self._latest_screenshot_bytes or b""

    def note_live_frame(self, url: str | None = None):
        """A live frame went to the dashboard: remember the address it came with."""
        if url and url != "unknown":
            self._latest_url = url

    def complete_action(self, result: dict):
        """Called by the websocket handler when an action result arrives."""
        if self._action_result_future and not self._action_result_future.done():
            self._action_result_future.set_result(result)

    async def execute_action(self, action_name: str, args: dict[str, Any]) -> dict:
        """Send an action to the extension and wait for the result."""
        async with self._action_lock:
            from app.websocket import manager as ws_manager

            # A short gap (the extension reconnecting) is waited out; no
            # extension at all fails at once instead of after a long timeout.
            if not await self.wait_for_extension(timeout=self.reconnect_wait):
                return {"action": action_name, "success": False,
                        "detail": "The HandOff extension isn't connected to this tab."}

            # Extension is stateless, we just send standard actions
            ext_msg = {
                "type": "execute_action",
                "action": action_name,
                **args
            }

            self._action_result_future = asyncio.Future()

            # We need a way to send to the Extension WS.
            # Assuming the new endpoint registers the extension ws or we broadcast.
            await ws_manager.send_to_extension(self.session_id, ext_msg)

            try:
                # Wait for extension to reply with 'action_result'
                # Page loads are waited for by the extension (up to 10 s), so allow longer.
                timeout = 20.0 if action_name in ("navigate", "open_web_browser", "go_back") else 10.0
                ext_result = await asyncio.wait_for(self._action_result_future, timeout=timeout)
                return ext_result
            except asyncio.TimeoutError:
                logger.warning(f"Extension action timeout for {action_name}")
                return {"action": action_name, "success": False, "detail": "Extension timeout"}
            except Exception as e:
                logger.error(f"Extension action error: {e}")
                return {"action": action_name, "success": False, "detail": str(e)}

    async def close(self):
        """Cleanup resources."""
        # Stop the live view
        from app.websocket import manager as ws_manager
        self.live_view = False
        try:
            await ws_manager.send_to_extension(self.session_id, {"type": "stop_stream"})
        except Exception:
            pass

        self._latest_screenshot_bytes = None
        logger.info(f"LiveBrowserAdapter closed for {self.session_id}")
