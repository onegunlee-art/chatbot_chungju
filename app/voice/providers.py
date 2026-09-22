"""TTS 제공자 어댑터.

업체를 아직 고르지 않았으므로, 업체별 SDK 를 미리 박아 넣지 않았다. 대신 대부분의
상용 TTS 가 공통으로 쓰는 'REST + JSON 본문 + 오디오 바이트 응답' 형태를 환경변수로
기술할 수 있게 했다. 업체를 정하면 .env 몇 줄로 붙고, 규격이 다르면 이 파일에
어댑터 클래스 하나만 추가하면 된다.
"""
from __future__ import annotations

import json
import logging

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.voice.base import Speech, TTSProvider, VoiceNotEnabled

log = logging.getLogger(__name__)


class NullProvider:
    """기본값. 음성은 꺼져 있다."""

    name = "none"

    async def synthesize(self, text: str, voice_id: str | None = None) -> Speech:
        raise VoiceNotEnabled(
            "음성 합성이 꺼져 있습니다. docs/PERSONA_CONSENT.md 의 동의 절차를 먼저 진행하세요."
        )


class HttpTTSProvider:
    """환경변수로 기술되는 범용 REST TTS 어댑터.

    VOICE_ENDPOINT   : POST 할 URL
    VOICE_HEADERS    : JSON 객체. 예) {"Authorization": "Bearer ${VOICE_API_KEY}"}
    VOICE_BODY       : JSON 객체 템플릿. {text} 와 {voice_id} 자리가 치환된다.
                       예) {"text": "{text}", "voice": "{voice_id}", "format": "mp3"}
    VOICE_MIME       : 응답 오디오의 MIME 타입 (기본 audio/mpeg)
    """

    name = "http"

    def __init__(
        self,
        endpoint: str,
        headers: dict[str, str],
        body_template: dict,
        default_voice_id: str | None,
        mime_type: str = "audio/mpeg",
    ) -> None:
        self._endpoint = endpoint
        self._headers = headers
        self._body_template = body_template
        self._default_voice_id = default_voice_id
        self._mime_type = mime_type

    def _render_body(self, text: str, voice_id: str | None) -> dict:
        """템플릿의 {text}/{voice_id} 자리를 값으로 바꾼다.

        JSON 으로 직렬화한 뒤 치환하면 따옴표·개행이 깨지므로, 값을 JSON 문자열로
        인코딩해 넣은 다음 다시 파싱한다.
        """
        raw = json.dumps(self._body_template, ensure_ascii=False)
        raw = raw.replace('"{text}"', json.dumps(text, ensure_ascii=False))
        raw = raw.replace(
            '"{voice_id}"', json.dumps(voice_id or self._default_voice_id or "", ensure_ascii=False)
        )
        return json.loads(raw)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,  # RetryError 로 감싸면 호출부의 예외 분기가 어긋난다
    )
    async def synthesize(self, text: str, voice_id: str | None = None) -> Speech:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                self._endpoint,
                headers=self._headers,
                json=self._render_body(text, voice_id),
                timeout=60.0,
            )
            resp.raise_for_status()
            return Speech(audio=resp.content, mime_type=self._mime_type)


__all__ = ["HttpTTSProvider", "NullProvider", "Speech", "TTSProvider", "VoiceNotEnabled"]
