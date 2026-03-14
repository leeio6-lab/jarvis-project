"""Comprehensive crawl: 받은메일함 + 보낸메일함 전체 순회 (모든 페이지, 다음 버튼 포함)."""

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

RESULTS = {}


def init_folder(key):
    if key not in RESULTS:
        RESULTS[key] = {"tried": 0, "success": 0, "chars": 0, "mails": []}


async def push(record):
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
    # Read responses until we get the one matching our request id
    deadline = asyncio.get_event_loop().time() + 15
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            return None
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=remaining))
        if resp.get("id") == rid:
            return resp.get("result", {}).get("result", {}).get("value")
        # Skip CDP events (no "id" field) or responses for other requests


async def navigate_and_wait(ws, url, rid=100, wait=5):
    await ws.send(json.dumps({"id": rid, "method": "Page.navigate",
                               "params": {"url": url}}))
    # Read until we get our navigate response
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
    # Drain any queued CDP events
    while True:
        try:
            await asyncio.wait_for(ws.recv(), timeout=0.3)
        except asyncio.TimeoutError:
            break


async def get_mail_subjects(ws, rid_base, max_count=30):
    """Get mail subjects from the list (not navigation elements)."""
    for attempt in range(5):
        count = await cdp_eval(ws, "document.querySelectorAll('.subject').length", rid=rid_base)
        if count and count > 0:
            break
        await asyncio.sleep(2)

    subjects_js = f"""
    (() => {{
        const subs = document.querySelectorAll('.subject');
        const results = [];
        for (let i = 0; i < Math.min(subs.length, {max_count}); i++) {{
            const el = subs[i];
            // Use mail_title span text if available, otherwise full text
            const titleEl = el.querySelector('.mail_title') || el.querySelector('.text') || el;
            let text = titleEl.textContent.trim();
            // Strip accessibility prefixes
            text = text.replace(/^내가 수신인에 포함된 메일/, '').replace(/^메일 제목:/, '').trim();
            if (text.length < 2) continue;
            // Only skip if parent is the sidebar folder tree (not the mail list)
            const parent = el.closest('.snb, .lnb, .lnb_mail');
            if (parent) continue;
            results.push(text.slice(0, 100));
        }}
        return results;
    }})()
    """
    return await cdp_eval(ws, subjects_js, rid=rid_base + 1) or []


async def go_to_next_page(ws, rid_base):
    """Try to go to next page. Returns True if navigation happened."""
    # Strategy: try clicking numbered page links first, then "다음" button
    next_js = """
    (() => {
        // Find current active page number
        const active = document.querySelector('[class*=paging] .on, [class*=page] .active, [class*=page] .current, [class*=paging] strong');
        let currentPage = 0;
        if (active) currentPage = parseInt(active.textContent.trim()) || 0;

        // Try clicking next numbered page
        if (currentPage > 0) {
            const nextNum = currentPage + 1;
            const pageLinks = document.querySelectorAll('[class*=paging] a, [class*=page] a');
            for (const a of pageLinks) {
                if (a.textContent.trim() === String(nextNum)) {
                    a.click();
                    return 'page_' + nextNum;
                }
            }
        }

        // Try "다음" button (for going past page 10)
        const nextBtns = document.querySelectorAll('[class*=next], [class*=paging] a');
        for (const b of nextBtns) {
            const text = b.textContent.trim();
            const title = b.getAttribute('title') || '';
            const ariaLabel = b.getAttribute('aria-label') || '';
            if (text === '다음' || title.includes('다음') || ariaLabel.includes('다음') ||
                text === '>' || text === '›' || text === '»') {
                b.click();
                return 'next_button';
            }
        }

        // Try img-based next button
        const imgs = document.querySelectorAll('[class*=paging] img, [class*=page] img');
        for (const img of imgs) {
            const alt = img.getAttribute('alt') || '';
            const src = img.getAttribute('src') || '';
            if (alt.includes('다음') || src.includes('next')) {
                const parent = img.closest('a, button') || img;
                parent.click();
                return 'next_img';
            }
        }

        return false;
    })()
    """
    result = await cdp_eval(ws, next_js, rid=rid_base)
    if result:
        await asyncio.sleep(3)
        return True
    return False


