"""Crawl remaining custom folders: 자료요청, 지급, 계좌모니터링, 채권채무."""

import asyncio
import json
import sys
from datetime import datetime, timezone

import httpx
import websockets

sys.stdout.reconfigure(encoding="utf-8")

CDP = "http://127.0.0.1:9222"
SERVER = "http://localhost:8000"


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


async def push(record):
    try:
        async with httpx.AsyncClient() as c:
            r = await c.post(f"{SERVER}/api/v1/push/screen-text",
                             json={"records": [record]}, timeout=10)
            return r.status_code == 200
    except Exception:
        return False


async def main():
    print("=== 나머지 커스텀 폴더 크롤링 ===")
    r = httpx.get(f"{CDP}/json", timeout=5)
    tabs = [t for t in r.json()
            if t.get("type") == "page" and "worksmobile" in t.get("url", "")]
    ws_url = tabs[0]["webSocketDebuggerUrl"]

    folders_to_check = ["자료요청", "지급", "계좌모니터링", "채권채무 조회서"]
    success = 0
    tried = 0

    async with websockets.connect(ws_url, close_timeout=15) as ws:
        for fname in folders_to_check:
            await nav(ws, "https://mail.worksmobile.com/w/inbox", rid=1000, wait=3)

            # Expand folder tree
            await cdp_eval(ws, """
            (() => {
                document.querySelectorAll('[class*=toggle], button').forEach(b => {
                    const t = b.getAttribute('title') || '';
                    if (t.includes('열기') || t.includes('하위')) b.click();
                });
            })()
            """, rid=1001)
            await asyncio.sleep(2)

            # Click the folder by name
            click_js = (
                "(() => {"
                "  const els = document.querySelectorAll('a, span');"
                "  for (const el of els) {"
                f"    if (el.textContent.trim() === '{fname}') {{"
                "      el.click(); return true;"
                "    }"
                "  }"
                "  return false;"
                "})()"
            )
            clicked = await cdp_eval(ws, click_js, rid=1002)

            if not clicked:
                print(f"  [{fname}] 클릭 실패")
                continue

            await asyncio.sleep(4)

            subjects = await cdp_eval(ws, """
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
            """, rid=1003)

            if not subjects:
                print(f"  [{fname}] 메일 없음")
                continue

            print(f"  [{fname}] {len(subjects)}건")

            for j, subj in enumerate(subjects[:2]):
                tried += 1
                href = subj.get("href", "")
                if href and href.startswith("/"):
                    await nav(ws, f"https://mail.worksmobile.com{href}",
                             rid=2000 + j * 10, wait=3)
                    text = await cdp_eval(ws, "document.body.innerText.slice(0, 2000)",
                                         rid=2000 + j * 10 + 1)
                    title = await cdp_eval(ws, "document.title",
                                          rid=2000 + j * 10 + 2)
                    if text and len(text) > 50:
                        success += 1
                        await push({
                            "app_name": "네이버 웍스",
                            "window_title": f"[{fname}] {title}",
                            "extracted_text": text,
                            "text_length": len(text),
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        })
                        ts = datetime.now().strftime("%H:%M:%S")
                        print(f"    [{j+1}] {ts} | {(title or subj['text'])[:40]} | {len(text):,}자")

    if tried:
        print(f"\n결과: {success}/{tried} ({success/tried*100:.0f}%)")
    else:
        print("\n시도 없음")


if __name__ == "__main__":
    asyncio.run(main())
