# J.A.R.V.I.S 실사용 연동 가이드

Phase 0~3 구현 완료 후, 실제 API 키를 연결하고 서버+PC 클라이언트를 돌리기 위한 가이드.

---

## 1. API 키 연동 순서

### 1-1. Anthropic API 키 (필수)

모든 AI 기능의 핵심. 브리핑, 대화, 약속 추출, 리포트 생성에 사용.

1. https://console.anthropic.com/ 접속
2. 로그인 → API Keys → Create Key
3. 생성된 `sk-ant-...` 키 복사
4. `.env` 파일에 설정:
   ```
   ANTHROPIC_API_KEY=sk-ant-api03-xxxxxxxxxxxxx
   ```

비용 참고:
- Claude Sonnet (대화/브리핑/리포트): ~$3/MTok input, ~$15/MTok output
- Claude Haiku (약속 추출): ~$0.80/MTok input, ~$4/MTok output
- 일반 사용 시 하루 $0.5~2 수준

### 1-2. Deepgram API 키 (음성 인식용)

녹음 파일 업로드 및 실시간 음성 인식에 사용.

1. https://console.deepgram.com/ 접속
2. 회원가입 (무료 크레딧 $200 제공)
3. Settings → API Keys → Create Key
4. `.env` 파일에 설정:
   ```
   DEEPGRAM_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxx
   ```

Deepgram 없이도 서버는 동작함 (mock 응답 반환). 음성 기능을 쓸 때만 필요.

### 1-3. Picovoice API 키 + 웨이크워드 (PC 음성 트리거용)

"자비스"라고 부르면 음성 대화를 시작하는 기능.

1. https://console.picovoice.ai/ 접속
2. 회원가입 → AccessKey 복사
3. 커스텀 웨이크워드 생성:
   - Picovoice Console → Porcupine → Custom Wake Word
   - Phrase에 `자비스` 입력
   - Platform: `Windows` 선택
   - Train → 다운로드 (.ppn 파일)
4. 다운받은 `.ppn` 파일을 `pc-client/` 디렉토리에 배치
5. `pc-client/config.json` 생성:
   ```json
   {
     "picovoice_access_key": "xxxxxxxxxxxxxxxxxxxxxxxx",
     "wakeword": "자비스"
   }
   ```

Picovoice 없이도 PC 클라이언트는 동작함. 웨이크워드 대신 키보드 입력으로 음성 세션 시작 가능.

### 1-4. Google Cloud OAuth (Gmail + Calendar + Drive)

이메일 미답장 추적, 캘린더 동기화, Drive 저장에 사용.

**Step 1: Google Cloud 프로젝트 생성**

1. https://console.cloud.google.com/ 접속
2. 프로젝트 선택 → 새 프로젝트 → `jarvis` 이름으로 생성

**Step 2: API 활성화**

1. 좌측 메뉴 → API 및 서비스 → 라이브러리
2. 다음 3개 API 검색 후 각각 "사용" 클릭:
   - Gmail API
   - Google Calendar API
   - Google Drive API

**Step 3: OAuth 동의 화면 설정**

1. API 및 서비스 → OAuth 동의 화면
2. User Type: 외부 → 만들기
3. 앱 이름: `J.A.R.V.I.S`
4. 범위 추가:
   - `https://www.googleapis.com/auth/gmail.readonly`
   - `https://www.googleapis.com/auth/calendar.readonly`
   - `https://www.googleapis.com/auth/drive.readonly`
   - `https://www.googleapis.com/auth/drive.file`
5. 테스트 사용자에 본인 Gmail 추가

**Step 4: OAuth 자격증명 생성**

