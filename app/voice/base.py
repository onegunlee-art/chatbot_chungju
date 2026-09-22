"""음성 합성 공통 인터페이스.

여기서 가장 중요한 것은 품질이 아니라 **잠금**이다. 실존 공직자의 음성을 쓰는 일은
서면 동의 없이는 인격권 침해이고, 선거 기간에는 공직선거법 위반이다. 그래서 설정 실수로
켜지는 일이 없도록, 동의 기록이 없으면 합성 자체가 거부되게 만들었다.

절차: docs/PERSONA_CONSENT.md
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol


class VoiceNotEnabled(RuntimeError):
    """음성 기능이 꺼져 있거나 동의 기록이 없을 때."""


@dataclass
class Speech:
    audio: bytes
    mime_type: str


class TTSProvider(Protocol):
    name: str

    async def synthesize(self, text: str, voice_id: str | None = None) -> Speech: ...


# ── 낭독 전 텍스트 정리 ────────────────────────────────────────────
# 화면용 표기가 그대로 읽히면 "청년 월세를 지원합니다 대괄호 일" 처럼 들린다.
_CITATION = re.compile(r"\s*\[\d+\]")
_MARKDOWN = re.compile(r"[*_`#>]+")
_URL = re.compile(r"https?://\S+")
_LIST_BULLET = re.compile(r"^\s*[-•]\s*", re.MULTILINE)
_MULTI_SPACE = re.compile(r"[ \t]{2,}")


def to_speakable(text: str) -> str:
    """답변 본문을 낭독용으로 다듬는다."""
    text = _CITATION.sub("", text)
    text = _URL.sub("자세한 내용은 화면의 링크를 확인해 주세요.", text)
    text = _MARKDOWN.sub("", text)
    text = _LIST_BULLET.sub("", text)
    text = _MULTI_SPACE.sub(" ", text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())
