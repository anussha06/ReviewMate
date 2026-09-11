"""Configuration management for ReviewMate AI.

Loads settings from environment variables and .env file safely.
Ensures API keys and tokens are never exposed in logs or string representations.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Search for .env in project root or current working directory
_BASE_DIR = Path(__file__).resolve().parent.parent
_ENV_FILE = _BASE_DIR / ".env"
if _ENV_FILE.exists():
    load_dotenv(dotenv_path=_ENV_FILE)
else:
    load_dotenv()


def _mask_secret(val: Optional[str]) -> str:
    """Safely mask a secret for logs/diagnostics."""
    if not val:
        return "<not set>"
    if len(val) <= 8:
        return "***"
    return f"{val[:4]}...{val[-4:]}"


class Settings:
    """Application runtime settings."""

    def __init__(self) -> None:
        self.groq_api_key: str = os.getenv("GROQ_API_KEY", "").strip()
        self.groq_model: str = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b").strip()
        self.github_token: str = os.getenv("GITHUB_TOKEN", "").strip()
        self.host: str = os.getenv("HOST", "127.0.0.1").strip()
        self.port: int = int(os.getenv("PORT", "8000"))
        self.db_path: str = os.getenv("DB_PATH", str(_BASE_DIR / "reviewmate.db"))
        self.context_token_limit: int = int(os.getenv("CONTEXT_TOKEN_LIMIT", "6000"))

    @property
    def has_groq_key(self) -> bool:
        return bool(self.groq_api_key)

    @property
    def has_github_token(self) -> bool:
        return bool(self.github_token)

    def masked_summary(self) -> dict[str, str]:
        """Return safe summary of settings without secret leakage."""
        return {
            "groq_model": self.groq_model,
            "groq_api_key": _mask_secret(self.groq_api_key),
            "github_token": _mask_secret(self.github_token),
            "context_token_limit": str(self.context_token_limit),
            "db_path": self.db_path,
        }

    def __repr__(self) -> str:
        return f"Settings(groq_model={self.groq_model!r}, groq_key_set={self.has_groq_key}, github_token_set={self.has_github_token})"


settings = Settings()
