-- 충주 AI 챗봇 스키마
-- 설계 원칙: (1) 출처·신뢰등급을 항상 보존 (2) 정정/마감/삭제를 표현 가능
--            (3) 무엇을 수집했고 무엇이 누락됐는지 감사 가능

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ── 원문 문서 ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS documents (
    id            BIGSERIAL PRIMARY KEY,
    source_id     TEXT        NOT NULL,          -- sources.yaml 의 id
    external_id   TEXT        NOT NULL,          -- 출처 내 고유 식별자 (게시글 번호 등)
    url           TEXT        NOT NULL,
    title         TEXT        NOT NULL,
    body          TEXT        NOT NULL,
    category      TEXT,                          -- 고시공고 / 보도자료 / 관광 / 복지 ...
    department    TEXT,                          -- 담당 부서
    published_at  TIMESTAMPTZ,
    -- 신뢰등급: 1=충주시 공식, 2=타 공공기관 공식, 3=언론보도, 4=기타
    trust_tier    SMALLINT    NOT NULL DEFAULT 1,
    -- 생애주기: active=유효, superseded=정정/대체됨, expired=마감, removed=출처에서 삭제
    status        TEXT        NOT NULL DEFAULT 'active',
    superseded_by BIGINT      REFERENCES documents(id) ON DELETE SET NULL,
    valid_until   TIMESTAMPTZ,                   -- 신청마감일 등
    content_hash  TEXT        NOT NULL,          -- 본문 변경 감지용
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_id, external_id)
);

CREATE INDEX IF NOT EXISTS documents_status_idx     ON documents (status);
CREATE INDEX IF NOT EXISTS documents_published_idx  ON documents (published_at DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS documents_source_idx     ON documents (source_id);

-- ── 문서 변경 이력 (정정 추적) ──────────────────────────────
CREATE TABLE IF NOT EXISTS document_revisions (
    id           BIGSERIAL PRIMARY KEY,
    document_id  BIGINT      NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    content_hash TEXT        NOT NULL,
    title        TEXT        NOT NULL,
    body         TEXT        NOT NULL,
    captured_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS document_revisions_doc_idx ON document_revisions (document_id, captured_at DESC);

-- ── 청크 (검색 단위) ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS chunks (
    id          BIGSERIAL PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    ord         INT    NOT NULL,
    text        TEXT   NOT NULL,
    -- 한국어 형태소를 공백으로 이어붙인 문자열 (BM25용)
    tokens_ko   TEXT   NOT NULL DEFAULT '',
    embedding   vector(1024),
    tsv         tsvector GENERATED ALWAYS AS (to_tsvector('simple', tokens_ko)) STORED,
    UNIQUE (document_id, ord)
);

CREATE INDEX IF NOT EXISTS chunks_tsv_idx ON chunks USING GIN (tsv);
CREATE INDEX IF NOT EXISTS chunks_vec_idx ON chunks
    USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);

-- ── 수집 실행 감사 로그 ─────────────────────────────────────
-- "무엇을 수집했고 무엇이 누락됐는지" 를 사람이 확인할 수 있게 하는 표
CREATE TABLE IF NOT EXISTS ingest_runs (
    id            BIGSERIAL PRIMARY KEY,
    started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at   TIMESTAMPTZ,
    trigger       TEXT NOT NULL,                 -- schedule | manual | startup
    status        TEXT NOT NULL DEFAULT 'running', -- running | ok | partial | failed
    stats         JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS ingest_source_results (
    id           BIGSERIAL PRIMARY KEY,
    run_id       BIGINT NOT NULL REFERENCES ingest_runs(id) ON DELETE CASCADE,
    source_id    TEXT   NOT NULL,
    status       TEXT   NOT NULL,                -- ok | failed | skipped
    fetched      INT    NOT NULL DEFAULT 0,
    inserted     INT    NOT NULL DEFAULT 0,
    updated      INT    NOT NULL DEFAULT 0,
    unchanged    INT    NOT NULL DEFAULT 0,
    expired      INT    NOT NULL DEFAULT 0,
    error        TEXT,
    duration_ms  INT
);
CREATE INDEX IF NOT EXISTS ingest_source_results_run_idx ON ingest_source_results (run_id);

-- ── 대화 로그 (품질 개선 / 미응답 질문 추적) ────────────────
CREATE TABLE IF NOT EXISTS conversations (
    id          BIGSERIAL PRIMARY KEY,
    session_id  TEXT        NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS messages (
    id              BIGSERIAL PRIMARY KEY,
    conversation_id BIGINT      NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT        NOT NULL,        -- user | assistant
    content         TEXT        NOT NULL,
    citations       JSONB       NOT NULL DEFAULT '[]'::jsonb,
    -- 근거를 못 찾아 "확인되지 않았다"고 답한 경우 true → 수집 공백 신호
    unanswered      BOOLEAN     NOT NULL DEFAULT false,
    usage           JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS messages_conv_idx       ON messages (conversation_id, created_at);
CREATE INDEX IF NOT EXISTS messages_unanswered_idx ON messages (created_at DESC) WHERE unanswered;
