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
    LIVE_MODEL: str = "gemini-2.5-flash-native-audio-preview-12-2025"

    # Models for sorting requests, planning and checking steps.
    # SORT_MODEL decides if a request is chat or a task, and quick or hard.
    # Quick tasks are planned with FAST_MODEL, hard ones with STRONG_MODEL.
    # BACKUP_MODEL is tried once whenever one of those calls fails.
    # gemini-2.5-flash-lite and gemini-2.5-pro are closed to new projects.
    # STRONG_MODEL needs a paid (billing-enabled) project; on the free tier its
    # calls fail and BACKUP_MODEL answers instead.
    SORT_MODEL: str = "gemini-3.5-flash-lite"
    FAST_MODEL: str = "gemini-3.5-flash"
    STRONG_MODEL: str = "gemini-3.1-pro-preview"
    BACKUP_MODEL: str = "gemini-2.5-flash"
    # Checks whether a step is finished. A different model from FAST_MODEL
    # spreads the work across separate per-model rate limits on the free tier.
    CHECK_MODEL: str = "gemini-3.5-flash-lite"

    # "steps" = plan, do, check (default). "classic" = the original single loop.
    TASK_FLOW: str = "steps"
    # How steps act. "page" (default): read the page map and act on numbered
    # items with ordinary tool calls (any Gemini model). "screenshot": the
    # Computer Use model clicks on screenshots (needs paid quota).
    ACTION_MODE: str = "page"
    # Where search_web looks when the request doesn't name a site:
    # "google", "bing" or "duckduckgo".
    SEARCH_ENGINE: str = "google"
    MAX_STEP_ACTIONS: int = 10      # actions allowed on one step before re-planning
    MAX_STEP_RETRIES: int = 3       # failed attempts on one step before re-planning
    MAX_PLAN_REVISIONS: int = 2     # re-plans allowed per task
    KEEP_SCREENSHOTS: int = 3       # screenshots kept in the action model's history
    EXTENSION_WAIT_SECONDS: float = 15   # how long a task waits for the Chrome extension to connect
    DASHBOARD_GRACE_SECONDS: float = 30  # a task keeps running this long after its dashboard disconnects
    MODEL_CALL_TIMEOUT: float = 45  # seconds one Gemini call may take before it is tried again

    # Browser / Screen
    SCREEN_WIDTH: int = 1440
    SCREEN_HEIGHT: int = 900

    # Agent
    MAX_AGENT_TURNS: int = 25
    AGENT_TIMEOUT_SECONDS: int = 300
    SCREENSHOT_INTERVAL: float = 0.5  # seconds between live frames

    # Server
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    """Cached settings instance."""
    return Settings()
