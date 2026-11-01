"""Runtime configuration: environment first, then values saved from the Settings page."""

import os
from datetime import time
from functools import lru_cache
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Provider = Literal["ollama", "openai", "claude"]

# Fields the Settings page may change (stored in the database, overriding the environment).
EDITABLE = frozenset({
    "llm_service", "ollama_host", "ollama_model", "ollama_num_ctx",
    "openai_base_url", "openai_model", "anthropic_base_url", "claude_model", "claude_effort",
    "transcript_max_chars", "max_ai_summaries_per_channel",
    "smtp_server", "smtp_port", "smtp_security", "email_user", "from_email", "app_url",
    "timezone", "schedule_times",
})
# Never editable from the UI and never returned by the API; only whether they are set.
SECRETS = ("openai_api_key", "anthropic_api_key", "email_password")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False,
                                      populate_by_name=True)

    # LLM
    llm_service: Provider = "ollama"
    ollama_host: str = "http://host.docker.internal:11434"
    ollama_model: str = "llama3.2"
    ollama_num_ctx: int = Field(default=16384, ge=2048, le=1_048_576)
    openai_api_key: str | None = None
    openai_base_url: str | None = None  # any OpenAI-compatible server, e.g. http://host:1234/v1
    openai_model: str = "gpt-4o-mini"
    anthropic_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("ANTHROPIC_API_KEY", "CLAUDE_API_KEY")
    )
    anthropic_base_url: str | None = None  # any Anthropic-compatible server or proxy
    claude_model: str = "claude-haiku-5-5"
    claude_effort: Literal["low", "medium", "high", "xhigh", "max"] = "low"
    llm_timeout_seconds: float = 300

    # YouTube
    transcript_max_chars: int = Field(default=20000, ge=1000, le=200_000)
    channel_scan_limit: int = 30  # flat entries scanned per subscription check
    max_ai_summaries_per_channel: int = Field(default=3, ge=0, le=10)

    # Email
    smtp_server: str = "smtp.gmail.com"
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_security: Literal["starttls", "ssl", "none"] = "starttls"
    email_user: str | None = None
    email_password: str | None = None
    from_email: str | None = None
    app_url: str = "http://localhost:8090"

    # Schedule
    timezone: str = "UTC"
    schedule_times: str = Field(
        default="09:00", validation_alias=AliasChoices("SCHEDULE_TIMES", "SCHEDULE_TIME")
    )
    scheduler_enabled: bool = True

    # Storage / serving
    data_dir: Path = Path("data")
    static_dir: Path = Path("static")

    @field_validator("openai_base_url", "anthropic_base_url", "email_user", "from_email", mode="before")
    @classmethod
    def _blank_is_none(cls, v):
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v

    @field_validator("openai_base_url", "anthropic_base_url", "ollama_host", "app_url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        if v is not None and not v.startswith(("http://", "https://")):
            raise ValueError("must start with http:// or https://")
        return v.rstrip("/") if v else v

    @field_validator("timezone")
    @classmethod
    def _valid_tz(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise ValueError(f"Unknown timezone {v!r}") from e
        return v

    @field_validator("schedule_times", mode="before")
    @classmethod
    def _empty_times(cls, v):
        # SCHEDULE_TIMES wins, but an empty SCHEDULE_TIMES= line must not hide SCHEDULE_TIME
        return v or os.environ.get("SCHEDULE_TIME") or "09:00"

    @field_validator("schedule_times")
    @classmethod
    def _normalize_times(cls, v: str) -> str:
        return ",".join(f"{t:%H:%M}" for t in parse_times(v))

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def parsed_schedule_times(self) -> list[time]:
        return parse_times(self.schedule_times)

    @property
    def sender(self) -> str | None:
        return self.from_email or self.email_user

    @property
    def email_configured(self) -> bool:
        return bool(self.email_user and self.email_password and self.sender)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"


def parse_times(raw: str) -> list[time]:
    """Parse '9:00, 18:30' into sorted unique times. Raises ValueError on bad input."""
    out: set[time] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        hh, sep, mm = part.partition(":")
        if not sep or not hh.isdigit() or not mm.isdigit() or len(mm) != 2:
            raise ValueError(f"Invalid schedule time {part!r}; expected HH:MM")
        out.add(time(int(hh), int(mm)))  # time() validates ranges
    if not out:
        raise ValueError("No schedule times given")
    return sorted(out)


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    _ = s.parsed_schedule_times  # fail fast on bad SCHEDULE_TIMES
    return s
