"""Final crawl: inbox page count + sent mail last pages."""

import asyncio
import json
import re
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
            r = await c.post(
                f"{SERVER}/api/v1/push/screen-text",
                json={"records": [record]}, timeout=10,
            )
            return r.status_code == 200
    except Exception:
        return False


CLICK_PAGE_JS = """
(() => {{
    const els = document.querySelectorAll('a.num, [class*=paging] a');
    for (const el of els) {{
        if (el.textContent.trim() === '{page}') {{ el.click(); return true; }}
    }}
    const nexts = document.querySelectorAll('[class*=paging] a');
    for (const el of nexts) {{
        if ((el.getAttribute('title')||'').includes('\ub2e4\uc74c')) {{ el.click(); return true; }}
    }}
    return false;
}})()
"""

COUNT_SUBJECTS_JS = """
(() => {
    let c = 0;
    document.querySelectorAll('.subject').forEach(el => {
        const t = el.querySelector('.mail_title') || el;
        if (t.textContent.trim().length > 2) c++;
    });
    return c;
})()
"""

GET_SUBJECTS_JS = """
(() => {
    const subs = document.querySelectorAll('.subject');
    const results = [];
    for (const el of subs) {
        const titleEl = el.querySelector('.mail_title') || el.querySelector('.text') || el;
        let text = titleEl.textContent.trim();
        text = text.replace(/^\\ub0b4\\uac00 \\uc218\\uc2e0\\uc778\\uc5d0 \\ud3ec\\ud568\\ub41c \\uba54\\uc77c/, '');
        text = text.replace(/^\\uba54\\uc77c \\uc81c\\ubaa9:/, '').trim();
        if (text.length < 2) continue;
        const link = el.querySelector('a[href]');
        const href = link ? link.getAttribute('href') : '';
        results.push({text: text.slice(0, 80), href: href});
    }
    return results;
})()
"""


async def main():
    r = httpx.get(f"{CDP}/json", timeout=5)
    tabs = [t for t in r.json()
            if t.get("type") == "page" and "worksmobile" in t.get("url", "")]
    ws_url = tabs[0]["webSocketDebuggerUrl"]

    async with websockets.connect(ws_url, close_timeout=15) as ws:
        # === 1. 받은메일함 페이지 수 ===
        print("=== 받은메일함 전체 페이지 수 ===")
        await nav(ws, "https://mail.worksmobile.com/w/inbox", rid=1, wait=5)

        last_inbox = 1
        for page in range(2, 60):
            js = CLICK_PAGE_JS.replace("{page}", str(page))
            clicked = await cdp_eval(ws, js, rid=page * 10)
            if not clicked:
                break
            await asyncio.sleep(1.5)
            count = await cdp_eval(ws, COUNT_SUBJECTS_JS, rid=page * 10 + 1)
            if count and count > 0:
                last_inbox = page
                if page % 10 == 0:
                    print(f"  페이지 {page}: {count}건")
            else:
                break

        print(f"  받은메일함: {last_inbox}페이지 (~{last_inbox * 25}건)")

        # === 2. 보낸메일함 마지막 페이지 메일 열기 ===
        print(f"\n=== 보낸메일함 50~53페이지 실제 크롤링 ===")
        await nav(ws, "https://mail.worksmobile.com/w/sent", rid=2000, wait=5)

        # Navigate to page 50
        for p in range(2, 51):
            js = CLICK_PAGE_JS.replace("{page}", str(p))
            clicked = await cdp_eval(ws, js, rid=2000 + p)
            if not clicked:
                print(f"  {p}페이지 이동 불가")
                return
            await asyncio.sleep(1)

        success = 0
        tried = 0
        for page in range(50, 54):
            await asyncio.sleep(2)
            subjects = await cdp_eval(ws, GET_SUBJECTS_JS, rid=3000 + page * 10)

            if not subjects:
                print(f"  페이지 {page}: 메일 없음")
                break

            print(f"  페이지 {page}: {len(subjects)}건")

            href = subjects[0].get("href", "")
            if href and href.startswith("/"):
                tried += 1
                await nav(ws, f"https://mail.worksmobile.com{href}",
                         rid=4000 + page * 100, wait=3)
                text = await cdp_eval(ws, "document.body.innerText.slice(0, 2000)",
                                     rid=4000 + page * 100 + 1)
                title = await cdp_eval(ws, "document.title",
                                      rid=4000 + page * 100 + 2)
                if text and len(text) > 50:
                    success += 1
                    sender_m = re.search(r"([\w가-힣]+)\s*<", text)
                    sender = sender_m.group(1) if sender_m else ""
                    await push({
                        "app_name": "네이버 웍스",
                        "window_title": f"[보낸p{page}] {title}",
                        "extracted_text": text,
                        "text_length": len(text),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                    ts = datetime.now().strftime("%H:%M:%S")
                    print(f"    {ts} | {(title or '')[:40]} | {sender[:8]} | {len(text):,}자")

                await nav(ws, "https://mail.worksmobile.com/w/sent",
                         rid=4000 + page * 100 + 3, wait=2)
                # Go to next page
                js = CLICK_PAGE_JS.replace("{page}", str(page + 1))
                await cdp_eval(ws, js, rid=4000 + page * 100 + 4)

        if tried:
            print(f"\n  마지막 페이지 크롤링: {success}/{tried} ({success/tried*100:.0f}%)")

    # Final health check
    r = httpx.get(f"{SERVER}/health", timeout=10)
    print(f"\n서버 Health: {r.json()['status']}")


if __name__ == "__main__":
    asyncio.run(main())
