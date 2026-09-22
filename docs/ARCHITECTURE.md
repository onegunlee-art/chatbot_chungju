# 아키텍처

## 전체 흐름

```
 [매일 21:00 KST]                          [사용자 질문]
        │                                        │
        ▼                                        ▼
  수집 (collectors)                    하이브리드 검색 (retriever)
   충주시 게시판 HTML                    ├─ 벡터 검색 (pgvector, BGE-M3)
        │                                └─ 어휘 검색 (BM25, Kiwi 형태소)
        ▼                                        │
  변경 감지 (content_hash)                    RRF 융합
   신규 / 갱신 / 무변경                          │
        │                                        ▼
        ▼                                  문서당 상위 2청크로 제한
  청크 분할 + 임베딩                              │
        │                                        ▼
        ▼                              Claude Opus 5 (스트리밍)
   PostgreSQL + pgvector  ◄───────────  시스템 프롬프트(캐시됨) + 근거 블록
   documents / chunks                          │
        │                                      ▼
        ▼                              근거 번호가 달린 답변 + 출처 링크
  생애주기 정리
   만료 / 정정 / 삭제
```

## 왜 하이브리드 검색인가

행정 정보 질문은 두 종류가 섞여 들어옵니다.

- **정확한 명칭**: "청년 월세 한시 특별지원" → 어휘 검색(BM25)이 강함
- **구어체 의도**: "집 구하는 데 돈 보태주는 거 있어?" → 벡터 검색이 강함

둘 중 하나만 쓰면 다른 쪽을 놓칩니다. 두 결과를 **RRF(Reciprocal Rank Fusion)** 로
합칩니다. 점수 스케일이 다른 두 검색기를 순위만으로 합치므로 가중치 튜닝이 필요 없고,
양쪽에서 모두 잡힌 문서가 자연스럽게 위로 올라옵니다.

한국어는 Postgres 기본 파서가 제대로 쪼개지 못하므로, **색인 시점과 질의 시점에 똑같이**
Kiwi 형태소 분석기를 통과시킨 뒤 `to_tsvector('simple', ...)` 를 씁니다. 조사가 붙은
"충주시는"과 "충주시가"가 같은 토큰으로 정규화됩니다.

## 프롬프트 캐싱

시스템 프롬프트(약 1천 토큰)를 캐시 접두부로 고정했습니다. 질문·근거·오늘 날짜처럼
매 요청마다 바뀌는 값은 **반드시 캐시 경계 뒤**에 둡니다.

`app/llm/persona.py` 의 `SYSTEM_PROMPT` 에 날짜나 시각을 넣으면 캐시가 매번 깨집니다.
`tests/test_persona.py::test_system_prompt_has_no_volatile_content` 가 이를 막습니다.

캐시가 동작하는지는 응답의 `usage.cache_read_input_tokens` 로 확인합니다
(`/admin/stats` 와 `messages.usage` 컬럼에 기록됨).

## 데이터 모델

| 테이블 | 역할 |
|---|---|
| `documents` | 원문 1건. 출처·신뢰등급·생애주기(`status`)·유효기한 보유 |
| `document_revisions` | 본문이 바뀌기 전 판을 보관 (정정 추적) |
| `chunks` | 검색 단위. 임베딩 + 형태소 tsvector |
| `ingest_runs` / `ingest_source_results` | 수집 실행 감사 로그 |
| `conversations` / `messages` | 대화 로그, 미응답 질문 추적 |

### `status` 값

| 값 | 의미 | 검색 |
|---|---|---|
| `active` | 유효 | 포함 |
| `superseded` | 정정·대체됨 | 포함 (답변에 "정정됨" 표시) |
| `expired` | 기한 지남 | 제외 |
| `removed` | 출처에서 삭제됨 | 제외 |

## 모델 설정

`claude-opus-5`, adaptive thinking, `effort=high`, 항상 스트리밍.

`effort` 는 `.env` 의 `CHATBOT_EFFORT` 로 조절합니다. 일반 안내 질문은 `medium` 으로
낮춰도 품질이 유지되는 경우가 많으니, 실사용 로그가 쌓이면 측정해서 조정하세요.

## 확장 지점

- **새 수집원 추가**: `sources.yaml` 에 항목 추가 → `verify` → `verified: true`
  (파이썬 코드 수정 불필요)
- **임베딩 교체**: `EMBEDDING_PROVIDER=voyage` 로 전환 가능.
  단 차원이 바뀌면 `db/schema.sql` 의 `vector(1024)` 와 기존 청크 재색인 필요
- **모두의AI 연동(12월 예정)**: `docs/ROADMAP.md` 참고
