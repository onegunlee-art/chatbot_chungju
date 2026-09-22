# 충주 AI 챗봇

충주시 **공식 자료를 근거로만** 답하는 안내 챗봇입니다. 근거가 없으면 지어내지 않고
"확인되지 않았습니다"라고 답합니다.

## 지금 상태

| 구성 요소 | 상태 |
|---|---|
| 하이브리드 검색 (벡터 + BM25) | ✅ 구현·검증 완료 |
| 답변 생성 (Claude Opus 5, 스트리밍, 근거 인용) | ✅ 구현 완료 |
| 매일 21:00 KST 자동 수집 | ✅ 구현 완료 |
| 변경·정정·마감 반영 | ✅ 구현 완료 |
| 수집 감사 (무엇이 빠졌는지 확인) | ✅ 구현 완료 |
| 테스트용 웹 UI | ✅ 구현 완료 |
| 충주시청 게시판 CSS 선택자 | ⚠️ **미검증** — [아래 참고](#2-수집기-선택자-검증-필수) |
| 아바타 데모 화면 (`web/avatar.html`) | ✅ 구현 완료 — 사진 + 브라우저 음성, 연동 0 |
| 동의서 서식 + 동의 영상 대본 | ✅ 작성 완료 — 서명 대기 |
| 음성 안내 (브라우저 내장) | ✅ 구현 완료 — API 키·비용·연동 없음 |
| 상용 TTS 연결부 + 선거법 자동 중단 | ✅ 구현 완료 — [업체 선정 대기](docs/VOICE_OPTIONS.md) |
| 시장 음성 복제 / 실사 아바타 | ⏸ **동의 확보 후** — [제작 계획](docs/AVATAR_PLAN.md) |

---

## 빠른 시작

```bash
git clone https://github.com/onegunlee-art/chatbot_chungju.git
cd chatbot_chungju
cp .env.example .env        # ANTHROPIC_API_KEY 를 채워 넣으세요
docker compose up -d db     # Postgres + pgvector
docker compose up api
```

또는 로컬에서 직접:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[local-embed,dev]"
python -m app.cli init-db
uvicorn app.main:app --reload
```

브라우저에서 <http://localhost:8000> 을 열면 테스트 화면이,
<http://localhost:8000/avatar.html> 을 열면 **아바타 시연 화면**이 나옵니다.

---

## 서버에 올린 뒤 꼭 해야 하는 두 가지

### 1. API 키 넣기

`.env` 의 `ANTHROPIC_API_KEY` 를 채웁니다. 준비 상태는 이렇게 확인합니다:

```bash
curl localhost:8000/readyz
```

### 2. 수집기 선택자 검증 (필수)

개발 환경이 외부망에 닿지 않아 **충주시청 게시판의 CSS 선택자를 실제로 확인하지 못했습니다.**
`app/ingest/sources.yaml` 의 모든 소스는 `verified: false` 이고, 검증 전에는 일일 수집에서
자동으로 제외됩니다 — 잘못된 자료가 DB 에 들어갈 일은 없습니다.

외부망이 되는 서버에서 소스마다 한 번씩 돌려 주세요:

```bash
python -m app.cli verify chungju_press
python -m app.cli verify chungju_notice
```

- **문서가 잡히고 본문이 제대로 보이면** → `sources.yaml` 에서 그 소스의 `verified: true` 로 변경
- **0건이면** → 브라우저 개발자도구로 목록 행·제목 링크·본문 영역의 CSS 선택자를 확인해
  `selectors` 를 고친 뒤 다시 `verify`

전부 검증했으면 첫 수집을 돌립니다:

```bash
python -m app.cli ingest
python -m app.cli ask "충주시 청년 지원사업 알려줘"
```

---

## 설계 요점

### 근거 없는 말을 하지 않는다

답변은 검색된 충주시 자료만을 출처로 삼습니다. 모든 사실 문장에는 `[1]` 같은 근거 번호가
붙고, 화면에는 원문 링크가 함께 표시됩니다. 근거가 없으면 담당 부서 문의로 안내합니다.

### 어제 정보가 오늘 사실처럼 나가지 않는다

일일 수집은 새 글만 가져오는 것이 아니라 기존 글의 **변경·정정·마감·삭제**도 반영합니다.

| 상황 | 처리 |
|---|---|
| 본문이 바뀜 | 이전 판을 `document_revisions` 에 보관하고 새 판으로 교체 |
| 신청 기한이 지남 | `status='expired'` → 검색에서 제외 |
| 정정 공고가 나옴 | `status='superseded'` → 답변에서 "정정됨" 표시 |
| 출처에서 글이 내려감 | `status='removed'` → 검색에서 제외 |

### 무엇이 빠졌는지 알 수 있다

"모든 정보"의 완전 수집은 어떤 시스템도 보장할 수 없습니다. 대신 **무엇을 수집했고
무엇이 왜 빠졌는지** 확인할 수 있게 했습니다.

```bash
curl -H "Authorization: Bearer $ADMIN_TOKEN" localhost:8000/admin/sources     # 수집 대상과 제외 사유
curl -H "Authorization: Bearer $ADMIN_TOKEN" localhost:8000/admin/ingest/runs # 실행별 성공/실패 내역
curl -H "Authorization: Bearer $ADMIN_TOKEN" localhost:8000/admin/stats       # 답변 못 한 질문 목록
```

`/admin/stats` 의 **답변 못 한 질문 목록**이 다음에 무엇을 수집해야 하는지 알려 줍니다.

### 공식 자료와 언론 보도를 섞지 않는다

모든 문서에 신뢰등급이 붙습니다 (1=충주시 공식, 2=공공기관, 3=언론보도, 4=기타).
언론 보도는 "언론 보도에 따르면"으로 표현하고 공식 발표와 같은 무게로 단정하지 않습니다.

---

## 주요 명령

```bash
python -m app.cli init-db                # 스키마 적용
python -m app.cli verify <source_id>     # 수집기 선택자 검증
python -m app.cli ingest [--limit N]     # 즉시 수집
python -m app.cli ask "질문"              # 터미널에서 질의응답 테스트
pytest                                   # 테스트 (48개)
ruff check app tests                     # 린트
```

## 문서

- [아키텍처](docs/ARCHITECTURE.md) — 전체 구조와 데이터 흐름
- [데이터 소스](docs/DATA_SOURCES.md) — 수집 대상, 추가 방법, 수집 예절
- [음성·아바타 동의 절차](docs/PERSONA_CONSENT.md) — **제작 전 반드시 읽을 것**
- [동의서 서식](docs/CONSENT_FORM.md) — **출력해서 미팅에 가져가세요**
- [아바타 제작 계획](docs/AVATAR_PLAN.md) — 업체 선택, 구현 방식, 촬영 목록
- [음성 업체 선정](docs/VOICE_OPTIONS.md) — 후보 비교와 붙이는 방법
- [로드맵](docs/ROADMAP.md) — 남은 일과 12월 모두의AI 연동 준비

## 기술 스택

Python 3.11 · FastAPI · PostgreSQL 16 + pgvector · Claude Opus 5 ·
BGE-M3 임베딩 · Kiwi 형태소 분석 · APScheduler
