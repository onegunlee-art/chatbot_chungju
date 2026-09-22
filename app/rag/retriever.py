"""하이브리드 검색: 벡터(의미) + BM25(정확한 단어) → RRF 융합.

행정 문서는 '청년 월세 지원' 처럼 정확한 사업명이 중요해서 어휘 검색이 꼭 필요하고,
'집 구하는 데 돈 보태주는 거 있어?' 같은 구어 질문은 의미 검색이 필요하다. 둘 다 쓴다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.config import get_settings
from app.db import connection
from app.rag.embeddings import get_embedder
from app.rag.korean import to_tsquery

log = logging.getLogger(__name__)

TRUST_LABEL = {1: "충주시 공식", 2: "공공기관 공식", 3: "언론보도", 4: "기타"}


@dataclass
class Evidence:
    chunk_id: int
    document_id: int
    text: str
    title: str
    url: str
    source_id: str
    category: str | None
    department: str | None
    published_at: str | None
    trust_tier: int
    status: str
    valid_until: str | None
    score: float = 0.0
    ranks: dict[str, int] = field(default_factory=dict)

    @property
    def trust_label(self) -> str:
        return TRUST_LABEL.get(self.trust_tier, "기타")


_SELECT = """
    SELECT c.id            AS chunk_id,
           c.text          AS text,
           d.id            AS document_id,
           d.title         AS title,
           d.url           AS url,
           d.source_id     AS source_id,
           d.category      AS category,
           d.department    AS department,
           d.published_at  AS published_at,
           d.trust_tier    AS trust_tier,
           d.status        AS status,
           d.valid_until   AS valid_until
"""

# 만료/삭제 문서는 기본 검색에서 제외하되, 'superseded' 는 정정 안내를 위해 남겨둔다.
_ACTIVE = "d.status IN ('active', 'superseded')"


def _vector_search(conn, query: str, k: int) -> list[Evidence]:
    vec = get_embedder().embed_query(query)
    rows = conn.execute(
        f"""
        {_SELECT}, (c.embedding <=> %s::vector) AS distance
        FROM chunks c JOIN documents d ON d.id = c.document_id
        WHERE c.embedding IS NOT NULL AND {_ACTIVE}
        ORDER BY c.embedding <=> %s::vector
        LIMIT %s
        """,
        (vec, vec, k),
    ).fetchall()
    return [_to_evidence(r) for r in rows]


def _lexical_search(conn, query: str, k: int) -> list[Evidence]:
    tsq = to_tsquery(query)
    if not tsq:
        return []
    rows = conn.execute(
        f"""
        {_SELECT}, ts_rank_cd(c.tsv, to_tsquery('simple', %s)) AS rank
        FROM chunks c JOIN documents d ON d.id = c.document_id
        WHERE c.tsv @@ to_tsquery('simple', %s) AND {_ACTIVE}
        ORDER BY rank DESC
        LIMIT %s
        """,
        (tsq, tsq, k),
    ).fetchall()
    return [_to_evidence(r) for r in rows]


def _to_evidence(row: dict) -> Evidence:
    return Evidence(
        chunk_id=row["chunk_id"],
        document_id=row["document_id"],
        text=row["text"],
        title=row["title"],
        url=row["url"],
        source_id=row["source_id"],
        category=row["category"],
        department=row["department"],
        published_at=row["published_at"].isoformat() if row["published_at"] else None,
        trust_tier=row["trust_tier"],
        status=row["status"],
        valid_until=row["valid_until"].isoformat() if row["valid_until"] else None,
    )


def _rrf(runs: dict[str, list[Evidence]], rrf_k: int) -> list[Evidence]:
    """Reciprocal Rank Fusion. 점수 스케일이 다른 두 검색기를 순위로만 합친다."""
    merged: dict[int, Evidence] = {}
    for run_name, results in runs.items():
        for rank, ev in enumerate(results, start=1):
            target = merged.setdefault(ev.chunk_id, ev)
            target.score += 1.0 / (rrf_k + rank)
            target.ranks[run_name] = rank
    return sorted(merged.values(), key=lambda e: e.score, reverse=True)


def _dedupe_by_document(evidences: list[Evidence], per_doc: int = 2) -> list[Evidence]:
    """한 문서가 상위를 독식하지 않도록 문서당 청크 수를 제한한다."""
    seen: dict[int, int] = {}
    out: list[Evidence] = []
    for ev in evidences:
        n = seen.get(ev.document_id, 0)
        if n >= per_doc:
            continue
        seen[ev.document_id] = n + 1
        out.append(ev)
    return out


def retrieve(query: str, top_k: int | None = None) -> list[Evidence]:
    s = get_settings()
    top_k = top_k or s.context_top_k
    with connection() as conn:
        try:
            vector_hits = _vector_search(conn, query, s.retrieve_top_k)
        except Exception:  # 임베딩 모델 미구동 등 - 어휘 검색만으로도 답하게 한다
            log.exception("벡터 검색 실패 - 어휘 검색으로만 진행합니다.")
            vector_hits = []
        lexical_hits = _lexical_search(conn, query, s.retrieve_top_k)

    fused = _rrf({"vector": vector_hits, "lexical": lexical_hits}, s.rrf_k)
    return _dedupe_by_document(fused)[:top_k]
