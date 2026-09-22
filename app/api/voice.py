"""음성 엔드포인트. 잠겨 있으면 이유를 분명히 알려준다."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.config import get_settings
from app.voice.base import VoiceNotEnabled
from app.voice.service import election_blackout_active, speak

log = logging.getLogger(__name__)
router = APIRouter(prefix="/voice", tags=["voice"])


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=3000)
    voice_id: str | None = None


@router.get("/status")
def voice_status() -> dict:
    s = get_settings()
    return {
        "enabled": s.voice_enabled,
        "provider": s.voice_provider,
        "consent_on_file": s.voice_consent_on_file,
        "election_blackout": election_blackout_active(),
        "note": (
            "사용 가능합니다."
            if s.voice_enabled and not election_blackout_active()
            else "docs/PERSONA_CONSENT.md 의 동의 절차를 완료해야 사용할 수 있습니다."
        ),
    }


@router.post("/speak")
async def voice_speak(req: SpeakRequest) -> Response:
    try:
        speech = await speak(req.text, req.voice_id)
    except VoiceNotEnabled as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception:
        log.exception("음성 합성 실패")
        raise HTTPException(status_code=502, detail="음성 합성에 실패했습니다.") from None

    return Response(
        content=speech.audio,
        media_type=speech.mime_type,
        headers={"Cache-Control": "no-store"},
    )
