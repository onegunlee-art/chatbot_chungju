"""음성 합성 진입점. 동의 잠금이 여기 한 곳에 모여 있다."""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.voice.base import Speech, TTSProvider, VoiceNotEnabled, to_speakable
from app.voice.providers import HttpTTSProvider, NullProvider

log = logging.getLogger(__name__)


def _expand_env(value: str) -> str:
    """헤더 값의 ${VAR} 를 환경변수로 치환한다. API 키를 .env 에만 두기 위함."""
    return os.path.expandvars(value)


@lru_cache(maxsize=1)
def get_provider() -> TTSProvider:
    s = get_settings()

    if not s.voice_enabled:
        # 이유를 로그에 남겨, 설정을 했는데 왜 안 되는지 헤매지 않게 한다.
        if s.voice_provider != "none" and not s.voice_consent_on_file:
            log.warning(
                "VOICE_PROVIDER=%s 이지만 VOICE_CONSENT_ON_FILE 이 false 여서 음성을 잠급니다. "
                "docs/PERSONA_CONSENT.md 의 체크리스트를 먼저 완료하세요.",
                s.voice_provider,
            )
        return NullProvider()

    endpoint = os.getenv("VOICE_ENDPOINT", "")
    if not endpoint:
        log.error("VOICE_ENDPOINT 가 비어 있어 음성을 잠급니다.")
        return NullProvider()

    headers = {
        k: _expand_env(v) for k, v in json.loads(os.getenv("VOICE_HEADERS", "{}")).items()
    }
    body = json.loads(os.getenv("VOICE_BODY", '{"text": "{text}", "voice": "{voice_id}"}'))

    log.info("음성 제공자 활성화: %s", endpoint)
    return HttpTTSProvider(
        endpoint=endpoint,
        headers=headers,
        body_template=body,
        default_voice_id=s.voice_id,
        mime_type=os.getenv("VOICE_MIME", "audio/mpeg"),
    )


def election_blackout_active() -> bool:
    """공직선거법 제82조의8 제한기간인지.

    ELECTION_DAY(YYYY-MM-DD)가 설정되어 있고 그 90일 전부터 선거일까지면 True.
    설정하지 않으면 제한을 적용하지 않는다 — 운영자가 반드시 채워야 하는 값이다.

    선거일은 한국 날짜이므로 오늘도 한국시간으로 판단한다. 서버가 UTC 면
    제한기간의 첫날과 마지막날 판정이 하루 어긋난다.
    """
    raw = os.getenv("ELECTION_DAY", "").strip()
    if not raw:
        return False
    try:
        election_day = date.fromisoformat(raw)
    except ValueError:
        log.error("ELECTION_DAY 형식이 잘못되었습니다(YYYY-MM-DD): %r", raw)
        return False
    today = datetime.now(ZoneInfo(get_settings().timezone)).date()
    days_left = (election_day - today).days
    return 0 <= days_left <= 90


async def speak(text: str, voice_id: str | None = None) -> Speech:
    """답변 텍스트를 낭독용으로 다듬어 합성한다."""
    if election_blackout_active():
        raise VoiceNotEnabled(
            "공직선거법 제82조의8 제한기간(선거일 전 90일)이라 음성 기능을 중단했습니다."
        )
    spoken = to_speakable(text)
    if not spoken:
        raise ValueError("낭독할 내용이 없습니다.")
    return await get_provider().synthesize(spoken, voice_id)