1. API 및 서비스 → 사용자 인증 정보 → 사용자 인증 정보 만들기 → OAuth 클라이언트 ID
2. 애플리케이션 유형: 웹 애플리케이션
3. 승인된 리디렉션 URI: `http://localhost:8000/auth/google/callback`
4. 만들기 → 클라이언트 ID와 클라이언트 보안 비밀번호 복사
5. `.env` 파일에 설정:
   ```
   GOOGLE_CLIENT_ID=xxxxxxxxxxxx.apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=GOCSPX-xxxxxxxxxxxxx
   GOOGLE_REDIRECT_URI=http://localhost:8000/auth/google/callback
   ```

Google 없이도 서버는 동작함 (mock 데이터 반환). 실제 이메일/캘린더 연동 시 필요.

### 최종 `.env` 파일

```bash
# === J.A.R.V.I.S Configuration ===

APP_NAME=J.A.R.V.I.S
APP_ENV=development
APP_PORT=8000
APP_LOCALE=ko

# Claude (필수)
ANTHROPIC_API_KEY=sk-ant-api03-xxxxxxxxxxxxx
CLAUDE_MODEL=claude-sonnet-4-20250514
CLAUDE_MAX_TOKENS=4096

# Deepgram (음성 인식)
DEEPGRAM_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxx

# Google (이메일/캘린더/드라이브)
GOOGLE_CLIENT_ID=xxxxxxxxxxxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-xxxxxxxxxxxxx
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/google/callback

# Database
DATABASE_URL=sqlite+aiosqlite:///./jarvis.db

# JWT
JWT_SECRET_KEY=여기에-랜덤-문자열-32자-이상
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=1440
```

---

## 2. 서버 + PC 클라이언트 실행

### 2-1. 서버 실행

```bash
# 프로젝트 루트에서
cd "C:\Users\user\OneDrive\바탕 화면\Project_jarvis"

# 가상환경 활성화
.venv\Scripts\activate

# .env 파일 확인
cat .env

# 서버 시작
python -m server.main
```

정상 출력:
```
2026-03-14 12:00:00 | INFO | server.main | J.A.R.V.I.S 서버를 시작합니다
INFO:     Uvicorn running on http://0.0.0.0:8000
INFO:     Application startup complete.
```

서버 확인:
```bash
curl http://localhost:8000/health
# → {"status":"ok","version":"0.1.0","message":"시스템 정상 작동 중","pc_connected":false}
```

### 2-2. PC 클라이언트 실행 (새 터미널)

```bash
# 새 터미널 열기
cd "C:\Users\user\OneDrive\바탕 화면\Project_jarvis"
.venv\Scripts\activate

# PC 클라이언트 시작
python pc-client/main.py
```

정상 출력:
```
J.A.R.V.I.S PC Client starting...
Server connection OK: http://localhost:8000
Window tracker started (interval=5.0s)
PC Client running. Press Ctrl+C to stop.
```

### 2-3. 연동 확인

```bash
curl http://localhost:8000/health
# → {"status":"ok","version":"0.1.0","message":"시스템 정상 작동 중","pc_connected":true}
#                                                                      ^^^^^^^^^^^^^^
# pc_connected가 true로 바뀌면 WebSocket 연동 성공
```

---

## 3. 첫 실사용 테스트 체크리스트

아래 순서대로 하나씩 확인. 각 단계에서 문제가 있으면 해당 항목의 트러블슈팅을 참고.

### 체크 1: PC 활동 추적 확인

PC 클라이언트 실행 후 1분 대기. 그 동안 VSCode, 브라우저 등을 전환해 봄.

```bash
curl http://localhost:8000/api/v1/data/activity/summary
```

`total_active_s`가 0보다 크면 성공. `pc.apps`에 사용한 프로그램이 보여야 함.

문제 시: PC 클라이언트 로그에서 "Window tracker started" 확인. `sync_interval`(기본 60초) 후 데이터가 서버에 전송됨.

### 체크 2: 대화 테스트

```bash
curl -X POST http://localhost:8000/api/v1/command ^
  -H "Content-Type: application/json" ^
  -d "{\"text\": \"안녕하세요\", \"locale\": \"ko\"}"
```

`[MOCK]`이 아닌 실제 Claude 응답이 오면 Anthropic 키 연동 성공.

