from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.voice.base import VoiceNotEnabled, to_speakable
from app.voice.providers import HttpTTSProvider, NullProvider
from app.voice.service import election_blackout_active

KST = ZoneInfo("Asia/Seoul")


def kst_today():
    """제한기간 판정과 같은 기준으로 오늘을 구한다."""
    return datetime.now(KST).date()


class TestSpeakableText:
    def test_citation_markers_are_not_read_aloud(self):
        got = to_speakable("신청 기간은 3월 2일까지입니다 [2]. 대상은 청년입니다 [1]")
        assert "[" not in got and "]" not in got
        assert "신청 기간은 3월 2일까지입니다." in got

    def test_urls_become_a_spoken_hint(self):
        got = to_speakable("자세히는 https://www.chungju.go.kr/abc 를 보세요")
        assert "https" not in got
        assert "화면의 링크" in got

    def test_markdown_and_bullets_are_stripped(self):
        got = to_speakable("**중요**\n- 첫째\n- 둘째")
        assert "*" not in got
        assert got.splitlines() == ["중요", "첫째", "둘째"]

    def test_blank_input_gives_blank_output(self):
        assert to_speakable("") == ""
        assert to_speakable("   \n\n  ") == ""


class TestConsentLock:
    async def test_null_provider_refuses_and_names_the_procedure(self):
        with pytest.raises(VoiceNotEnabled) as exc:
            await NullProvider().synthesize("안녕하세요")
        assert "PERSONA_CONSENT" in str(exc.value)

    def test_provider_is_null_without_consent(self, monkeypatch):
        """동의 기록이 없으면 업체를 지정해도 NullProvider 가 나와야 한다."""
        from app.config import get_settings
        from app.voice import service

        monkeypatch.setenv("VOICE_PROVIDER", "elevenlabs")
        monkeypatch.setenv("VOICE_CONSENT_ON_FILE", "false")
        monkeypatch.setenv("VOICE_ENDPOINT", "https://example.com/tts")
        get_settings.cache_clear()
        service.get_provider.cache_clear()
        try:
            assert isinstance(service.get_provider(), NullProvider)
        finally:
            get_settings.cache_clear()
            service.get_provider.cache_clear()


class TestElectionBlackout:
    def test_no_election_day_means_no_blackout(self, monkeypatch):
        monkeypatch.delenv("ELECTION_DAY", raising=False)
        assert election_blackout_active() is False

    def test_within_90_days_blocks(self, monkeypatch):
        monkeypatch.setenv("ELECTION_DAY", (kst_today() + timedelta(days=30)).isoformat())
        assert election_blackout_active() is True

    def test_more_than_90_days_out_is_allowed(self, monkeypatch):
        monkeypatch.setenv("ELECTION_DAY", (kst_today() + timedelta(days=200)).isoformat())
        assert election_blackout_active() is False

    def test_past_election_is_allowed(self, monkeypatch):
        monkeypatch.setenv("ELECTION_DAY", (kst_today() - timedelta(days=5)).isoformat())
        assert election_blackout_active() is False

    def test_exactly_90_days_out_blocks(self, monkeypatch):
        """제한기간 첫날. 여기서 하루 틀리면 법을 어긴다."""
        monkeypatch.setenv("ELECTION_DAY", (kst_today() + timedelta(days=90)).isoformat())
        assert election_blackout_active() is True

    def test_91_days_out_is_still_allowed(self, monkeypatch):
        monkeypatch.setenv("ELECTION_DAY", (kst_today() + timedelta(days=91)).isoformat())
        assert election_blackout_active() is False

    def test_election_day_itself_blocks(self, monkeypatch):
        monkeypatch.setenv("ELECTION_DAY", kst_today().isoformat())
        assert election_blackout_active() is True

    def test_malformed_date_does_not_crash(self, monkeypatch):
        monkeypatch.setenv("ELECTION_DAY", "2026년 6월 3일")
        assert election_blackout_active() is False


class TestBodyTemplate:
    def test_quotes_and_newlines_survive_substitution(self):
        """따옴표가 든 답변이 JSON 본문을 깨뜨리면 안 된다."""
        p = HttpTTSProvider(
            endpoint="https://example.com/tts",
            headers={},
            body_template={"text": "{text}", "voice": "{voice_id}", "format": "mp3"},
            default_voice_id="v1",
        )
        body = p._render_body('그는 "안녕"이라 했다\n다음 줄', None)
        assert body["text"] == '그는 "안녕"이라 했다\n다음 줄'
        assert body["voice"] == "v1"
        assert body["format"] == "mp3"

    def test_explicit_voice_id_overrides_default(self):
        p = HttpTTSProvider("https://e.com", {}, {"v": "{voice_id}"}, "default-voice")
        assert p._render_body("안녕", "other-voice")["v"] == "other-voice"
