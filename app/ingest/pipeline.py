"""수집 파이프라인: 가져오기 → 변경 감지 → 청크 → 임베딩 → 저장 → 만료 처리.

'매일 새 정보만' 이 아니라 '변경·정정·마감' 까지 반영하는 것이 핵심이다.
- 본문 해시가 바뀌면 이전 판을 document_revisions 에 보관하고 새 판으로 교체한다.
- 목록에서 사라진 문서는 status='removed' 로 내려 검색에서 제외한다.
- valid_until 이 지난 문서는 status='expired' 로 내린다.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from pathlib import Path

import yaml

from app.db import connection
from app.ingest.base import RawDoc
from app.ingest.collectors import build_collector
from app.rag.chunker import chunk as chunk_text
from app.rag.embeddings import get_embedder
from app.rag.korean import tokens_to_column

log = logging.getLogger(__name__)

SOURCES_PATH = Path(__file__).parent / "sources.yaml"


def load_sources(path: Path | str = SOURCES_PATH) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)["sources"]


def active_sources(sources: list[dict] | None = None) -> list[dict]:
    """enabled 이고 verified 인 소스만 실제 수집에 쓴다.

    선택자를 사람이 확인하지 않은 소스가 조용히 쓰레기를 넣는 일을 막는다.
    """
    return [s for s in (sources or load_sources()) if s.get("enabled") and s.get("verified")]


# ── 저장 ────────────────────────────────────────────────────────────
def _upsert_document(conn, doc: RawDoc) -> tuple[int, str]:
    """(document_id, 'inserted'|'updated'|'unchanged') 를 돌려준다."""
    row = conn.execute(
        "SELECT id, content_hash, title, body FROM documents "
        "WHERE source_id = %s AND external_id = %s",
        (doc.source_id, doc.external_id),
    ).fetchone()

    now = datetime.now(UTC)

    if row is None:
        new = conn.execute(
            """
            INSERT INTO documents (source_id, external_id, url, title, body, category,
                                   department, published_at, valid_until, trust_tier,
                                   content_hash, status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'active')
            RETURNING id
            """,
            (
                doc.source_id, doc.external_id, doc.url, doc.title, doc.body, doc.category,
                doc.department, doc.published_at, doc.valid_until, doc.trust_tier, doc.hash,
            ),
        ).fetchone()
        return new["id"], "inserted"

    if row["content_hash"] == doc.hash:
        conn.execute("UPDATE documents SET last_seen_at = %s WHERE id = %s", (now, row["id"]))
        return row["id"], "unchanged"

    # 내용이 바뀌었다 → 이전 판을 이력으로 남기고 갱신
    conn.execute(
        "INSERT INTO document_revisions (document_id, content_hash, title, body) "
        "VALUES (%s,%s,%s,%s)",
        (row["id"], row["content_hash"], row["title"], row["body"]),
    )
    conn.execute(
        """
        UPDATE documents
           SET url=%s, title=%s, body=%s, category=%s, department=%s, published_at=%s,
               valid_until=%s, trust_tier=%s, content_hash=%s,
               status='active', last_seen_at=%s, updated_at=%s
         WHERE id=%s
        """,
        (
            doc.url, doc.title, doc.body, doc.category, doc.department, doc.published_at,
            doc.valid_until, doc.trust_tier, doc.hash, now, now, row["id"],
        ),
    )
    return row["id"], "updated"


def _reindex_chunks(conn, document_id: int, doc: RawDoc) -> int:
    conn.execute("DELETE FROM chunks WHERE document_id = %s", (document_id,))
    pieces = chunk_text(doc.title, doc.body)
    if not pieces:
        return 0
    vectors = get_embedder().embed_documents(pieces)
    for ord_, (text, vec) in enumerate(zip(pieces, vectors)):
        conn.execute(
            "INSERT INTO chunks (document_id, ord, text, tokens_ko, embedding) "
            "VALUES (%s,%s,%s,%s,%s)",
            (document_id, ord_, text, tokens_to_column(text), vec),
        )
    return len(pieces)


def _mark_removed(conn, source_id: str, seen_ids: list[str]) -> int:
    """이번 수집에서 목록에 없던 문서를 removed 로 내린다.

    목록 페이지 수(pages)만큼만 훑으므로, 오래돼서 페이지 밖으로 밀려난 글까지
    removed 로 만들면 안 된다. 이번에 본 글들의 최소 발행일 이후 문서만 대상으로 한다.
    """
    if not seen_ids:
        return 0
    result = conn.execute(
        """
        UPDATE documents SET status = 'removed', updated_at = now()
         WHERE source_id = %s
           AND status = 'active'
           AND NOT (external_id = ANY(%s))
           AND published_at >= (
                 SELECT MIN(published_at) FROM documents
                  WHERE source_id = %s AND external_id = ANY(%s)
               )
        """,
        (source_id, seen_ids, source_id, seen_ids),
    )
    return result.rowcount or 0


def _expire_outdated(conn) -> int:
    result = conn.execute(
        "UPDATE documents SET status = 'expired', updated_at = now() "
        "WHERE status = 'active' AND valid_until IS NOT NULL AND valid_until < now()"
    )
    return result.rowcount or 0


# ── 실행 ────────────────────────────────────────────────────────────
async def ingest_source(source: dict, limit: int | None = None) -> dict:
    started = time.monotonic()
    stats = {
        "source_id": source["id"], "status": "ok",
        "fetched": 0, "inserted": 0, "updated": 0, "unchanged": 0, "expired": 0,
        "error": None,
    }
    try:
        collector = build_collector(source)
        docs = await collector.collect(limit=limit)
        stats["fetched"] = len(docs)

        seen: list[str] = []
        with connection() as conn:
            for doc in docs:
                doc_id, action = _upsert_document(conn, doc)
                seen.append(doc.external_id)
                stats[action] += 1
                if action in ("inserted", "updated"):
                    _reindex_chunks(conn, doc_id, doc)
                conn.commit()

            stats["expired"] += _mark_removed(conn, source["id"], seen)
            conn.commit()

    except Exception as e:  # 한 소스가 죽어도 나머지는 계속 수집한다
        log.exception("[%s] 수집 실패", source["id"])
        stats["status"] = "failed"
        stats["error"] = f"{type(e).__name__}: {e}"

    stats["duration_ms"] = int((time.monotonic() - started) * 1000)
    return stats


async def run_ingest(trigger: str = "manual", limit: int | None = None) -> dict:
    sources = active_sources()
    skipped = [s["id"] for s in load_sources() if s not in sources]

    with connection() as conn:
        run = conn.execute(
            "INSERT INTO ingest_runs (trigger) VALUES (%s) RETURNING id", (trigger,)
        ).fetchone()
        conn.commit()
    run_id = run["id"]
    log.info("수집 시작 run_id=%s trigger=%s 대상=%s", run_id, trigger, [s["id"] for s in sources])

    results = [await ingest_source(s, limit=limit) for s in sources]

    with connection() as conn:
        expired = _expire_outdated(conn)
        for r in results:
            conn.execute(
                """
                INSERT INTO ingest_source_results
                    (run_id, source_id, status, fetched, inserted, updated, unchanged,
                     expired, error, duration_ms)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    run_id, r["source_id"], r["status"], r["fetched"], r["inserted"],
                    r["updated"], r["unchanged"], r["expired"], r["error"], r["duration_ms"],
                ),
            )
        for sid in skipped:
            conn.execute(
                "INSERT INTO ingest_source_results (run_id, source_id, status, error) "
                "VALUES (%s,%s,'skipped','enabled=false 이거나 verified=false')",
                (run_id, sid),
            )

        failed = [r for r in results if r["status"] == "failed"]
        status = "failed" if failed and len(failed) == len(results) else ("partial" if failed or skipped else "ok")
        summary = {
            "sources_run": len(results),
            "sources_skipped": skipped,
            "inserted": sum(r["inserted"] for r in results),
            "updated": sum(r["updated"] for r in results),
            "unchanged": sum(r["unchanged"] for r in results),
            "expired_by_date": expired,
        }
        conn.execute(
            "UPDATE ingest_runs SET finished_at = now(), status = %s, stats = %s::jsonb "
            "WHERE id = %s",
            (status, __import__("json").dumps(summary, ensure_ascii=False), run_id),
        )
        conn.commit()

    log.info("수집 완료 run_id=%s status=%s %s", run_id, status, summary)
    return {"run_id": run_id, "status": status, "summary": summary, "sources": results}


def run_ingest_sync(trigger: str = "schedule") -> dict:
    return asyncio.run(run_ingest(trigger=trigger))
