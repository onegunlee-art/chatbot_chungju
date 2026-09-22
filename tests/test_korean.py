from app.rag.korean import to_tsquery, tokenize, tokens_to_column


def test_tokenize_drops_particles_and_short_tokens():
    tokens = tokenize("충주시는 청년에게 월세를 지원합니다")
    assert "충주" in " ".join(tokens) or "충주시" in " ".join(tokens)
    assert "는" not in tokens
    assert all(len(t) > 1 for t in tokens)


def test_empty_input_is_safe():
    assert tokenize("") == []
    assert to_tsquery("") == ""
    assert tokens_to_column("") == ""


def test_tsquery_is_quoted_or_disjunction():
    q = to_tsquery("탄금호 무지개길 주차장")
    assert q == "" or ("'" in q and (" | " in q or q.count("'") == 2))


def test_tsquery_deduplicates_tokens():
    q = to_tsquery("지원 지원 지원")
    assert q.count("|") <= 1
