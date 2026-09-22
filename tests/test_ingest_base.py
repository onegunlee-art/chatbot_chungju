from app.ingest.base import RawDoc, content_hash, normalize_text
from app.ingest.collectors import parse_date


def test_normalize_collapses_whitespace_and_nbsp():
    assert normalize_text("충주\xa0시   청") == "충주 시 청"
    assert normalize_text("가\n\n\n\n나") == "가\n\n나"


def test_hash_is_stable_across_whitespace_noise():
    a = RawDoc("s", "1", "u", "제목 ", "본문\xa0입니다").normalized()
    b = RawDoc("s", "1", "u", "제목", "본문 입니다").normalized()
    assert a.hash == b.hash


def test_hash_changes_when_body_changes():
    assert content_hash("t", "a") != content_hash("t", "b")


def test_parse_korean_date_formats():
    assert parse_date("2026-03-02").date().isoformat() == "2026-03-02"
    assert parse_date("2026.03.02").date().isoformat() == "2026-03-02"
    assert parse_date("2026년 3월 2일").date().isoformat() == "2026-03-02"
    assert parse_date("") is None
    assert parse_date("없음") is None
