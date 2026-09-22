"""환경설정. 모든 튜닝 값은 여기 한 곳에서만 읽는다."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- LLM ---
    anthropic_api_key: str | None = None
    chatbot_model: str = "claude-opus-5"
    chatbot_effort: Literal["low", "medium", "high", "xhigh", "max"] = "high"
    max_tokens: int = 8000

    # --- DB ---
    database_url: str = "postgresql://chungju:chungju@localhost:5432/chungju"

    # --- 임베딩 ---
    embedding_provider: Literal["local", "voyage"] = "local"
    embedding_model: str = "BAAI/bge-m3"
    embedding_dim: int = 1024
    voyage_api_key: str | None = None

    # --- 검색 ---
    retrieve_top_k: int = 40        # 각 검색기(vector/BM25)가 뽑는 후보 수
    context_top_k: int = 8          # 최종적으로 모델에게 주는 근거 수
    rrf_k: int = 60                 # Reciprocal Rank Fusion 상수

    # --- 수집 스케줄 ---
    timezone: str = "Asia/Seoul"
    ingest_cron_hour: int = 21
    ingest_cron_minute: int = 0
    ingest_on_startup: bool = False
    data_go_kr_service_key: str | None = None

    # --- 운영 ---
    log_level: str = "INFO"
    admin_token: str = "change-me-please"
    allowed_origins: str = "http://localhost:8000"

    # --- 음성 (동의 확보 전에는 비활성) ---
    voice_provider: Literal["none", "elevenlabs", "custom"] = "none"
    voice_api_key: str | None = None
    voice_id: str | None = None
    voice_consent_on_file: bool = False

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def voice_enabled(self) -> bool:
        """서면 동의가 기록되지 않았으면 어떤 설정이든 음성 합성을 켜지 않는다."""
        return self.voice_provider != "none" and self.voice_consent_on_file


@lru_cache
def get_settings() -> Settings:
    return Settings()
