from __future__ import annotations

from fastapi import APIRouter

from app.config import get_settings
from app.db import connection
from app.ingest.scheduler import next_run_time

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@router.get("/readyz")
def readyz() -> dict:
    s = get_settings()
    checks: dict[str, object] = {}

    try:
        with connection() as conn:
            row = conn.execute("SELECT count(*) AS n FROM chunks").fetchone()
        checks["database"] = "ok"
        checks["indexed_chunks"] = row["n"]
    except Exception as e:  # noqa: BLE001 - 헬스체크는 어떤 이유로도 500 을 내면 안 된다
        checks["database"] = f"error: {type(e).__name__}"
        checks["indexed_chunks"] = 0

    checks["model"] = s.chatbot_model
    checks["anthropic_key"] = "set" if s.anthropic_api_key else "missing"
    checks["embedding_provider"] = s.embedding_provider
    checks["next_ingest"] = next_run_time()
    checks["voice_enabled"] = s.voice_enabled

    ready = checks["database"] == "ok" and checks["anthropic_key"] == "set"
    return {"status": "ready" if ready else "not_ready", **checks}
