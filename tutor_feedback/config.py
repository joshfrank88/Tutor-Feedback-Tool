"""Application configuration loaded from environment / .env file."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    anthropic_api_key: str = ""
    whisper_model: str = "base"
    data_dir: Path = Path("./data")
    styles_dir: Path = Path("./styles")
    claude_model: str = "claude-sonnet-4-20250514"


def get_settings() -> Settings:
    return Settings()
