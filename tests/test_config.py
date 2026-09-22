from app.config import Settings


def test_voice_stays_off_without_written_consent():
    """동의 기록이 없으면 어떤 설정을 해도 음성 합성이 켜지지 않아야 한다."""
    s = Settings(voice_provider="elevenlabs", voice_consent_on_file=False)
    assert s.voice_enabled is False


def test_voice_enabled_only_with_provider_and_consent():
    assert Settings(voice_provider="elevenlabs", voice_consent_on_file=True).voice_enabled is True
    assert Settings(voice_provider="none", voice_consent_on_file=True).voice_enabled is False


def test_origins_are_split_and_trimmed():
    s = Settings(allowed_origins="http://a.com, http://b.com ,")
    assert s.origins == ["http://a.com", "http://b.com"]
