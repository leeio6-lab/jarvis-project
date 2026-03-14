"""Crawl custom folders, all-mail, drafts, spam — Part 1-3."""

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
RESULTS = {"all": 0, "custom": 0, "drafts": 0, "spam": 0}
TRIED = {"all": 0, "custom": 0, "drafts": 0, "spam": 0}


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


async def crawl_mails(ws, folder_name, folder_key, subjects, max_mails=5, rid_base=100):
    """Open mails and extract text."""
    for j, subj in enumerate(subjects[:max_mails]):
        TRIED[folder_key] += 1
        href = subj.get("href", "")
        if href and href.startswith("/"):
            mail_url = f"https://mail.worksmobile.com{href}"
            await nav(ws, mail_url, rid=rid_base + j * 10, wait=3)
        else:
            print(f"    [{j+1}] href 없음: {subj['text'][:35]}")
            continue

        text = await cdp_eval(ws, "document.body.innerText.slice(0, 2000)", rid=rid_base + j * 10 + 1)
        title = await cdp_eval(ws, "document.title", rid=rid_base + j * 10 + 2)

        if text and len(text) > 50:
            RESULTS[folder_key] += 1
            record = {
                "app_name": "네이버 웍스",
                "window_title": f"[{folder_name}] {title or subj['text']}",
                "extracted_text": text,
                "text_length": len(text),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            pushed = await push(record)
            sender_match = re.search(r"([\w가-힣]+)\s*<", text)
            sender = sender_match.group(1) if sender_match else ""
            ts = datetime.now().strftime("%H:%M:%S")
            print(f"    [{j+1}] {ts} | {(title or subj['text'])[:40]} | {sender[:8]} | {len(text):,}자")
        else:
            print(f"    [{j+1}] 텍스트 추출 실패 ({len(text or '')}자)")


async def main():
    start = datetime.now()
    print("=" * 60)
    print("Part 1-3: 전체메일함 + 모든 폴더 크롤링")
    print(f"시작: {start.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    r = httpx.get(f"{CDP}/json", timeout=5)
    tabs = [t for t in r.json()
            if t.get("type") == "page" and
            ("worksmobile" in t.get("url", "") or "메일" in t.get("title", ""))]
    if not tabs:
        print("No mail tab")
        return

    ws_url = tabs[0]["webSocketDebuggerUrl"]

    async with websockets.connect(ws_url, close_timeout=15) as ws:
        # ── 전체메일함 ──
        print(f"\n{'━'*50}")
        print("📂 [전체메일함]")
        await nav(ws, "https://mail.worksmobile.com/w/all", rid=1, wait=5)
        subjects = await cdp_eval(ws, GET_SUBJECTS_JS, rid=2)
        if subjects:
            print(f"  {len(subjects)}건 발견")
            await crawl_mails(ws, "전체메일함", "all", subjects, max_mails=10, rid_base=100)
            # Go back
            await nav(ws, "https://mail.worksmobile.com/w/inbox", rid=50, wait=3)
        else:
            print("  메일 없음")

        # ── 임시보관함 ──
        print(f"\n{'━'*50}")
        print("📂 [임시보관함]")
        await nav(ws, "https://mail.worksmobile.com/w/draft", rid=300, wait=4)
        subjects = await cdp_eval(ws, GET_SUBJECTS_JS, rid=301)
        if subjects:
            print(f"  {len(subjects)}건 발견")
            await crawl_mails(ws, "임시보관함", "drafts", subjects, max_mails=5, rid_base=400)
        else:
            print("  메일 없음")

        # ── 스팸함 ──
        print(f"\n{'━'*50}")
        print("📂 [스팸함]")
        await nav(ws, "https://mail.worksmobile.com/w/spam", rid=500, wait=4)
        subjects = await cdp_eval(ws, GET_SUBJECTS_JS, rid=501)
        if subjects:
            print(f"  {len(subjects)}건 발견")
            await crawl_mails(ws, "스팸함", "spam", subjects, max_mails=5, rid_base=600)
        else:
            print("  메일 없음")

        # ── 커스텀 폴더 ──
        print(f"\n{'━'*50}")
        print("📂 [커스텀 폴더 탐색]")
        await nav(ws, "https://mail.worksmobile.com/w/inbox", rid=700, wait=4)

        # Expand folder tree
        await cdp_eval(ws, """
        (() => {
            const btns = document.querySelectorAll('[class*=toggle], [class*=btn_fold], button');
            let count = 0;
            btns.forEach(b => {
                const t = b.getAttribute('title') || b.getAttribute('aria-label') || b.textContent;
                if (t && (t.includes('열기') || t.includes('펼치기') || t.includes('하위'))) {
                    b.click(); count++;
                }
            });
            return count;
        })()
        """, rid=701)
        await asyncio.sleep(2)

        # Find custom folder links
        folders = await cdp_eval(ws, """
        (() => {
            const links = [];
            document.querySelectorAll('a').forEach(a => {
                const href = a.getAttribute('href') || '';
                const text = a.textContent.trim();
                if (href.includes('/w/folder/') && text.length > 0 && text.length < 30) {
                    links.push({name: text, href: href});
                }
            });
            return links;
        })()
        """, rid=702)

        if not folders:
            # Fallback: find by known names
            known = ["고정자산", "IO코드", "생성완료", "매각 폐기",
                     "장기미대체자산", "기타무형자산", "건중홍보",
                     "자료요청", "지급", "계좌모니터링", "채권채무 조회서"]
            print("  링크 감지 실패. 사이드바 텍스트에서 폴더 검색...")
            sidebar = await cdp_eval(ws, "document.body.innerText.slice(0, 2500)", rid=703)
            found = [f for f in known if f in (sidebar or "")]
            print(f"  발견: {', '.join(found) if found else '없음'}")

            for idx, fname in enumerate(found[:7]):
                print(f"\n  [{fname}]")
                # Click folder in sidebar
                clicked = await cdp_eval(ws, f"""
                (() => {{
                    const els = document.querySelectorAll('a, span');
                    for (const el of els) {{
                        if (el.textContent.trim() === '{fname}') {{
                            el.click();
                            return true;
                        }}
                    }}
                    return false;
                }})()
                """, rid=800 + idx * 10)

                if clicked:
                    await asyncio.sleep(4)
                    subjects = await cdp_eval(ws, GET_SUBJECTS_JS, rid=800 + idx * 10 + 1)
                    if subjects:
                        print(f"    {len(subjects)}건 발견")
                        await crawl_mails(ws, fname, "custom", subjects, max_mails=3,
                                         rid_base=900 + idx * 100)
                    else:
                        print(f"    메일 없음")
                    await nav(ws, "https://mail.worksmobile.com/w/inbox", rid=800 + idx * 10 + 5, wait=3)
                else:
                    print(f"    클릭 실패")
        else:
            print(f"  커스텀 폴더 {len(folders)}개:")
            for f in folders:
                print(f"    - {f['name']}")

            for idx, folder in enumerate(folders[:10]):
                fname = folder["name"]
                fhref = folder["href"]
                furl = f"https://mail.worksmobile.com{fhref}" if fhref.startswith("/") else fhref

                print(f"\n  [{fname}]")
                await nav(ws, furl, rid=1000 + idx * 50, wait=4)
                subjects = await cdp_eval(ws, GET_SUBJECTS_JS, rid=1000 + idx * 50 + 1)
                if subjects:
                    print(f"    {len(subjects)}건 발견")
                    await crawl_mails(ws, fname, "custom", subjects, max_mails=3,
                                     rid_base=1100 + idx * 100)
                else:
                    print(f"    메일 없음")

    # Summary
    end = datetime.now()
    elapsed = (end - start).total_seconds()
    print(f"\n{'═'*60}")
    print("폴더별 크롤링 결과")
    print(f"{'═'*60}")
    for key in ["all", "drafts", "spam", "custom"]:
        if TRIED[key] > 0:
            pct = RESULTS[key] / TRIED[key] * 100
            print(f"  {key:10s}: {RESULTS[key]}/{TRIED[key]} ({pct:.0f}%)")
        else:
            print(f"  {key:10s}: 메일 없음")
    total = sum(RESULTS.values())
    total_t = sum(TRIED.values())
    if total_t:
        print(f"\n  합계: {total}/{total_t} ({total/total_t*100:.0f}%)")
    print(f"  소요: {elapsed:.0f}초")


if __name__ == "__main__":
    asyncio.run(main())
