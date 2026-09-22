"""SSE 스트림 계약 검증. DB·LLM 없이 엔드포인트만 확인한다."""
import json

import pytest
from fastapi.testclient import TestClient

from app.rag.retriever import Evidence


def make_evidence() -> Evidence:
    return Evidence(
        chunk_id=1, document_id=1, text="지원 대상은 만 19~39세입니다.",
        title="청년 월세 지원", url="https://www.chungju.go.kr/notice/1",
        source_id="chungju_notice", category="지원사업", department="청년정책과",
        published_at="2026-03-01T00:00:00", trust_tier=1, status="active", valid_until=None,
    )


@pytest.fixture
def client(monkeypatch):
    from app.api import chat as chat_mod

    async def fake_stream(question, evidences, history=None):
        yield "text", "지원 대상은 만 19~39세입니다 [1]. "
        yield "text", "자세히는 https://www.chungju.go.kr/notice/1 를 보세요."
        yield "usage", {"input_tokens": 10, "output_tokens": 5}

    monkeypatch.setattr(chat_mod, "retrieve", lambda q, top_k=None: [make_evidence()])
    monkeypatch.setattr(chat_mod, "stream_answer", fake_stream)
    monkeypatch.setattr(chat_mod, "_log_turn", lambda *a, **k: None)

    from app.main import app

    return TestClient(app)


def parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for frame in body.split("\n\n"):
        lines = frame.split("\n")
        ev = next((line[7:].strip() for line in lines if line.startswith("event: ")), None)
        data = next((line[6:] for line in lines if line.startswith("data: ")), None)
        if ev and data:
            events.append((ev, json.loads(data)))
    return events


class TestChatStream:
    def test_event_order_is_citations_then_deltas_then_done(self, client):
        res = client.post("/chat/stream", json={"message": "청년 월세 지원 알려줘"})
        assert res.status_code == 200
        names = [name for name, _ in parse_sse(res.text)]
        assert names[0] == "citations"
        assert names[-1] == "done"
        assert "delta" in names

    def test_citations_carry_source_and_trust(self, client):
        res = client.post("/chat/stream", json={"message": "청년 월세 지원"})
        events = dict(parse_sse(res.text))
        cites = events["citations"]
        assert cites[0]["n"] == 1
        assert cites[0]["trust"] == "충주시 공식"
        assert cites[0]["url"].startswith("https://")

    def test_done_carries_spoken_text_without_screen_markup(self, client):
        """브라우저 음성이 읽을 문장에 근거 번호와 URL 이 남아 있으면 안 된다."""
        res = client.post("/chat/stream", json={"message": "청년 월세 지원"})
        events = dict(parse_sse(res.text))
        spoken = events["done"]["spoken"]
        assert "[1]" not in spoken
        assert "https" not in spoken
        assert "지원 대상은 만 19~39세입니다." in spoken
        assert "화면의 링크" in spoken

    def test_done_reports_answered_when_evidence_was_used(self, client):
        res = client.post("/chat/stream", json={"message": "청년 월세 지원"})
        assert dict(parse_sse(res.text))["done"]["unanswered"] is False


class TestNoEvidence:
    def test_unanswered_is_flagged_when_nothing_retrieved(self, monkeypatch):
        from app.api import chat as chat_mod

        async def fake_stream(question, evidences, history=None):
            yield "text", "제가 가진 충주시 자료에서는 확인되지 않았습니다."

        monkeypatch.setattr(chat_mod, "retrieve", lambda q, top_k=None: [])
        monkeypatch.setattr(chat_mod, "stream_answer", fake_stream)
        monkeypatch.setattr(chat_mod, "_log_turn", lambda *a, **k: None)

        from app.main import app

        res = TestClient(app).post("/chat/stream", json={"message": "없는 질문"})
        events = dict(parse_sse(res.text))
        assert events["citations"] == []
        assert events["done"]["unanswered"] is True


class TestStaticPages:
    def test_demo_pages_are_served(self, client):
        for path in ("/", "/avatar.html"):
            res = client.get(path)
            assert res.status_code == 200, path
            assert "충주" in res.text

    def test_avatar_page_shows_the_ai_disclosure(self, client):
        """동의서 제3조: AI 임을 상시 표시해야 한다."""
        res = client.get("/avatar.html")
        assert "시장 본인이 아닙니다" in res.text
