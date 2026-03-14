"""Deep crawl: open mails from pages 2+ in inbox and sent folders."""

import asyncio
import json
import re
import sys
from datetime import datetime, timezone

import httpx
import websockets

sys.stdout.reconfigure(encoding="utf-8")

SERVER = "http://localhost:8000"
CDP = "http://127.0.0.1:9222"
STATS = {"inbox": {"tried": 0, "success": 0, "chars": 0},
         "sent": {"tried": 0, "success": 0, "chars": 0}}


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


GET_SUBJECTS_JS = """
(() => {
    const subs = document.querySelectorAll('.subject');
    const results = [];
    for (const el of subs) {
        const titleEl = el.querySelector('.mail_title') || el.querySelector('.text') || el;
        let text = titleEl.textContent.trim();
        text = text.replace(/^내가 수신인에 포함된 메일/, '').replace(/^메일 제목:/, '').trim();
        if (text.length < 2) continue;
        const link = el.querySelector('a[href]');
        const href = link ? link.getAttribute('href') : '';
        results.push({text: text.slice(0, 80), href: href});
    }
    return results;
})()
"""


async def click_page(ws, page_num, rid):
    """Click a page number or next button."""
    return await cdp_eval(ws, f"""
    (() => {{
        const els = document.querySelectorAll('a.num, [class*=paging] a');
        for (const el of els) {{
            if (el.textContent.trim() === '{page_num}') {{
                el.click();
                return 'page_{page_num}';
            }}
        }}
        const nexts = document.querySelectorAll('[class*=paging] a, button');
        for (const el of nexts) {{
            const title = el.getAttribute('title') || '';
            if (title.includes('다음')) {{
                el.click();
                return 'next';
            }}
        }}
        return false;
    }})()
    """, rid=rid)


async def crawl_pages(ws, folder_name, folder_key, base_url, start_page, end_page, mails_per_page, rid_base):
    """Crawl mails from specific pages."""
    print(f"\n{'━'*55}")
    print(f"📂 [{folder_name}] 페이지 {start_page}~{end_page} 크롤링")
    print(f"{'━'*55}")

    await nav(ws, base_url, rid=rid_base, wait=5)

    for page in range(start_page, end_page + 1):
        if page > 1:
            clicked = await click_page(ws, page, rid=rid_base + page * 100)
            if not clicked:
                print(f"  페이지 {page}: 이동 불가")
                break
            await asyncio.sleep(3)

        subjects = await cdp_eval(ws, GET_SUBJECTS_JS, rid=rid_base + page * 100 + 1)
        if not subjects:
            print(f"  페이지 {page}: 메일 없음")
            break

        print(f"\n  ── 페이지 {page} ({len(subjects)}건) ──")

        for j, subj in enumerate(subjects[:mails_per_page]):
            STATS[folder_key]["tried"] += 1
            href = subj.get("href", "")
            if not href or not href.startswith("/"):
                continue

            mail_url = f"https://mail.worksmobile.com{href}"
            await nav(ws, mail_url, rid=rid_base + page * 1000 + j * 10, wait=3)

            text = await cdp_eval(ws, "document.body.innerText.slice(0, 2000)",
                                 rid=rid_base + page * 1000 + j * 10 + 1)
            title = await cdp_eval(ws, "document.title",
                                  rid=rid_base + page * 1000 + j * 10 + 2)

            if text and len(text) > 50:
                STATS[folder_key]["success"] += 1
                STATS[folder_key]["chars"] += len(text)

                sender_match = re.search(r"([\w가-힣]+)\s*<", text)
                sender = sender_match.group(1) if sender_match else ""

                record = {
                    "app_name": "네이버 웍스",
                    "window_title": f"[{folder_name} p{page}] {title or subj['text']}",
                    "extracted_text": text,
                    "text_length": len(text),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                await push(record)

                ts = datetime.now().strftime("%H:%M:%S")
                print(f"    [{j+1}] {ts} | {(title or subj['text'])[:38]} | {sender[:8]} | {len(text):,}자")
            else:
                print(f"    [{j+1}] 추출 실패")

            # Go back to the folder
            await nav(ws, base_url, rid=rid_base + page * 1000 + j * 10 + 3, wait=2)
            # Re-navigate to the current page
            if page > 1:
                await click_page(ws, page, rid=rid_base + page * 1000 + j * 10 + 4)
                await asyncio.sleep(2)


async def main():
    start = datetime.now()
    print("=" * 60)
    print("Deep Crawl: 받은메일함 + 보낸메일함 다중 페이지")
    print(f"시작: {start.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    r = httpx.get(f"{CDP}/json", timeout=5)
    tabs = [t for t in r.json()
            if t.get("type") == "page" and
            ("worksmobile" in t.get("url", "") or "메일" in t.get("title", ""))]
    ws_url = tabs[0]["webSocketDebuggerUrl"]

    async with websockets.connect(ws_url, close_timeout=15) as ws:
        # Sent mail: pages 3-6, 3 mails each
        await crawl_pages(ws, "보낸메일함", "sent",
                         "https://mail.worksmobile.com/w/sent",
                         start_page=3, end_page=6, mails_per_page=3,
                         rid_base=10000)

        # 중간에 뉴스 확인 (업무 시뮬레이션)
        print(f"\n{'━'*55}")
        print("📰 업무 중 뉴스 확인")
        await nav(ws, "https://news.naver.com/section/101", rid=50000, wait=5)
        text = await cdp_eval(ws, "document.body.innerText.slice(0, 2000)", rid=50001)
        if text:
            await push({
                "app_name": "네이버 경제뉴스",
                "window_title": "네이버 경제뉴스",
                "extracted_text": text,
                "text_length": len(text),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            print(f"  경제뉴스: {len(text):,}자 추출 | OK")

        # Sent mail: pages 7-10, 2 mails each
        await crawl_pages(ws, "보낸메일함", "sent",
                         "https://mail.worksmobile.com/w/sent",
                         start_page=7, end_page=10, mails_per_page=2,
                         rid_base=30000)

    # Summary
    end = datetime.now()
    elapsed = (end - start).total_seconds()
    print(f"\n{'═'*60}")
    print("Deep Crawl 결과")
    print(f"{'═'*60}")
    for key in ["inbox", "sent"]:
        s = STATS[key]
        if s["tried"]:
            pct = s["success"] / s["tried"] * 100
            avg = s["chars"] // s["success"] if s["success"] else 0
            print(f"  {key:10s}: {s['success']}/{s['tried']} ({pct:.0f}%) 평균 {avg:,}자")
    total_s = sum(s["success"] for s in STATS.values())
    total_t = sum(s["tried"] for s in STATS.values())
    if total_t:
        print(f"\n  합계: {total_s}/{total_t} ({total_s/total_t*100:.0f}%)")
    print(f"  소요: {elapsed:.0f}초 ({elapsed/60:.1f}분)")


if __name__ == "__main__":
    asyncio.run(main())
