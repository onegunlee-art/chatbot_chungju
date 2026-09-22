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

from app.config import get_settings


def _setup_logging() -> None:
    logging.basicConfig(level=get_settings().log_level, format="%(levelname)s %(message)s")


async def cmd_verify(source_id: str, limit: int) -> int:
    """선택자가 맞는지 실제 응답으로 확인한다. 0건이면 selectors 를 고쳐야 한다."""
    from app.ingest.collectors import build_collector
    from app.ingest.pipeline import load_sources

    source = next((s for s in load_sources() if s["id"] == source_id), None)
    if source is None:
        print(f"[오류] sources.yaml 에 '{source_id}' 가 없습니다.")
        return 1

    print(f"▶ {source_id} ({source.get('name')}) 검증 - 최대 {limit}건")
    print(f"  목록 URL: {source.get('list_url') or source.get('feed_url')}")
    docs = await build_collector(source).collect(limit=limit)

    print(f"\n수집된 문서: {len(docs)}건")
    if not docs:
        print("\n❌ 0건입니다. selectors 의 row/link/body 를 실제 HTML 에 맞게 고치세요.")
        print("   브라우저 개발자도구에서 목록 행과 본문 영역의 CSS 선택자를 확인하면 됩니다.")
        return 2

    for d in docs[:3]:
        print(f"\n─ [{d.external_id}] {d.title}")
        print(f"  발행일: {d.published_at}  담당: {d.department}")
        print(f"  URL: {d.url}")
        print(f"  본문 {len(d.body)}자: {d.body[:200]}...")
    print("\n✅ 정상으로 보이면 sources.yaml 에서 이 소스의 verified 를 true 로 바꾸세요.")
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
