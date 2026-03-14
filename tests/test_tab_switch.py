"""Part 1-4: Tab switching test — browse news, calendar, search, then return to mail.
Part 1-5: UIAutomation for non-browser apps.
"""

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

RESULTS = []


async def push_screen_text(record):
    try:
        async with httpx.AsyncClient() as c:
            r = await c.post(f"{SERVER}/api/v1/push/screen-text",
                             json={"records": [record]}, timeout=10)
            return r.status_code == 200
    except Exception:
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


async def navigate_and_wait(ws, url, rid=100, wait=5):
    await ws.send(json.dumps({"id": rid, "method": "Page.navigate",
                               "params": {"url": url}}))
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


async def test_site(ws, name, url, rid_base):
    """Navigate to a site, extract text, push to server."""
    print(f"\n  [{name}]")
    start = time.time()

    await navigate_and_wait(ws, url, rid=rid_base, wait=5)

    title = await cdp_eval(ws, "document.title", rid=rid_base + 1)
    current_url = await cdp_eval(ws, "window.location.href", rid=rid_base + 2)
    text = await cdp_eval(ws, "document.body.innerText.slice(0, 2000)", rid=rid_base + 3)

    elapsed = time.time() - start
    text_len = len(text) if text else 0

    record = {
        "app_name": name,
        "window_title": title or name,
        "extracted_text": text or "",
        "text_length": text_len,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    pushed = await push_screen_text(record)

    success = text_len > 50
    result = {
        "site": name,
        "url": (current_url or url)[:60],
        "title": (title or "")[:50],
        "text_len": text_len,
        "pushed": pushed,
        "success": success,
        "elapsed_s": round(elapsed, 1),
    }
    RESULTS.append(result)

    status = "OK" if success else "FAIL"
    print(f"    제목: {title or 'N/A'}")
    print(f"    텍스트: {text_len:,}자 | 서버: {'OK' if pushed else 'FAIL'} | {elapsed:.1f}초")
    if text and text_len > 50:
        print(f"    미리보기: \"{text[:100]}...\"")
    print(f"    결과: {status}")

    return success


async def main():
    print("=" * 60)
    print("Part 1-4: 탭 전환 테스트 (뉴스, 캘린더, 검색, 메일 복귀)")
    print(f"시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    r = httpx.get(f"{CDP}/json", timeout=5)
    tabs = [t for t in r.json() if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
    page_tabs = [t for t in tabs if t.get("type") == "page"]
    if not page_tabs:
        print("No page tab found")
        return

    ws_url = page_tabs[0]["webSocketDebuggerUrl"]

    async with websockets.connect(ws_url, close_timeout=15) as ws:
        # 1. 네이버 뉴스 — 실제 업무처럼 뉴스 확인
        print("\n━━━ 뉴스 확인 (실제 업무 시뮬레이션) ━━━")
        await test_site(ws, "네이버 뉴스", "https://news.naver.com/", rid_base=100)

        # 2. Google Calendar — 일정 확인
        print("\n━━━ 일정 확인 ━━━")
        await test_site(ws, "Google Calendar", "https://calendar.google.com/", rid_base=200)

        # 3. Google 검색 — 업무 관련 검색
        print("\n━━━ 업무 검색 ━━━")
        await test_site(ws, "Google 검색",
                       "https://www.google.com/search?q=K-IFRS+제1118호+보험계약+회계기준",
                       rid_base=300)

        # 4. 네이버 검색 — 회계 뉴스
        print("\n━━━ 회계 뉴스 검색 ━━━")
        await test_site(ws, "네이버 검색",
                       "https://search.naver.com/search.naver?query=대웅제약+회계",
                       rid_base=400)

        # 5. 다시 네이버 웍스로 복귀
        print("\n━━━ 네이버 웍스 복귀 ━━━")
        await test_site(ws, "네이버 웍스 복귀",
                       "https://mail.worksmobile.com/w/inbox",
                       rid_base=500)

    # === 결과 집계 ===
    print(f"\n{'═'*60}")
    print("탭 전환 테스트 결과")
    print(f"{'═'*60}")
    success_count = sum(1 for r in RESULTS if r["success"])
    print(f"  전체: {success_count}/{len(RESULTS)} 성공")
    for r in RESULTS:
        s = "OK" if r["success"] else "FAIL"
        print(f"  {r['site']:20s}: {r['text_len']:6,}자  {r['elapsed_s']:5.1f}초  {s}")

    print(f"\n  탭 전환 시 크롤링 정상: {'정상' if success_count >= 3 else '비정상'}")

    # Save
    with open("tests/tab_switch_results.json", "w", encoding="utf-8") as f:
        json.dump(RESULTS, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    asyncio.run(main())
