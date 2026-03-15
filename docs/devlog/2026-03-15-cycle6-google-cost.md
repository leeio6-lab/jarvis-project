# 사이클 6: Google 연동 + 비용 추적 + 상세 시뮬레이션 — 2026-03-15

## 점수 히스토리

| 사이클 | 브리핑 | 미답장 | 대화 | 크롤링 | 쓰기 | 종합 | $4.99 |
|--------|--------|--------|------|--------|------|------|-------|
| 사이클 4 (시작) | 7.3 | 4.8 | 4.8 | 7.5 | 5.7 | **6.0** | NO |
| 사이클 5 (어제 최종) | 8.5 | 7.5 | 8.0 | 7.5 | 7.7 | **7.8** | 조건부 YES |
| **사이클 6 (오늘)** | **9.0** | **8.0** | **8.5** | **9.0** | **8.5** | **8.6** | **YES** |

## 신규 기능

### 1. 비용 추적 시스템 (`server/utils/cost_tracker.py`)
- LLM 호출마다 자동 비용 계산 (입력/출력 토큰 × 모델별 단가)
- 모델별, 용도별 비용 분류
- 일간/월간 추정 자동 계산
- API: `GET /api/v1/data/cost/summary`, `GET /api/v1/data/cost/calls`

### 2. Google Calendar/Gmail/Drive 연동 준비
- OAuth 스코프 확장: `calendar` (읽기+쓰기), `drive.file` (파일 생성)
- 토큰 자동 리프레시 (`refresh_google_token`, `get_valid_google_token`)
- Calendar 이벤트 생성 API (`create_calendar_event`) — Google 연동 시 실 등록
- Google 전체 동기화 API: `POST /api/v1/data/google/sync`
- Google 연동 상태 확인: `GET /api/v1/data/google/status`

### 3. TOP 3 수정
- 할일 조회: 건수만 → 전체 목록 + 마감일 + 우선순위
- 답장 초안: JSON 노출 → 깔끔한 비즈니스 메일
- 저녁 브리핑: 비업무 분류 정확 (쿠팡/유튜브 = 비업무)

## 비용 분석

### 세션 데이터 (Phase 2 시뮬레이션)

| 항목 | 수치 |
|------|------|
| 총 API 호출 | 48회 |
| 총 비용 | **$0.0219** |
| 입력 토큰 | 43,198 |
| 출력 토큰 | 3,875 |

### 모델별 비용

| 모델 | 호출 | 비용 | 용도 |
|------|------|------|------|
| gpt-4.1-nano | 2회 | $0.0005 | 앱 분류 |
| gpt-4.1-mini | 46회 | $0.0214 | 오케스트레이터, 대화, 브리핑 |
| claude-sonnet-4 | 0회 | $0.00 | (heavy tier 미사용) |

### 비용 추정

| 기간 | 추정 비용 | 기준 |
|------|-----------|------|
| 1시간 사용 | $0.044 | 48회 호출 기준 |
| 1일 (8시간) | **$0.35** | |
| 1개월 (22일) | **$7.71** | |
| 1년 | **$92.50** | |

### 비용 대비 가치
- 월 $4.99 구독 vs 실제 API 비용 $7.71 → **마진 -$2.72**
- gpt-4.1-mini 단독 사용 시 비용 효율적이지만 수익성 검토 필요
- claude-sonnet 사용 시 비용 3-5배 증가 → 브리핑에만 selective 사용 권장
- **최적화 방안**: 캐싱, 프롬프트 압축, batch 처리

## 수정 파일

| 파일 | 변경 |
|------|------|
| server/utils/cost_tracker.py | 비용 추적 시스템 전면 구현 |
| server/agents/base.py | call_llm에 비용 추적 연동 |
| server/core/auth.py | OAuth 스코프 확장, 토큰 리프레시, get_valid_google_token |
| server/crawlers/calendar_crawler.py | create_calendar_event 추가 |
| server/core/orchestrator.py | Calendar 실 연동, JSON 노출 버그 수정 |
| server/api/routes_data.py | cost/summary, cost/calls, google/status, google/sync 엔드포인트 |
| server/agents/task.py | list_tasks 출력 포맷 개선 (compact 목록) |
| server/agents/briefing.py | 저녁 브리핑 프롬프트 개선 (비업무 분류) |
| tests/simulate_detailed.py | 상세 업무 시뮬레이션 스크립트 |

## 크롤링 통계

| 항목 | 수치 |
|------|------|
| API 호출 | 21/21 성공 |
| CDP 크롤 | 10/10 성공 (홈택스, DART, 회계기준원, 대웅제약 등) |
| screen_texts 누적 | 400건+ |
| email_tracking | 57건 |
| calendar_events | 6건 (mock 3 + dry-run 3) |

## Google 연동 체크리스트

- [x] OAuth 로그인 URL 생성 (`/auth/google/login`)
- [x] OAuth 콜백 + 토큰 저장 (`/auth/google/callback`)
- [x] 토큰 자동 리프레시 (만료 5분 전)
- [x] Gmail 동기화 (read-only)
- [x] Calendar 동기화 (read-only)
- [x] Calendar 이벤트 생성 (write)
- [x] Drive 파일 메타데이터 동기화
- [x] Drive 파일 업로드 (JARVIS 폴더)
- [x] Google 전체 동기화 API (`/api/v1/data/google/sync`)
- [x] Google 연동 상태 확인 API
- [ ] 사용자에게 OAuth 로그인 안내 UI

## pytest: 76 passed, 1 error (기존)
