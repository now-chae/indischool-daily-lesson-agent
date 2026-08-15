from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _default_indischool_profile_path() -> Path:
    local_app_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return local_app_data / "LessonAgent" / "indischool-profile"


def _default_runtime_path(name: str) -> Path:
    local_app_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return local_app_data / "LessonAgent" / name


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LESSON_AGENT_",
        env_file=".env",
        extra="ignore",
    )

    plan_source: Literal["local"] = "local"
    local_plan_dir: Path = Field(default_factory=lambda: _default_runtime_path("plans"))
    grade: int = 6
    class_number: int = 2
    excluded_subjects: Annotated[tuple[str, ...], NoDecode] = ("체육", "영어")
    timezone: str = "Asia/Seoul"
    max_results: int = Field(default=5, ge=1, le=5)
    indischool_profile_path: Path = Field(default_factory=_default_indischool_profile_path)
    state_path: Path = Field(default_factory=lambda: _default_runtime_path("state"))
    download_path: Path = Field(default_factory=lambda: _default_runtime_path("downloads"))
    dry_run: bool = False
    kakao_rest_api_key: str | None = None
    kakao_redirect_uri: str = "http://localhost:8765/callback"
    openai_api_key: str | None = None
    openai_model: str = "gpt-5-mini"

    @field_validator("excluded_subjects", mode="before")
    @classmethod
    def parse_subjects(cls, value: Any) -> Any:
        if isinstance(value, str):
            return tuple(item.strip() for item in value.split(",") if item.strip())
        return value