### 체크 3: 캘린더 기반 답변

Google OAuth가 설정되지 않았으면 mock 데이터 기반으로 응답함. 실제 연동은 온보딩 과정 후:

```bash
curl -X POST http://localhost:8000/api/v1/command ^
  -H "Content-Type: application/json" ^
  -d "{\"text\": \"오늘 일정 알려줘\", \"locale\": \"ko\"}"
```

### 체크 4: 브리핑 생성

```bash
curl -X POST http://localhost:8000/api/v1/data/briefing ^
  -H "Content-Type: application/json" ^
  -d "{\"type\": \"morning\", \"locale\": \"ko\"}"
```

`content` 필드에 실제 브리핑 텍스트가 나오면 성공. PC 활동 데이터가 있으면 브리핑에 포함됨.

### 체크 5: "오늘 뭐했어?" 종합 답변

```bash
curl -X POST http://localhost:8000/api/v1/command ^
  -H "Content-Type: application/json" ^
  -d "{\"text\": \"오늘 뭐했어?\", \"locale\": \"ko\"}"
```

오케스트레이터가 활동 데이터를 조회해서 답변해야 함.

### 체크 6: 녹음 파일 업로드 → 전사 + 약속 추출

테스트용 WAV 파일이 있으면:

```bash
curl -X POST http://localhost:8000/api/v1/upload/audio ^
  -F "file=@recording.wav" ^
  -F "source=mic" ^
  -F "language=ko"
```

Deepgram 키가 있으면 실제 전사. 없으면 mock 응답. `promises` 배열에 추출된 약속이 나오면 파이프라인 동작 확인.

### 체크 7: 생산성 점수

```bash
curl http://localhost:8000/api/v1/data/productivity/score
```

`score`, `grade`, `insights`가 나오면 성공.

### 체크 8: 프로액티브 알림

수동 트리거:
```bash
curl -X POST http://localhost:8000/api/v1/data/proactive/check
```

미답장 이메일이나 마감 임박 할 일이 있으면 `alerts`에 표시됨.

### 체크 9: 웨이크워드 음성 대화 (Picovoice 설정 후)

1. PC 클라이언트가 실행 중인 상태에서
2. "자비스"라고 말하기
3. "네, 말씀하세요" 응답 후 질문
4. 응답이 TTS로 재생되면 성공

Picovoice 미설정 시 이 체크는 건너뛰기.

---

## 4. 트러블슈팅

| 증상 | 원인 | 해결 |
|------|------|------|
| `[MOCK]` 응답만 나옴 | API 키 미설정 | `.env`에 `ANTHROPIC_API_KEY` 확인 |
| PC 활동이 안 보임 | 동기화 대기 중 | 1분 대기 후 재확인 (기본 sync_interval=60s) |
| `pc_connected: false` | WebSocket 미연결 | PC 클라이언트 로그에서 WebSocket 에러 확인. `websockets` 패키지 설치: `pip install websockets` |
| Google API 에러 | OAuth 미완료 | 섹션 1-4 Google Cloud 설정 확인 |
| pyaudio ImportError | 빌드 도구 필요 | `pip install pipwin && pipwin install pyaudio` |
| edge-tts 음성 안 나옴 | 재생기 없음 | ffmpeg 설치: https://ffmpeg.org/download.html |
| 서버 시작 실패 | 포트 충돌 | `.env`에서 `APP_PORT=8001` 등으로 변경 |

---

## 5. 다음 단계

실사용 테스트가 완료되면:

1. **API 키 실연동** 후 실제 데이터로 브리핑/리포트 품질 확인
2. **Google OAuth 연동** 후 실제 이메일/캘린더 데이터로 테스트
3. **하루 종일 PC 클라이언트 돌리기** → 저녁에 이브닝 서머리 확인
4. **녹음 파일 올려보기** → 약속 추출 정확도 확인
5. Phase 4 (Flutter 모바일 앱) 진행 여부 결정
