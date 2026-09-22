"""Anthropic 클라이언트 래퍼.

- 모델: claude-opus-5 (adaptive thinking)
- 스트리밍: 답변이 길어져도 HTTP 타임아웃에 걸리지 않게 항상 스트리밍
- 프롬프트 캐싱: 고정 시스템 프롬프트를 캐시 접두부로 고정
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Iterable
from datetime import datetime
from zoneinfo import ZoneInfo

import anthropic

from app.config import get_settings
from app.llm.persona import SYSTEM_PROMPT, build_context_block

log = logging.getLogger(__name__)

_client: anthropic.AsyncAnthropic | None = None


def get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        s = get_settings()
        _client = anthropic.AsyncAnthropic(api_key=s.anthropic_api_key, max_retries=3)
    return _client


def _today() -> str:
    return datetime.now(ZoneInfo(get_settings().timezone)).strftime("%Y년 %m월 %d일")


def build_messages(
    question: str,
    evidences: list,
    history: Iterable[dict] | None = None,
) -> list[dict]:
    """대화 이력 → 근거 → 질문 순. 근거는 질문 바로 앞에 둬야 모델이 붙잡기 쉽다."""
    messages: list[dict] = []
    for turn in history or []:
        messages.append({"role": turn["role"], "content": turn["content"]})

    context = build_context_block(evidences, _today())
    messages.append({"role": "user", "content": f"{context}\n\n질문: {question}"})
    return messages


async def stream_answer(
    question: str,
    evidences: list,
    history: Iterable[dict] | None = None,
) -> AsyncIterator[tuple[str, object]]:
    """('text', str) 조각들을 흘려보내고, 마지막에 ('usage', dict) 를 준다."""
    s = get_settings()
    client = get_client()

    try:
        async with client.messages.stream(
            model=s.chatbot_model,
            max_tokens=s.max_tokens,
            thinking={"type": "adaptive"},
            output_config={"effort": s.chatbot_effort},
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=build_messages(question, evidences, history),
        ) as stream:
            async for text in stream.text_stream:
                yield "text", text
            final = await stream.get_final_message()

        if final.stop_reason == "refusal":
            yield "error", "안전 정책에 따라 이 질문에는 답변할 수 없습니다."
            return

        usage = final.usage
        yield "usage", {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0),
            "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0),
            "stop_reason": final.stop_reason,
        }

    except anthropic.RateLimitError:
        log.warning("rate limited")
        yield "error", "지금 요청이 몰리고 있습니다. 잠시 후 다시 시도해 주세요."
    except anthropic.APIStatusError as e:
        log.error("anthropic api error: %s %s", e.status_code, e.message)
        yield "error", "일시적인 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."
    except anthropic.APIConnectionError:
        log.exception("connection error")
        yield "error", "네트워크 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."
