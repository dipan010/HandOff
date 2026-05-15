"""Application configuration using Pydantic Settings."""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Google Cloud
    GOOGLE_CLOUD_PROJECT: str = "udaa-489513"
    GOOGLE_API_KEY: str = ""

    # GCP Services (Firestore only)
    USE_FIRESTORE: bool = False
    FIRESTORE_COLLECTION: str = "sessions"

    # Local Storage
    LOCAL_SCREENSHOT_DIR: str = "screenshots"

    # Gemini Models
    COMPUTER_USE_MODEL: str = "gemini-2.5-computer-use-preview-10-2025"
    LIVE_MODEL: str = "gemini-2.0-flash-exp"

    # Browser / Screen
    SCREEN_WIDTH: int = 1440
    SCREEN_HEIGHT: int = 900

    # Agent
    MAX_AGENT_TURNS: int = 25
    AGENT_TIMEOUT_SECONDS: int = 300
    SCREENSHOT_INTERVAL: float = 0.5  # seconds between live frames

    # WebSocket auth — set a non-empty secret to require clients to send
    # ?api_key=<key> or Authorization: Bearer <key>; empty = auth disabled
    WS_API_KEY: str = ""

    # Navigation domain policy — both lists use exact hostname matching
    # (subdomains are included automatically)
    NAV_BLOCKED_DOMAINS: list[str] = []   # always rejected, even if in allowed list
    NAV_ALLOWED_DOMAINS: list[str] = []   # if non-empty, only these hosts are reachable

    # Server
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    """Cached settings instance."""
    return Settings()
