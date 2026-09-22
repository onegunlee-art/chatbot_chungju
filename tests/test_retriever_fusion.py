from app.rag.retriever import Evidence, _dedupe_by_document, _rrf


def ev(chunk_id: int, document_id: int) -> Evidence:
    return Evidence(
        chunk_id=chunk_id, document_id=document_id, text="t", title="제목", url="u",
        source_id="s", category=None, department=None, published_at=None,
        trust_tier=1, status="active", valid_until=None,
    )


def test_rrf_ranks_items_found_by_both_searchers_higher():
    a, b, c = ev(1, 1), ev(2, 2), ev(3, 3)
    fused = _rrf({"vector": [a, b], "lexical": [b, c]}, rrf_k=60)
    assert fused[0].chunk_id == 2          # 양쪽에서 잡힌 문서가 1위
    assert {e.chunk_id for e in fused} == {1, 2, 3}


def test_rrf_records_per_run_ranks():
    a = ev(1, 1)
    fused = _rrf({"vector": [a], "lexical": [a]}, rrf_k=60)
    assert fused[0].ranks == {"vector": 1, "lexical": 1}


def test_rrf_handles_an_empty_run():
    a = ev(1, 1)
    fused = _rrf({"vector": [a], "lexical": []}, rrf_k=60)
    assert len(fused) == 1


def test_dedupe_limits_chunks_per_document():
    items = [ev(1, 10), ev(2, 10), ev(3, 10), ev(4, 11)]
    kept = _dedupe_by_document(items, per_doc=2)
    assert [e.chunk_id for e in kept] == [1, 2, 4]
