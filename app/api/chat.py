"""채팅 엔드포인트. SSE 스트리밍(/chat/stream)과 단발 응답(/chat) 둘 다 제공."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.db import connection
from app.llm.client import stream_answer
from app.llm.persona import NO_EVIDENCE_MARKER
from app.rag.retriever import Evidence, retrieve
from app.schemas import ChatRequest, ChatResponse, Citation

log = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])


def _citations(evidences: list[Evidence]) -> list[Citation]:
    return [
        Citation(
            n=i,
            title=ev.title,
            url=ev.url,
            source=ev.source_id,
            trust=ev.trust_label,
            published_at=ev.published_at[:10] if ev.published_at else None,
            status=ev.status,
        )
        for i, ev in enumerate(evidences, start=1)
    ]


def _log_turn(
    session_id: str, question: str, answer: str, citations: list[Citation],
    unanswered: bool, usage: dict,
) -> None:
    """대화를 남긴다. 실패해도 사용자 응답을 막지 않는다."""
    try:
        with connection() as conn:
            row = conn.execute(
                "INSERT INTO conversations (session_id) VALUES (%s) RETURNING id", (session_id,)
            ).fetchone()
            conv_id = row["id"]
            conn.execute(
                "INSERT INTO messages (conversation_id, role, content) VALUES (%s,'user',%s)",
                (conv_id, question),
            )
            conn.execute(
                "INSERT INTO messages (conversation_id, role, content, citations, "
                "unanswered, usage) VALUES (%s,'assistant',%s,%s::jsonb,%s,%s::jsonb)",
                (
                    conv_id, answer,
                    json.dumps([c.model_dump() for c in citations], ensure_ascii=False),
                    unanswered,
                    json.dumps(usage, ensure_ascii=False),
                ),
            )
            conn.commit()
    except Exception:
        log.exception("대화 로그 저장 실패 (응답에는 영향 없음)")


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest) -> StreamingResponse:
    evidences = retrieve(req.message)
    citations = _citations(evidences)
    history = [t.model_dump() for t in req.history]

    async def event_source():
        # 근거를 먼저 보내 화면이 출처를 즉시 그릴 수 있게 한다
        yield _sse("citations", [c.model_dump() for c in citations])

        answer_parts: list[str] = []
        usage: dict = {}
        try:
            async for kind, payload in stream_answer(req.message, evidences, history):
                if kind == "text":
                    answer_parts.append(payload)
                    yield _sse("delta", {"text": payload})
                elif kind == "usage":
                    usage = payload
                elif kind == "error":
                    yield _sse("error", {"message": payload})
        except Exception:
            log.exception("스트리밍 중 오류")
            yield _sse("error", {"message": "답변 생성 중 오류가 발생했습니다."})

        answer = "".join(answer_parts)
        unanswered = NO_EVIDENCE_MARKER in answer or not evidences
        yield _sse("done", {"unanswered": unanswered, "usage": usage})
        _log_turn(req.session_id, req.message, answer, citations, unanswered, usage)

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    evidences = retrieve(req.message)
    citations = _citations(evidences)
    history = [t.model_dump() for t in req.history]

    parts: list[str] = []
    usage: dict = {}
    async for kind, payload in stream_answer(req.message, evidences, history):
        if kind == "text":
            parts.append(payload)
        elif kind == "usage":
            usage = payload
        elif kind == "error":
            parts.append(payload)

    answer = "".join(parts)
    unanswered = NO_EVIDENCE_MARKER in answer or not evidences
    _log_turn(req.session_id, req.message, answer, citations, unanswered, usage)
    return ChatResponse(answer=answer, citations=citations, unanswered=unanswered)


def _sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
