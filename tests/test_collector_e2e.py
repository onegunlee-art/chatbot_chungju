"""수집기를 실제 HTTP 서버에 붙여 끝까지 돌려본다.

가짜 게시판이지만 한국 지자체 홈페이지에서 흔한 구조(표 목록 + 상세 페이지)를
그대로 본떴다. 선택자·URL 결합·날짜 파싱·본문 추출이 함께 동작하는지 확인한다.
"""
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

import pytest

from app.ingest.collectors import build_collector

FIXTURES = Path(__file__).parent / "fixtures"


class BoardHandler(SimpleHTTPRequestHandler):
    """목록과 상세를 흉내내는 최소 서버."""

    def do_GET(self):
        name = "board_view.html" if "NttView" in self.path else "board_list.html"
        body = (FIXTURES / name).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def board_url():
    server = HTTPServer(("127.0.0.1", 0), BoardHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


@pytest.fixture
def source(board_url):
    return {
        "id": "test_board",
        "type": "html_board",
        "trust_tier": 1,
        "category": "보도자료",
        "list_url": f"{board_url}/list.do?pageIndex={{page}}",
        "pages": 1,
        "id_pattern": r"nttNo=(\d+)",
        "delay_seconds": 0,
        "concurrency": 3,
        "selectors": {
            "row": "table.p-table tbody tr",
            "link": "td.p-subject a",
            "date": "td.date",
            "body": ".p-view__content",
            "detail_title": ".p-view__title",
            "department": ".p-view__info dd",
        },
    }


class TestCollectorEndToEnd:
    async def test_collects_every_row(self, source):
        docs = await build_collector(source).collect()
        assert len(docs) == 3

    async def test_external_id_comes_from_the_url(self, source):
        docs = await build_collector(source).collect()
        assert {d.external_id for d in docs} == {"1022", "1023", "1024"}

    async def test_relative_links_become_absolute(self, source, board_url):
        docs = await build_collector(source).collect()
        assert all(d.url.startswith(board_url) for d in docs)

    async def test_body_and_department_are_extracted(self, source):
        docs = await build_collector(source).collect()
        doc = docs[0]
        assert "만 19세부터 39세까지" in doc.body
        assert doc.department == "청년정책과"
        assert doc.category == "보도자료"
        assert doc.trust_tier == 1

    async def test_three_korean_date_formats_all_parse(self, source):
        """목록의 2026-03-01 / 2026.02.24 / 2026년 2월 20일 이 모두 읽혀야 한다."""
        docs = await build_collector(source).collect()
        dates = sorted(d.published_at.date().isoformat() for d in docs)
        assert dates == ["2026-02-20", "2026-02-24", "2026-03-01"]

    async def test_dates_are_timezone_aware_kst(self, source):
        docs = await build_collector(source).collect()
        assert all(d.published_at.tzinfo is not None for d in docs)

    async def test_limit_is_respected(self, source):
        docs = await build_collector(source).collect(limit=2)
        assert len(docs) == 2

    async def test_body_is_normalized_and_hashed_stably(self, source):
        first = await build_collector(source).collect(limit=1)
        second = await build_collector(source).collect(limit=1)
        assert first[0].hash == second[0].hash
        assert "  " not in first[0].body


class TestCollectorFailures:
    async def test_unreachable_host_raises_httpx_error_not_retryerror(self, source):
        """tenacity 가 RetryError 로 감싸면 호출부의 예외 처리가 어긋난다."""
        import httpx

        source = {**source, "list_url": "http://127.0.0.1:1/list.do?pageIndex={page}"}
        collector = build_collector(source)
        async with httpx.AsyncClient() as client:
            with pytest.raises(httpx.HTTPError):
                await collector._get(client, source["list_url"])

    async def test_unreachable_list_returns_empty_instead_of_crashing(self, source):
        source = {**source, "list_url": "http://127.0.0.1:1/list.do?pageIndex={page}"}
        assert await build_collector(source).collect() == []

    async def test_wrong_row_selector_returns_nothing(self, source):
        source = {**source, "selectors": {**source["selectors"], "row": "table.nope tr"}}
        assert await build_collector(source).collect() == []

    async def test_wrong_body_selector_drops_the_document(self, source):
        source = {**source, "selectors": {**source["selectors"], "body": "div.nope"}}
        assert await build_collector(source).collect() == []


class TestMissingOptionalFields:
    async def test_missing_department_is_none_not_empty_string(self, source):
        """빈 문자열이 DB 에 들어가면 '없음' 과 '빈칸' 을 구분할 수 없다."""
        source = {**source, "selectors": {**source["selectors"], "department": ".nope"}}
        docs = await build_collector(source).collect(limit=1)
        assert docs[0].department is None

    async def test_missing_detail_title_falls_back_to_list_title(self, source):
        source = {**source, "selectors": {**source["selectors"], "detail_title": ".nope"}}
        docs = await build_collector(source).collect(limit=3)
        titles = {d.title for d in docs}
        assert "2026년 충주사과축제 개최" in titles
