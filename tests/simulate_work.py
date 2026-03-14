"""Simulate realistic workday: browse news, search, check mail, switch tabs."""

import asyncio
import json
import sys
import time
from datetime import datetime, timezone

import httpx
import websockets

sys.stdout.reconfigure(encoding="utf-8")

SERVER = "http://localhost:8000"
CDP = "http://127.0.0.1:9222"
ACTIVITIES = []


async def push(record):
    try:
        async with httpx.AsyncClient() as c:
            r = await c.post(f"{SERVER}/api/v1/push/screen-text",
                             json={"records": [record]}, timeout=10)
            return r.status_code == 200
    except:
        return False


async def cdp_eval(ws, expr, rid=1):
    await ws.send(json.dumps({"id": rid, "method": "Runtime.evaluate",
                               "params": {"expression": expr, "returnByValue": True}}))
    deadline = asyncio.get_event_loop().time() + 15
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            return None
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=remaining))
        if resp.get("id") == rid:
            return resp.get("result", {}).get("result", {}).get("value")


async def nav(ws, url, rid=100, wait=5):
    await ws.send(json.dumps({"id": rid, "method": "Page.navigate", "params": {"url": url}}))
    deadline = asyncio.get_event_loop().time() + 10
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            break
        try:
            resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=remaining))
            if resp.get("id") == rid:
                break
        except asyncio.TimeoutError:
            break
    await asyncio.sleep(wait)
    while True:
        try:
            await asyncio.wait_for(ws.recv(), timeout=0.3)
        except asyncio.TimeoutError:
            break


