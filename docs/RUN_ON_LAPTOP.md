# 노트북에서 돌리기

두 단계로 나눠져 있습니다. **1단계만 하셔도 제가 다음 작업을 할 수 있습니다.**

| | 필요한 것 | 걸리는 시간 | 용량 |
|---|---|---|---|
| **1단계 — 수집기 확인** | Python + 인터넷 | 5분 | 약 60MB |
| 2단계 — 챗봇 전체 실행 | + Docker + API 키 | 30분~1시간 | 약 5GB |

DB도, API 키도, AI 모델도 1단계에는 필요 없습니다.

---

# 1단계 — 수집기 확인 (5분)

## 준비: 파이썬

**Windows**

1. <https://www.python.org/downloads/> 에서 최신 버전 내려받기
2. 설치 화면에서 **“Add python.exe to PATH”에 반드시 체크**하고 설치
3. 시작 메뉴에서 `PowerShell` 실행 후 확인:
   ```powershell
   python --version
   ```
   `Python 3.11` 이상이 나오면 됩니다.

**Mac**

`터미널` 앱을 열고:
```bash
python3 --version
```
3.11 미만이거나 없으면 <https://www.python.org/downloads/> 에서 설치하세요.

## 내려받기

**Windows (PowerShell)**
```powershell
cd ~\Desktop
git clone https://github.com/onegunlee-art/chatbot_chungju.git
cd chatbot_chungju
git checkout claude/github-integration-check-uaa9sy
```

**Mac (터미널)**
```bash
cd ~/Desktop
git clone https://github.com/onegunlee-art/chatbot_chungju.git
cd chatbot_chungju
git checkout claude/github-integration-check-uaa9sy
```

> `git` 이 없다면: Windows 는 <https://git-scm.com/download/win>,
> Mac 은 터미널에서 `xcode-select --install` 하면 깔립니다.
> 그마저 번거로우면 깃허브 페이지에서 **Code → Download ZIP** 으로 받아 풀어도 됩니다.

## 설치

**Windows**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-verify.txt
```

> `Activate.ps1` 에서 “스크립트 실행이 차단되었습니다” 가 나오면 한 번만:
> ```powershell
> Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
> ```

**Mac**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-verify.txt
```

## 실행

```
python -m app.cli verify chungju_press
```

그리고

```
python -m app.cli verify chungju_notice
```

## 결과를 저에게 보내주세요

화면에 나온 내용을 **그대로 복사해서** 붙여주시면 됩니다. 세 가지 중 하나가 나옵니다.

### ✅ 잘 된 경우
```
1) 접속: HTTP 200
2) 목록 행 선택자 'table.p-table tbody tr' → 10개 매칭
3) 본문 수집 시도...
   수집된 문서: 3건

─ [1024] 청년 월세 한시 특별지원 신청 안내
  본문 480자: 충주시는 청년의 주거비 부담을...

✅ 정상입니다.
```
→ 바로 다음 단계로 갑니다.

### ⚠ 페이지는 열리는데 선택자가 안 맞는 경우
```
2) 목록 행 선택자 '...' → 0개 매칭
⚠ 페이지는 정상인데 선택자가 안 맞습니다.
   → verify-chungju_press.html 파일을 그대로 보내주시면 선택자를 맞춰 드립니다.
```
→ **폴더에 생긴 `verify-chungju_press.html` 파일을 저에게 보내주세요.**
제가 보고 선택자를 정확히 고쳐 드립니다.

### ❌ 접속 자체가 안 되는 경우
```
❌ 접속 실패: ...
```
→ 그 메시지를 그대로 보내주세요. 주소가 바뀐 것인지 망이 막는 것인지 판단하겠습니다.

---

# 2단계 — 챗봇 전체 실행

1단계가 통과한 뒤에 하시면 됩니다.

## 추가로 필요한 것

- **Docker Desktop** — <https://www.docker.com/products/docker-desktop/>
- **Anthropic API 키** — <https://console.anthropic.com/> 에서 발급

## 설정

```bash
cp .env.example .env          # Windows: copy .env.example .env
```

`.env` 를 메모장으로 열어 이 줄을 채웁니다.
```
ANTHROPIC_API_KEY=sk-ant-...
```

## 실행

```bash
docker compose up -d db       # 데이터베이스 (처음 한 번만 오래 걸립니다)
pip install -e ".[local-embed]"   # AI 모델 포함 - 2~3GB, 시간이 좀 걸립니다
python -m app.cli init-db
python -m app.cli ingest      # 실제 충주 자료 수집
uvicorn app.main:app --reload
```

브라우저에서

- <http://localhost:8000> — 기본 챗봇 화면
- <http://localhost:8000/avatar.html> — **시연용 아바타 화면**

## 시장님 사진 넣기

`web/` 폴더에 사진을 **`portrait.jpg`** 라는 이름으로 넣으면 아바타 화면에 들어갑니다.
(저장소에는 올라가지 않게 막아 두었습니다.)

## 잘 되는지 확인

```bash
curl localhost:8000/readyz
```

`"status": "ready"` 가 나오면 준비된 것입니다. `indexed_chunks` 가 0이면
아직 수집이 안 된 상태이니 `python -m app.cli ingest` 를 먼저 돌리세요.

---

# 자주 막히는 곳

| 증상 | 해결 |
|---|---|
| `python: command not found` | 설치 때 “Add to PATH” 체크를 놓친 경우. 파이썬을 다시 설치하세요 |
| `Activate.ps1 … 차단` | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` 후 다시 |
| `docker: command not found` | Docker Desktop 을 설치하고 **실행**해 두어야 합니다 |
| `readyz` 가 `not_ready` | `.env` 의 `ANTHROPIC_API_KEY` 를 확인하세요 |
| 답변이 전부 “확인되지 않았습니다” | 수집이 안 된 상태입니다. `python -m app.cli ingest` |
