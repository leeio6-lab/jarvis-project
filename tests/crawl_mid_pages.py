"""Crawl sent mail pages 30-40."""

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


CLICK_JS = """
(() => {{
    const els = document.querySelectorAll('a.num, [class*=paging] a');
    for (const el of els) {{
        if (el.textContent.trim() === '{p}') {{ el.click(); return true; }}
    }}
    const nexts = document.querySelectorAll('[class*=paging] a');
    for (const el of nexts) {{
        if ((el.getAttribute('title')||'').includes('\ub2e4\uc74c')) {{ el.click(); return true; }}
    }}
    return false;
}})()
"""

GET_SUBJECTS = """
(() => {
    const subs = document.querySelectorAll('.subject');
    const results = [];
    for (const el of subs) {
        const titleEl = el.querySelector('.mail_title') || el.querySelector('.text') || el;
        let text = titleEl.textContent.trim();
        text = text.replace(/^내가 수신인에 포함된 메일/, '').replace(/^메일 제목:/, '').trim();
        if (text.length < 2) continue;
        const link = el.querySelector('a[href]');
        results.push({text: text.slice(0, 80), href: link ? link.getAttribute('href') : ''});
    }
    return results;
})()
"""


async def main():
    print("=== 보낸메일 30~40페이지 크롤링 ===")
    r = httpx.get(f"{CDP}/json", timeout=5)
    tabs = [t for t in r.json()
            if t.get("type") == "page" and "worksmobile" in t.get("url", "")]
    ws_url = tabs[0]["webSocketDebuggerUrl"]

    success = 0
    tried = 0

    async with websockets.connect(ws_url, close_timeout=15) as ws:
        await nav(ws, "https://mail.worksmobile.com/w/sent", rid=1, wait=5)

        # Navigate to page 30
        for p in range(2, 31):
            js = CLICK_JS.replace("{p}", str(p))
            await cdp_eval(ws, js, rid=p * 10)
            await asyncio.sleep(1)

        for page in range(30, 41):
            await asyncio.sleep(2)
            subjects = await cdp_eval(ws, GET_SUBJECTS, rid=page * 100)

            if not subjects:
                break

            href = subjects[0].get("href", "")
            if href and href.startswith("/"):
                tried += 1
                await nav(ws, f"https://mail.worksmobile.com{href}",
                         rid=page * 100 + 10, wait=3)
                text = await cdp_eval(ws, "document.body.innerText.slice(0, 2000)",
                                     rid=page * 100 + 11)
                title = await cdp_eval(ws, "document.title",
                                      rid=page * 100 + 12)
                if text and len(text) > 50:
                    success += 1
                    await push({
                        "app_name": "네이버 웍스",
                        "window_title": f"[보낸p{page}] {title}",
                        "extracted_text": text,
                        "text_length": len(text),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                    ts = datetime.now().strftime("%H:%M:%S")
                    print(f"  p{page}: {ts} | {(title or '')[:40]} | {len(text):,}자")

                await nav(ws, "https://mail.worksmobile.com/w/sent",
                         rid=page * 100 + 13, wait=2)
                js = CLICK_JS.replace("{p}", str(page + 1))
                await cdp_eval(ws, js, rid=page * 100 + 14)

    print(f"\n30~40페이지: {success}/{tried}")


if __name__ == "__main__":
    asyncio.run(main())
