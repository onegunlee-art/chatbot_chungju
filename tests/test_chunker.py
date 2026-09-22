from app.rag.chunker import MAX_CHARS, TARGET_CHARS, chunk


def test_empty_body_yields_nothing():
    assert chunk("제목", "") == []
    assert chunk("제목", "   \n\n ") == []


def test_title_is_prefixed_to_every_chunk():
    body = "\n\n".join("충주시는 청년 지원 사업을 시행합니다." * 10 for _ in range(6))
    chunks = chunk("청년 월세 지원", body)
    assert len(chunks) > 1
    assert all(c.startswith("[청년 월세 지원]\n") for c in chunks)


def test_chunks_stay_near_target_size():
    body = "\n\n".join("행정 문단입니다. " * 20 for _ in range(10))
    for c in chunk("고시", body):
        # 제목 접두어와 겹침(overlap)을 감안한 상한
        assert len(c) < TARGET_CHARS + MAX_CHARS


def test_single_short_paragraph_is_one_chunk():
    chunks = chunk("공고", "신청 기간은 3월 2일까지입니다.")
    assert chunks == ["[공고]\n신청 기간은 3월 2일까지입니다."]
