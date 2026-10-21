"""What every browser adapter must provide."""

from typing import Any
from abc import ABC, abstractmethod

class BrowserAdapter(ABC):
    """Abstract base class for browser control layers."""

    @property
    @abstractmethod
    def page(self):
        """Return a direct page handle if the adapter has one, otherwise None."""
        pass

    @abstractmethod
    async def get_current_url(self) -> str:
        """Get the current URL of the active tab."""
        pass

    @abstractmethod
    async def capture_screenshot(self) -> bytes:
        """Capture a PNG screenshot of the current page."""
        pass

    @abstractmethod
    async def execute_action(self, action_name: str, args: dict[str, Any]) -> dict:
        """Execute a Computer Use action on the browser page.
        Returns a dict describing what was done.
        """
        pass

    @abstractmethod
    async def close(self):
        """Close the browser and cleanup."""
        pass
