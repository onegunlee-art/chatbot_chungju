# 데이터 소스

## 수집 범위 (확정)

"공식 사실 위주"라는 방침에 따라 **1차 자료는 충주시 공식 자료**로 한정합니다.

| 신뢰등급 | 대상 | 수집 |
|---|---|---|
| 1 | 충주시청 보도자료·고시공고·행정예고·관광·복지 안내 | ✅ 주 수집 대상 |
| 2 | 충청북도, 공공데이터포털 등 타 공공기관 공식 자료 | 🔜 2단계 |
| 3 | 언론 보도 | ⏸ 보류 — 필요 시 "언론 보도에 따르면"으로만 인용 |
| 4 | 블로그·커뮤니티·유튜브 댓글 | ❌ 수집 안 함 |

등급 3·4 를 수집하지 않아도 자료 구조에는 `trust_tier` 가 이미 들어 있습니다.
나중에 언론 보도를 넣기로 하면, 공식 자료와 섞이지 않고 구분되어 인용됩니다.

## 현재 등록된 소스

`app/ingest/sources.yaml` 참고.

| id | 대상 | enabled | verified |
|---|---|---|---|
| `chungju_press` | 충주시 보도자료 | ✅ | ⚠️ 미검증 |
| `chungju_notice` | 충주시 고시·공고 | ✅ | ⚠️ 미검증 |
| `chungju_notice_admin` | 행정·입법예고 | ❌ | ⚠️ URL 확인 필요 |
| `chungju_tour` | 관광 정보 | ❌ | ⚠️ URL 확인 필요 |
| `chungju_welfare` | 복지·지원사업 | ❌ | ⚠️ URL 확인 필요 |

> **`verified: false` 인 소스는 일일 수집에서 자동 제외됩니다.**
> 개발 환경이 외부망에 닿지 않아 선택자를 실제로 확인하지 못했기 때문입니다.
> 검증 전에는 잘못된 자료가 DB 에 들어가지 않습니다.

## 소스 검증 방법

```bash
python -m app.cli verify chungju_press --limit 3
```

출력에서 확인할 것:

1. **수집된 문서가 0건이 아닌가** → 0건이면 `selectors.row` 또는 `link` 가 틀림
2. **제목이 제대로 나오는가** → 안 나오면 `selectors.link` / `detail_title` 수정
3. **본문 길이가 충분한가** (보통 수백 자 이상) → 짧으면 `selectors.body` 가 틀림
4. **발행일이 파싱되는가** → `None` 이면 `selectors.date` 수정

셀렉터는 브라우저 개발자도구(F12)에서 해당 요소를 우클릭 → "Copy selector" 로
확인하는 것이 가장 빠릅니다.

## 새 소스 추가하기

파이썬 코드를 고칠 필요 없이 `sources.yaml` 에 항목만 추가합니다.

### 게시판형 (`html_board`)

```yaml
  - id: chungju_culture
    name: 충주시 문화행사
    type: html_board
    enabled: true
    verified: false        # verify 통과 후 true 로
    trust_tier: 1
    category: 문화행사
    list_url: "https://www.chungju.go.kr/.../list.do?pageIndex={page}"
    pages: 3               # 목록 몇 페이지까지 훑을지
    id_pattern: "nttNo=(\\d+)"   # 상세 URL 에서 고유번호 뽑는 정규식
    delay_seconds: 0.5     # 요청 간격 (서버 부담 최소화)
    concurrency: 3
    selectors:
      row: "table tbody tr"          # 목록의 각 행
      link: "td.title a"             # 제목 링크 (상세 URL 포함)
      date: "td.date"                # 목록의 날짜 칸
      body: "div.view-content"       # 상세 페이지 본문
      detail_title: "h3.title"       # (선택) 상세 페이지 제목
      department: "span.dept"        # (선택) 담당 부서
```

목록이 `javascript:goView(12345)` 처럼 JS 로 이동하면 `detail_url` 템플릿을 추가합니다:

```yaml
    detail_url: "https://www.chungju.go.kr/.../view.do?nttNo={id}"
    id_pattern: "goView\\((\\d+)\\)"
```

### RSS (`rss`)

```yaml
  - id: some_feed
    type: rss
    enabled: true
    verified: true
    trust_tier: 1
    feed_url: "https://example.go.kr/rss.xml"
```

## 수집 예절

상대 서버에 부담을 주지 않도록 기본값을 보수적으로 잡았습니다.

- 요청 간격 `delay_seconds: 0.5`, 동시 요청 `concurrency: 3`
- `User-Agent` 에 봇임을 명시 (`ChungjuCityBot/0.1`)
- 실패 시 지수 백오프로 최대 3회 재시도
- 목록 페이지는 기본 3페이지까지만 (전체 재수집이 아니라 증분 갱신)

공식 서비스로 전환할 때는 충주시청 정보통신 부서에 수집 사실을 알리고,
가능하면 **공공데이터포털 OpenAPI 나 내부 DB 연계**로 바꾸는 편이 안정적입니다.
크롤링은 사이트 개편 때마다 깨집니다.

## 수집 현황 확인

```bash
curl -H "Authorization: Bearer $ADMIN_TOKEN" localhost:8000/admin/sources
curl -H "Authorization: Bearer $ADMIN_TOKEN" localhost:8000/admin/ingest/runs
curl -H "Authorization: Bearer $ADMIN_TOKEN" localhost:8000/admin/stats
```

`/admin/stats` 의 `unanswered_questions` 는 챗봇이 근거를 못 찾아 답하지 못한 질문
목록입니다. **다음에 무엇을 수집해야 하는지 알려주는 가장 직접적인 신호**입니다.
