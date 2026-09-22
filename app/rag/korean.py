"""한국어 형태소 토크나이저.

Postgres 의 기본 파서는 한국어를 제대로 쪼개지 못하므로, 색인 시점과 질의 시점에
동일한 형태소 분석기를 통과시킨 뒤 'simple' 설정으로 tsvector 를 만든다.
kiwipiepy 가 없으면 공백/음절 기반으로 성능을 낮춰 동작한다(검색이 죽지는 않게).
"""
from __future__ import annotations

import logging
import re
from functools import lru_cache

log = logging.getLogger(__name__)

# 색인에 의미가 있는 품사만 남긴다: 체언, 용언, 수사, 외국어, 한자, 숫자
_KEEP_TAGS = ("NNG", "NNP", "NNB", "NR", "NP", "VV", "VA", "SL", "SH", "SN", "XR")
_NON_WORD = re.compile(r"[^0-9A-Za-z가-힣]+")


@lru_cache(maxsize=1)
def _kiwi():
    try:
        from kiwipiepy import Kiwi
    except ImportError:  # pragma: no cover - 선택 의존성
        log.warning("kiwipiepy 미설치 - 단순 토크나이저로 대체합니다.")
        return None
    return Kiwi()


def tokenize(text: str) -> list[str]:
    """검색용 토큰 목록을 돌려준다."""
    if not text:
        return []
    kiwi = _kiwi()
    if kiwi is None:
        return [t for t in _NON_WORD.split(text.lower()) if len(t) > 1]
    tokens: list[str] = []
    for token in kiwi.tokenize(text):
        if token.tag in _KEEP_TAGS and len(token.form) > 1:
            tokens.append(token.form.lower())
    return tokens


def tokens_to_column(text: str) -> str:
    """DB 의 tokens_ko 컬럼에 저장할 공백 구분 문자열."""
    return " ".join(tokenize(text))


def to_tsquery(text: str) -> str:
    """to_tsquery('simple', ...) 에 넣을 OR 질의 문자열."""
    toks = tokenize(text)
    if not toks:
        return ""
    # 각 토큰을 인용해 특수문자 파싱 오류를 막는다
    return " | ".join(f"'{t}'" for t in dict.fromkeys(toks))
