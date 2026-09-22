"""운영용 엔드포인트. 수집 상태와 수집 공백(미응답 질문)을 눈으로 확인한다."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, HTTPException

from app.config import get_settings
from app.db import connection
from app.ingest.pipeline import load_sources, run_ingest
from app.ingest.scheduler import next_run_time
from app.schemas import IngestRequest

log = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])


def require_admin(authorization: str = Header(default="")) -> None:
    token = get_settings().admin_token
    if not authorization.startswith("Bearer ") or authorization[7:] != token:
        raise HTTPException(status_code=401, detail="관리자 토큰이 필요합니다.")


@router.get("/sources", dependencies=[Depends(require_admin)])
def list_sources() -> dict:
    """무엇을 수집 대상으로 잡고 있는지, 무엇이 왜 빠져 있는지 보여준다."""
    sources = load_sources()
    return {
        "sources": [
            {
                "id": s["id"],
                "name": s.get("name"),
                "enabled": bool(s.get("enabled")),
                "verified": bool(s.get("verified")),
                "collected": bool(s.get("enabled") and s.get("verified")),
                "reason": (
                    None if s.get("enabled") and s.get("verified")
                    else ("enabled=false" if not s.get("enabled") else "선택자 미검증")
                ),
                "trust_tier": s.get("trust_tier", 1),
                "category": s.get("category"),
            }
            for s in sources
        ],
        "next_ingest": next_run_time(),
    }


@router.post("/ingest", dependencies=[Depends(require_admin)])
async def trigger_ingest(req: IngestRequest) -> dict:
    return await run_ingest(trigger="manual", limit=req.limit)


@router.get("/ingest/runs", dependencies=[Depends(require_admin)])
def ingest_runs(limit: int = 10) -> dict:
    with connection() as conn:
        runs = conn.execute(
            "SELECT id, started_at, finished_at, trigger, status, stats "
            "FROM ingest_runs ORDER BY id DESC LIMIT %s",
            (limit,),
        ).fetchall()
        ids = [r["id"] for r in runs] or [0]
        details = conn.execute(
            "SELECT * FROM ingest_source_results WHERE run_id = ANY(%s) ORDER BY id", (ids,)
        ).fetchall()
    by_run: dict[int, list] = {}
    for d in details:
        by_run.setdefault(d["run_id"], []).append(d)
    return {"runs": [{**r, "sources": by_run.get(r["id"], [])} for r in runs]}


@router.get("/stats", dependencies=[Depends(require_admin)])
def stats() -> dict:
    with connection() as conn:
        docs = conn.execute(
            "SELECT source_id, status, count(*) AS n FROM documents "
            "GROUP BY source_id, status ORDER BY source_id"
        ).fetchall()
        chunks = conn.execute("SELECT count(*) AS n FROM chunks").fetchone()
        gaps = conn.execute(
            "SELECT content, created_at FROM messages "
            "WHERE role='user' AND conversation_id IN ("
            "  SELECT conversation_id FROM messages WHERE unanswered"
            ") ORDER BY created_at DESC LIMIT 50"
        ).fetchall()
    return {"documents": docs, "chunks": chunks["n"], "unanswered_questions": gaps}
