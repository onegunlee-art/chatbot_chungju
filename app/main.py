"""충주 AI 챗봇 - FastAPI 애플리케이션."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import admin, chat, health, voice
from app.config import get_settings
from app.db import close_pool
from app.ingest.scheduler import shutdown_scheduler, start_scheduler

settings = get_settings()
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger("chungju")


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    if settings.ingest_on_startup:
        from app.ingest.pipeline import run_ingest

        try:
            await run_ingest(trigger="startup")
        except Exception:
            log.exception("시작 시 수집 실패 - 서비스는 계속 기동합니다.")
    yield
    shutdown_scheduler()
    close_pool()


app = FastAPI(
    title="충주 AI 챗봇",
    description="충주시 공식 자료를 근거로 답하는 안내 챗봇",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(chat.router)
app.include_router(admin.router)
app.include_router(voice.router)

_web = Path(__file__).resolve().parent.parent / "web"
if _web.is_dir():
    app.mount("/", StaticFiles(directory=str(_web), html=True), name="web")