async def browse_and_record(ws, label, url, rid_base, read_time=10):
    """Visit a page, read it for a while, extract text, push to server."""
    print(f"\n  📖 [{label}]")
    start = time.time()

    await nav(ws, url, rid=rid_base, wait=4)

    title = await cdp_eval(ws, "document.title", rid=rid_base + 1)
    text = await cdp_eval(ws, "document.body.innerText.slice(0, 2000)", rid=rid_base + 2)

    if text and len(text) > 50:
        record = {
            "app_name": label,
            "window_title": title or label,
            "extracted_text": text,
            "text_length": len(text),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        pushed = await push(record)
        elapsed = time.time() - start
        print(f"     제목: {(title or 'N/A')[:50]}")
        print(f"     텍스트: {len(text):,}자 | 서버: {'OK' if pushed else 'FAIL'}")
        print(f"     읽는 시간: {read_time}초...")

        ACTIVITIES.append({
            "label": label,
            "title": (title or "")[:50],
            "chars": len(text),
            "time": round(elapsed, 1),
        })

        # Simulate reading
        await asyncio.sleep(read_time)
    else:
        print(f"     텍스트 추출 실패")


async def ask_jarvis(client, question):
    """Ask JARVIS a question and show the response."""
    print(f"\n  🗣️ \"{question}\"")
    start = time.time()
    r = await client.post(f"{SERVER}/api/v1/command",
                         json={"text": question, "locale": "ko"}, timeout=60)
    elapsed = time.time() - start
    if r.status_code == 200:
        body = r.json()
        reply = body.get("reply", "")
        print(f"     자비스: \"{reply[:150]}{'...' if len(reply) > 150 else ''}\"")
        print(f"     응답: {elapsed:.1f}초")
    else:
        print(f"     에러: {r.status_code}")


async def main():
    start_time = datetime.now()
    print("=" * 60)
    print("실제 업무 시뮬레이션 — 직장인 오후 루틴")
    print(f"시작: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    r = httpx.get(f"{CDP}/json", timeout=5)
    tabs = [t for t in r.json()
            if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
    page_tabs = [t for t in tabs if t.get("type") == "page"]
    ws_url = page_tabs[0]["webSocketDebuggerUrl"]

    async with websockets.connect(ws_url, close_timeout=15) as ws:
        async with httpx.AsyncClient() as client:
            # 1. 오후 시작 — 메일 확인
            print(f"\n{'━'*50}")
            print("📧 오후 업무 시작 — 메일 확인")
            await browse_and_record(ws, "네이버 웍스 메일",
                "https://mail.worksmobile.com/w/inbox", rid_base=100, read_time=5)

            # 2. 자비스에게 오늘 상태 물어보기
            print(f"\n{'━'*50}")
            print("💬 자비스와 대화")
            await ask_jarvis(client, "오늘 뭐했어? 간단히 알려줘")

            # 3. 회계 뉴스 확인 — K-IFRS 관련
            print(f"\n{'━'*50}")
            print("📰 회계 뉴스 확인")
            await browse_and_record(ws, "네이버 뉴스 (K-IFRS)",
                "https://search.naver.com/search.naver?where=news&query=K-IFRS+보험계약+회계기준",
                rid_base=200, read_time=15)

            # 4. 대웅제약 관련 뉴스
            await browse_and_record(ws, "네이버 뉴스 (대웅제약)",
                "https://search.naver.com/search.naver?where=news&query=대웅제약+2026",
                rid_base=300, read_time=15)

            # 5. SAP 관련 검색
            await browse_and_record(ws, "Google 검색 (SAP ZBDC)",
                "https://www.google.com/search?q=SAP+ZBDC+tool+fixed+assets",
                rid_base=400, read_time=10)

            # 6. 자비스에게 뉴스 읽은 거 질문
            print(f"\n{'━'*50}")
            print("💬 자비스와 대화 (뉴스 관련)")
            await ask_jarvis(client, "방금 뉴스에서 봤는데, K-IFRS 1118호 보험계약 기준이 뭐야? 간단히 설명해줘")

            # 7. Google Calendar 확인
            print(f"\n{'━'*50}")
            print("📅 일정 확인")
            await browse_and_record(ws, "Google Calendar",
                "https://calendar.google.com", rid_base=500, read_time=5)

            # 8. 자비스에게 할 일 물어보기
            await ask_jarvis(client, "이번 주 할 일 보여줘")

            # 9. 네이버 웍스로 돌아와서 보낸메일 확인
            print(f"\n{'━'*50}")
            print("📧 보낸메일 확인")
            await browse_and_record(ws, "보낸메일함",
                "https://mail.worksmobile.com/w/sent", rid_base=600, read_time=5)

            # 10. 자비스에게 생산성 물어보기
            print(f"\n{'━'*50}")
            print("💬 자비스에게 생산성 확인")
            await ask_jarvis(client, "오늘 생산성 어때?")

            # 11. 세무 관련 검색 — 실무
            print(f"\n{'━'*50}")
            print("🔍 실무 검색")
            await browse_and_record(ws, "Google 검색 (세금계산서)",
                "https://www.google.com/search?q=세금계산서+전자발행+오류+해결방법",
                rid_base=700, read_time=10)

            # 12. IT뉴스 잠깐 확인
            await browse_and_record(ws, "네이버 IT뉴스",
                "https://news.naver.com/section/105", rid_base=800, read_time=10)

            # 13. 다시 메일로 복귀
            print(f"\n{'━'*50}")
            print("📧 메일로 복귀")
            await browse_and_record(ws, "네이버 웍스 복귀",
                "https://mail.worksmobile.com/w/inbox", rid_base=900, read_time=5)

            # 14. 자비스에게 브리핑 요청
            await ask_jarvis(client, "지금까지 한 거 브리핑 해줘")

    # Summary
    end_time = datetime.now()
    elapsed = (end_time - start_time).total_seconds()

    print(f"\n{'═'*60}")
    print("업무 시뮬레이션 완료")
    print(f"{'═'*60}")
    print(f"  총 활동: {len(ACTIVITIES)}건")
    print(f"  소요시간: {elapsed:.0f}초 ({elapsed/60:.1f}분)")
    for act in ACTIVITIES:
        print(f"    {act['label']:25s} | {act['chars']:5,}자 | {act['time']:.1f}초")

    # Push PC activity records
    print("\n  PC 활동 기록 서버 전송...")
    async with httpx.AsyncClient() as client:
        now = datetime.now(timezone.utc)
        pc_records = []
        from datetime import timedelta as td
        for i, act in enumerate(ACTIVITIES):
            pc_records.append({
                "window_title": act["title"],
                "process_name": "msedge.exe",
                "started_at": (now - td(seconds=elapsed) + td(seconds=i * 30)).isoformat(),
                "ended_at": (now - td(seconds=elapsed) + td(seconds=(i + 1) * 30)).isoformat(),
                "duration_s": 30,
                "idle": False,
            })
        r = await client.post(f"{SERVER}/api/v1/push/pc-activity",
                             json={"activities": pc_records}, timeout=10)
        print(f"  전송 결과: {r.status_code}")


if __name__ == "__main__":
    asyncio.run(main())
