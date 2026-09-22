from dataclasses import dataclass

from app.llm.persona import NO_EVIDENCE_MARKER, SYSTEM_PROMPT, build_context_block


@dataclass
class FakeEvidence:
    title: str = "청년 월세 지원"
    text: str = "지원 대상은 만 19~39세입니다."
    trust_label: str = "충주시 공식"
    published_at: str | None = "2026-03-01T00:00:00"
    department: str | None = "청년정책과"
    category: str | None = "지원사업"
    status: str = "active"
    valid_until: str | None = None


def test_system_prompt_has_no_volatile_content():
    """캐시 접두부에 날짜·시각이 들어가면 캐시가 매번 깨진다."""
    for bad in ("2026", "오늘 날짜", "현재 시각"):
        assert bad not in SYSTEM_PROMPT


def test_system_prompt_forbids_impersonation():
    assert "사칭" in SYSTEM_PROMPT
    assert "시장 본인이 아니" in SYSTEM_PROMPT


def test_empty_evidence_block_instructs_the_no_answer_rule():
    block = build_context_block([], "2026년 9월 22일")
    assert "검색된 자료가 없습니다" in block
    assert "2026년 9월 22일" in block


def test_evidence_block_numbers_and_labels_sources():
    block = build_context_block([FakeEvidence(), FakeEvidence(title="두번째")], "2026년 9월 22일")
    assert "[1]" in block and "[2]" in block
    assert "신뢰등급=충주시 공식" in block
    assert "담당=청년정책과" in block
    assert "발행일=2026-03-01" in block


def test_expired_evidence_is_flagged():
    ev = FakeEvidence(status="superseded", valid_until="2026-01-31T00:00:00")
    block = build_context_block([ev], "2026년 9월 22일")
    assert "상태=정정/대체됨" in block
    assert "유효기한=2026-01-31" in block


def test_no_evidence_marker_matches_the_prompt_rule():
    assert NO_EVIDENCE_MARKER in SYSTEM_PROMPT
