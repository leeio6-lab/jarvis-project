"""Crawl sent mail page 2+ to test pagination."""

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


async def main():
    print("=" * 55)
    print("보낸메일함 2페이지 이후 크롤링")
    print("=" * 55)

    r = httpx.get(f"{CDP}/json", timeout=5)
    tabs = [t for t in r.json()
            if t.get("type") == "page" and
            ("worksmobile" in t.get("url", "") or "메일" in t.get("title", ""))]
    ws_url = tabs[0]["webSocketDebuggerUrl"]

    async with websockets.connect(ws_url, close_timeout=15) as ws:
        await nav(ws, "https://mail.worksmobile.com/w/sent", rid=1, wait=5)

        # Check page info
        page_text = await cdp_eval(ws, "document.body.innerText.slice(0, 3000)", rid=2)
        if page_text:
            # Look for pagination info
            import re
            page_match = re.search(r"(\d+)\s*/\s*(\d+)", page_text)
            if page_match:
                print(f"  페이지: {page_match.group(0)}")

        # Find page navigation elements
        nav_elements = await cdp_eval(ws, """
        (() => {
            const results = [];
            const all = document.querySelectorAll('a, button, [role=button]');
            for (const el of all) {
                const text = el.textContent.trim();
                const title = el.getAttribute('title') || '';
                const cls = el.className || '';
                // Look for page numbers or next/prev buttons
                if (/^\\d+$/.test(text) && parseInt(text) <= 20 && parseInt(text) >= 2) {
                    results.push({type: 'page', num: parseInt(text), tag: el.tagName, cls: cls.slice(0,30)});
                }
                if (title.includes('다음') || text === '다음' || text === '>') {
                    results.push({type: 'next', text: text, title: title, tag: el.tagName});
                }
            }
            return results;
        })()
        """, rid=3)

        if nav_elements:
            print(f"  페이지네이션 요소: {len(nav_elements)}개")
            for el in nav_elements[:5]:
                print(f"    {el}")

            # Try to click page 2
            clicked = await cdp_eval(ws, """
            (() => {
                const all = document.querySelectorAll('a, button');
                for (const el of all) {
                    const text = el.textContent.trim();
                    if (text === '2' && el.closest('[class*=paging], [class*=page], [class*=paginate]')) {
                        el.click();
                        return 'page_2';
                    }
                }
                // Fallback: any element with text "2" near pagination area
                for (const el of all) {
                    const text = el.textContent.trim();
                    const title = el.getAttribute('title') || '';
                    if (title.includes('다음')) {
                        el.click();
                        return 'next';
                    }
                }
                return false;
            })()
            """, rid=4)

            if clicked:
                print(f"\n  페이지 이동: {clicked}")
                await asyncio.sleep(4)

                subjects = await cdp_eval(ws, GET_SUBJECTS_JS, rid=5)
                if subjects:
                    print(f"  2페이지 메일: {len(subjects)}건")
                    success = 0
                    for j, subj in enumerate(subjects[:5]):
                        href = subj.get("href", "")
                        if href and href.startswith("/"):
                            url = f"https://mail.worksmobile.com{href}"
                            await nav(ws, url, rid=100 + j * 10, wait=3)
                            text = await cdp_eval(ws, "document.body.innerText.slice(0, 2000)", rid=100 + j * 10 + 1)
                            title = await cdp_eval(ws, "document.title", rid=100 + j * 10 + 2)
                            if text and len(text) > 50:
                                success += 1
                                record = {
                                    "app_name": "네이버 웍스",
                                    "window_title": f"[보낸p2] {title}",
                                    "extracted_text": text,
                                    "text_length": len(text),
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                }
                                await push(record)
                                ts = datetime.now().strftime("%H:%M:%S")
                                print(f"    [{j+1}] {ts} | {(title or subj['text'])[:40]} | {len(text):,}자")
                            await nav(ws, "https://mail.worksmobile.com/w/sent", rid=100 + j * 10 + 3, wait=3)

                            # Re-navigate to page 2 after going back
                            await cdp_eval(ws, """
                            (() => {
                                const all = document.querySelectorAll('a, button');
                                for (const el of all) {
                                    const text = el.textContent.trim();
                                    if (text === '2' && el.closest('[class*=paging], [class*=page]')) {
                                        el.click();
                                        return true;
                                    }
                                }
                                return false;
                            })()
                            """, rid=100 + j * 10 + 4)
                            await asyncio.sleep(3)

                    print(f"\n  2페이지 크롤링: {success}/{min(len(subjects), 5)}")
                else:
                    print("  2페이지 메일 없음")
            else:
                print("  페이지 이동 불가 (1페이지만 있는 것으로 보임)")
        else:
            print("  페이지네이션 요소 없음 — 보낸메일이 1페이지에 모두 있음")


if __name__ == "__main__":
    asyncio.run(main())