async def crawl_folder_all_pages(ws, folder_name, folder_key, base_url, rid_base=1000):
    """Crawl a mail folder across ALL pages until no more mails."""
    init_folder(folder_key)

    print(f"\n{'━'*55}")
    print(f"📂 [{folder_name}] — 전체 페이지 순회")
    print(f"{'━'*55}")

    await navigate_and_wait(ws, base_url, rid=rid_base, wait=5)

    page = 0
    consecutive_empty = 0
    max_total_pages = 50  # safety limit

    while page < max_total_pages:
        page += 1
        titles = await get_mail_subjects(ws, rid_base + page * 100, max_count=25)

        if not titles:
            consecutive_empty += 1
            if consecutive_empty >= 2 or page == 1:
                if page == 1:
                    print(f"  메일 없음")
                break
            continue
        consecutive_empty = 0

        print(f"\n  ── 페이지 {page} ({len(titles)}건) ──")

        # Get mail link hrefs for direct navigation
        links_js = """
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
                results.push({text: text.slice(0, 100), href: href});
            }
            return results;
        })()
        """
        mail_links = await cdp_eval(ws, links_js, rid=rid_base + page * 1000 + 5) or []

        for i, subj in enumerate(titles):
            RESULTS[folder_key]["tried"] += 1

            # Navigate directly to mail using href
            href = mail_links[i].get("href", "") if i < len(mail_links) else ""
            if href and href.startswith("/"):
                mail_url = f"https://mail.worksmobile.com{href}"
                await navigate_and_wait(ws, mail_url, rid=rid_base + page * 1000 + i * 10, wait=3)
            else:
                # Fallback: click
                click_js = f"""
                (() => {{
                    const subs = document.querySelectorAll('.subject a');
                    if (subs[{i}]) {{ subs[{i}].removeAttribute('data-disabled'); subs[{i}].click(); return true; }}
                    return false;
                }})()
                """
                clicked = await cdp_eval(ws, click_js, rid=rid_base + page * 1000 + i * 10)
                if not clicked:
                    print(f"    [p{page}-#{i+1}] 이동 실패: {subj[:35]}")
                    continue
                await asyncio.sleep(3)

            text = await cdp_eval(ws, "document.body.innerText.slice(0, 2000)", rid=rid_base + page * 1000 + i * 10 + 1)
            title = await cdp_eval(ws, "document.title", rid=rid_base + page * 1000 + i * 10 + 2)

            if not text or len(text) < 50:
                print(f"    [p{page}-#{i+1}] 텍스트 추출 실패 ({len(text or '')}자)")
                await navigate_and_wait(ws, base_url, rid=rid_base + page * 1000 + i * 10 + 3, wait=3)
                continue

            # Parse metadata
            sender_match = re.search(r"([\w가-힣]+)\s*<([\w.@]+)>", text)
            sender = f"{sender_match.group(1)}<{sender_match.group(2)}>" if sender_match else ""
            if not sender:
                s_match = re.search(r"(?:보낸사람|발신)[:\s]*\n?\s*([\w가-힣.@]+)", text)
                sender = s_match.group(1) if s_match else "N/A"

            r_match = re.search(r"(?:받는사람|수신)[:\s]*\n?\s*([\w가-힣.@]+)", text)
            recipient = r_match.group(1) if r_match else ""

            date_match = re.search(r"(\d{4}[./]\d{1,2}[./]\d{1,2})", text[:300])
            mail_date = date_match.group(1) if date_match else ""

            is_reply = bool(re.search(r"(?:RE:|Re:|회신|답장)", (title or subj)))

            record = {
                "app_name": "네이버 웍스",
                "window_title": f"[{folder_name}] {title or subj}",
                "extracted_text": text,
                "text_length": len(text),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            pushed = await push(record)

            RESULTS[folder_key]["success"] += 1
            RESULTS[folder_key]["chars"] += len(text)
            RESULTS[folder_key]["mails"].append({
                "title": (title or subj)[:60],
                "sender": sender[:30],
                "recipient": recipient[:30],
                "chars": len(text),
                "is_reply": is_reply,
                "date": mail_date,
            })

            reply_tag = " [RE]" if is_reply else ""
            ts = datetime.now().strftime("%H:%M:%S")
            display_title = (title or subj)[:40]
            print(f"    [p{page}-#{i+1}] {ts} | {display_title} | {sender[:12]} | {len(text):,}자{reply_tag}")

            await navigate_and_wait(ws, base_url, rid=rid_base + page * 1000 + i * 10 + 3, wait=3)

        # Try to go to next page
        has_next = await go_to_next_page(ws, rid_base=rid_base + page * 1000 + 900)
        if not has_next:
            print(f"  ── 마지막 페이지: {page} ──")
            break

    data = RESULTS[folder_key]
    if data["tried"] > 0:
        pct = data["success"] / data["tried"] * 100
        avg = data["chars"] // data["success"] if data["success"] else 0
        print(f"\n  ✓ {folder_name} 완료: {data['success']}/{data['tried']} ({pct:.0f}%) 평균 {avg:,}자 ({page}페이지)")


async def main():
    start_time = datetime.now()
    print("=" * 60)
    print("J.A.R.V.I.S 메일함 전체 순회 크롤링")
    print(f"시작: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    r = httpx.get(f"{CDP}/json", timeout=5)
    tabs = [t for t in r.json()
            if t.get("type") == "page" and
            ("worksmobile" in t.get("url", "") or "메일" in t.get("title", ""))]
    if not tabs:
        print("No mail tab found")
        return

    ws_url = tabs[0]["webSocketDebuggerUrl"]

    async with websockets.connect(ws_url, close_timeout=15) as ws:
        # ── 1. 받은메일함 (모든 페이지) ──
        await crawl_folder_all_pages(ws, "받은메일함", "inbox",
            "https://mail.worksmobile.com/w/inbox", rid_base=10000)

        # ── 2. 보낸메일함 (모든 페이지) ──
        await crawl_folder_all_pages(ws, "보낸메일함", "sent",
            "https://mail.worksmobile.com/w/sent", rid_base=20000)

        # ── 답장 매칭 분석 ──
        print(f"\n{'━'*55}")
        print("🔗 [답장/스레드 매칭 분석]")
        print(f"{'━'*55}")
        sent_mails = RESULTS.get("sent", {}).get("mails", [])
        inbox_mails = RESULTS.get("inbox", {}).get("mails", [])

        reply_count = sum(1 for m in sent_mails if m.get("is_reply"))
        print(f"  보낸메일 중 답장(RE:): {reply_count}/{len(sent_mails)}")

        matches = 0
        matched_pairs = []
        for sm in sent_mails:
            st = re.sub(r"^(RE:\s*|Re:\s*|\[회신\]\s*)", "", sm["title"]).strip()[:25]
            for im in inbox_mails:
                it = re.sub(r"^(RE:\s*|Re:\s*|\[회신\]\s*)", "", im["title"]).strip()[:25]
                if st and it and (st in it or it in st):
                    matches += 1
                    matched_pairs.append(f"    '{sm['title'][:30]}' ↔ '{im['title'][:30]}'")
                    break
        print(f"  보낸↔받은 스레드 매칭: {matches}건")
        for pair in matched_pairs[:5]:
            print(pair)

        can_detect = reply_count > 0 or matches > 0
        method = "RE: 접두사 + 제목 매칭" if can_detect else "불가"
        print(f"  답장 여부 추론: {'가능' if can_detect else '제한적'} ({method})")

    # ══════════ 최종 결과 ══════════
    end_time = datetime.now()
    print(f"\n{'═'*60}")
    print("📊 크롤링 최종 결과")
    print(f"{'═'*60}")
    total_tried = 0
    total_success = 0
    total_chars = 0

    for key in ["inbox", "sent"]:
        data = RESULTS.get(key, {"tried": 0, "success": 0, "chars": 0})
        if data["tried"] > 0:
            pct = data["success"] / data["tried"] * 100
            avg = data["chars"] // data["success"] if data["success"] else 0
            print(f"  {key:10s}: {data['success']:3d}/{data['tried']:3d} ({pct:5.1f}%)  평균 {avg:,}자")
            total_tried += data["tried"]
            total_success += data["success"]
            total_chars += data["chars"]
        else:
            print(f"  {key:10s}: 메일 없음")

    if total_tried:
        print(f"\n  합계: {total_success}/{total_tried} ({total_success/total_tried*100:.1f}%)")
        print(f"  전체 평균: {total_chars // total_success if total_success else 0:,}자")

    elapsed = (end_time - start_time).total_seconds()
    print(f"\n  소요시간: {elapsed:.0f}초 ({elapsed/60:.1f}분)")

    # Save results
    import os
    results_path = os.path.join(os.path.dirname(__file__), "crawl_results.json")
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "results": {k: {**v} for k, v in RESULTS.items()},
            "total_tried": total_tried,
            "total_success": total_success,
            "total_chars": total_chars,
            "elapsed_s": elapsed,
        }, f, ensure_ascii=False, indent=2)
    print(f"  결과 저장: {results_path}")


if __name__ == "__main__":
    asyncio.run(main())
