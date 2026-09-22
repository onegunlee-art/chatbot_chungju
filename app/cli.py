"""운영 CLI.

  python -m app.cli init-db                 스키마 적용
  python -m app.cli verify <source_id>      수집기 선택자 검증 (실제로 몇 건 잡히는지)
  python -m app.cli ingest [--limit N]      즉시 수집
  python -m app.cli ask "질문"               검색+답변을 터미널에서 확인
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from app.config import get_settings


def _setup_logging() -> None:
    logging.basicConfig(level=get_settings().log_level, format="%(levelname)s %(message)s")


async def cmd_verify(source_id: str, limit: int) -> int:
    """선택자가 맞는지 실제 응답으로 확인한다.

    '0건' 만 알려주면 원인을 알 수 없다. 접속이 막힌 것인지, 페이지는 받았는데
    선택자가 안 맞는 것인지를 나눠서 보여주고, 받은 HTML 을 파일로 남겨
    그대로 보내면 선택자를 고칠 수 있게 한다.
    """
    import httpx
    from selectolax.parser import HTMLParser

    from app.ingest.catalog import find_source
    from app.ingest.collectors import USER_AGENT, build_collector

    source = find_source(source_id)
    if source is None:
        print(f"[오류] sources.yaml 에 '{source_id}' 가 없습니다.")
        return 1

    list_url = (source.get("list_url") or source.get("feed_url") or "").replace("{page}", "1")
    print(f"▶ {source_id} ({source.get('name')}) 검증")
    print(f"  URL: {list_url}\n")

    # ── 1단계: 페이지를 받아올 수 있는가 ────────────────────────
    try:
        async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}) as client:
            resp = await client.get(list_url, timeout=30.0, follow_redirects=True)
    except Exception as e:  # noqa: BLE001 - 사용자에게 스택트레이스 대신 원인을 보여준다
        print(f"❌ 접속 실패: {type(e).__name__}: {e}\n")
        print("확인해 보세요")
        print("  1. 브라우저로 위 URL 이 열리나요?")
        print("  2. 회사·관공서 망이면 방화벽이나 프록시가 막고 있을 수 있습니다.")
        return 3

    print(f"1) 접속: HTTP {resp.status_code}")
    if resp.status_code != 200:
        print(f"\n❌ 페이지를 받지 못했습니다 (HTTP {resp.status_code}).")
        if resp.status_code in (401, 403):
            print("   차단된 것 같습니다. 브라우저로는 열리는지 확인해 주세요.")
        elif resp.status_code == 404:
            print("   주소가 바뀌었습니다. sources.yaml 의 list_url 을 고쳐야 합니다.")
        return 3

    html = resp.text
    dump = Path(f"verify-{source_id}.html")
    dump.write_text(html, encoding="utf-8")
    print(f"   받은 HTML {len(html):,}자 → {dump} 에 저장했습니다.")

    # ── 2단계: 선택자가 목록 행을 잡는가 ────────────────────────
    row_sel = source.get("selectors", {}).get("row", "")
    rows = HTMLParser(html).css(row_sel) if row_sel else []
    print(f"2) 목록 행 선택자 {row_sel!r} → {len(rows)}개 매칭")

    if not rows:
        print("\n⚠ 페이지는 정상인데 선택자가 안 맞습니다. 페이지에 있는 표 구조입니다:")
        tree = HTMLParser(html)
        seen: set[str] = set()
        for table in tree.css("table")[:5]:
            cls = table.attributes.get("class") or "(class 없음)"
            n = len(table.css("tbody tr")) or len(table.css("tr"))
            key = f"table.{cls}"
            if key not in seen:
                seen.add(key)
                print(f"   - table[class={cls}] 안에 tr {n}개")
        for ul in tree.css("ul")[:5]:
            cls = ul.attributes.get("class")
            if cls and len(ul.css("li")) > 3:
                print(f"   - ul[class={cls}] 안에 li {len(ul.css('li'))}개")
        print(f"\n   → {dump} 파일을 그대로 보내주시면 선택자를 맞춰 드립니다.")
        return 2

    # ── 3단계: 본문까지 실제로 가져오는가 ───────────────────────
    print("3) 본문 수집 시도...")
    try:
        docs = await build_collector(source).collect(limit=limit)
    except Exception as e:  # noqa: BLE001
        print(f"   ❌ 수집 중 오류: {type(e).__name__}: {e}")
        return 3

    print(f"   수집된 문서: {len(docs)}건\n")
    if not docs:
        print("⚠ 목록은 잡혔는데 본문이 비어 있습니다.")
        print("   selectors 의 link 또는 body 를 고쳐야 합니다.")
        print(f"   → {dump} 파일을 보내주시면 맞춰 드립니다.")
        return 2

    for d in docs[:3]:
        print(f"─ [{d.external_id}] {d.title}")
        print(f"  발행일: {d.published_at}  담당: {d.department}")
        print(f"  URL: {d.url}")
        print(f"  본문 {len(d.body)}자: {d.body[:180]}...\n")

    print("✅ 정상입니다. sources.yaml 에서 이 소스의 verified 를 true 로 바꾸세요.")
    return 0


async def cmd_ingest(limit: int | None) -> int:
    from app.ingest.pipeline import run_ingest

    result = await run_ingest(trigger="manual", limit=limit)
    print(f"run_id={result['run_id']} status={result['status']}")
    for k, v in result["summary"].items():
        print(f"  {k}: {v}")
    for s in result["sources"]:
        print(f"  - {s['source_id']}: {s['status']} 수집 {s['fetched']} "
              f"신규 {s['inserted']} 갱신 {s['updated']} {s['error'] or ''}")
    return 0 if result["status"] != "failed" else 1


async def cmd_ask(question: str) -> int:
    from app.llm.client import stream_answer
    from app.rag.retriever import retrieve

    evidences = retrieve(question)
    print(f"[근거 {len(evidences)}건]")
    for i, ev in enumerate(evidences, 1):
        print(f"  [{i}] {ev.title} ({ev.trust_label}) {ev.url}")
    print("\n[답변]")
    async for kind, payload in stream_answer(question, evidences):
        if kind == "text":
            print(payload, end="", flush=True)
        elif kind == "error":
            print(f"\n[오류] {payload}")
        elif kind == "usage":
            print(f"\n\n[토큰] {payload}")
    return 0


def main(argv: list[str] | None = None) -> int:
    _setup_logging()
    parser = argparse.ArgumentParser(prog="chungju", description="충주 AI 챗봇 운영 도구")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init-db", help="db/schema.sql 적용")

    p_verify = sub.add_parser("verify", help="수집기 선택자 검증")
    p_verify.add_argument("source_id")
    p_verify.add_argument("--limit", type=int, default=3)

    p_ingest = sub.add_parser("ingest", help="즉시 수집")
    p_ingest.add_argument("--limit", type=int, default=None)

    p_ask = sub.add_parser("ask", help="질문 테스트")
    p_ask.add_argument("question")

    args = parser.parse_args(argv)

    if args.cmd == "init-db":
        from app.db import apply_schema

        apply_schema()
        print("스키마를 적용했습니다.")
        return 0
    if args.cmd == "verify":
        return asyncio.run(cmd_verify(args.source_id, args.limit))
    if args.cmd == "ingest":
        return asyncio.run(cmd_ingest(args.limit))
    if args.cmd == "ask":
        return asyncio.run(cmd_ask(args.question))
    return 1


if __name__ == "__main__":
    sys.exit(main())
