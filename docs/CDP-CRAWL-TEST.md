# CDP 크롤링 테스트 방법

## 사전 조건

1. Edge를 CDP 모드로 시작 (한번만 하면 됨)
```
# Edge 전부 닫고:
"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --remote-debugging-port=9222
```
또는 `pc-client/start-edge-cdp.bat` 실행

2. 서버 실행
```
cd "C:\Users\user\OneDrive\바탕 화면\Project_jarvis"
.venv\Scripts\activate
python -m server.main
```

3. 네이버 웍스 메일에 로그인된 상태

## 테스트 실행

### 방법 1: 받은메일함 전체 크롤링
```bash
python tests/crawl_inbox.py
```
- 받은메일함의 메일을 하나씩 클릭
- 각 메일의 제목, 발신자, 본문, 첨부파일 추출
- 서버에 자동 전송
- 결과: 성공률, 평균 텍스트 길이, 서버 저장 건수

### 방법 2: 현재 활성 화면 1회 추출
```bash
python -c "
import sys, os, asyncio
sys.path.insert(0, os.path.join(os.getcwd(), 'pc-client'))
sys.stdout.reconfigure(encoding='utf-8')
from crawlers.text_extractor import extract_text

async def main():
    r = await extract_text()
    if r:
        print(f'Source: {r[\"source\"]} | App: {r[\"app_name\"]} | {r[\"text_length\"]} chars')
        print(r['extracted_text'][:500])
asyncio.run(main())
"
```

### 방법 3: 서버에 저장된 데이터 확인
```bash
curl http://localhost:8000/api/v1/data/screen-texts
```

## 예상 결과 (2026-03-14 테스트 기준)

```
받은메일함: 6건 발견

[메일 #1] 제목: [RPA] 휴폐업처 세금계산서 신고 요청 | 1,245자 | OK
[메일 #2] 제목: RE: [개발비] 엔블로멧 자산화 검토의 건 | 1,494자 | OK
[메일 #3] 제목: 회계1팀 주간업무(3월 2주차)          | 1,595자 | OK
[메일 #4] 제목: [회신] AI 교육 참석자 리스트 송부     | 1,048자 | OK
[메일 #5] 제목: [AX INSIGHT] 뉴스레터               | 2,000자 | OK
[메일 #6] 제목: 26.2월 매출대사 공유                  | 2,000자 | OK

성공: 6/6 (100%), 평균 1,563자
```

## 트러블슈팅

| 증상 | 원인 | 해결 |
|------|------|------|
| "No mail tab found" | Edge가 CDP 없이 실행됨 | Edge 닫고 `--remote-debugging-port=9222`로 재시작 |
| "메일 subject 요소 없음" | 페이지 로딩 안 됨 | Edge에서 메일함을 먼저 한번 열어두기 |
| CDP port 연결 안 됨 | 이미 일반 Edge가 실행 중 | 기존 Edge 전부 닫고 CDP로 재시작 |
| 텍스트 추출 실패 | iframe 안의 콘텐츠 | 네이버 웍스는 iframe 없이 동작하므로 보통 발생 안 함 |
