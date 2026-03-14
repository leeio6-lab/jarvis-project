"""Crawl ALL mail folders: sent, all-mail, drafts, spam, custom folders."""

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

RESULTS = {
    "sent": {"tried": 0, "success": 0, "chars": 0, "mails": []},
    "all": {"tried": 0, "success": 0, "chars": 0, "mails": []},
    "drafts": {"tried": 0, "success": 0, "chars": 0, "mails": []},
    "spam": {"tried": 0, "success": 0, "chars": 0, "mails": []},
    "custom": {"tried": 0, "success": 0, "chars": 0, "mails": []},
}


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
    resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
    return resp.get("result", {}).get("result", {}).get("value")


async def navigate_and_wait(ws, url, rid=100):
    await ws.send(json.dumps({"id": rid, "method": "Page.navigate",
                               "params": {"url": url}}))
    await asyncio.wait_for(ws.recv(), timeout=10)
    await asyncio.sleep(5)


async def crawl_folder(ws, folder_name, folder_key, url, max_mails=10, rid_base=200):
    """Crawl a specific mail folder."""
    print(f"\n{'='*50}")
    print(f"[{folder_name}] 크롤링 시작")
    print(f"{'='*50}")

    await navigate_and_wait(ws, url, rid=rid_base)

    # Wait for subject elements
    for attempt in range(5):
        count = await cdp_eval(ws, "document.querySelectorAll('.subject').length", rid=rid_base+1)
        if count and count > 0:
            break
        await asyncio.sleep(2)

    # Get mail subjects
    mail_titles = await cdp_eval(ws,
        f"Array.from(document.querySelectorAll('.subject')).slice(0,{max_mails})"
        ".map(el => el.textContent.trim().slice(0,80))", rid=rid_base+2)

    if not mail_titles:
        print(f"  메일 없음 또는 subject 요소 없음")
        return

    mail_titles = [t for t in mail_titles if len(t) > 3 and "메일" not in t[:5]]
    print(f"  발견: {len(mail_titles)}건\n")

    for i, subj in enumerate(mail_titles[:max_mails]):
        click_js = (
            f"(() => {{"
            f"  const subs = Array.from(document.querySelectorAll('.subject'))"
            f"    .filter(el => el.textContent.trim().length > 3);"
            f"  if (subs[{i}]) {{ subs[{i}].click(); return true; }}"
            f"  return false;"
            f"}})()"
        )
        clicked = await cdp_eval(ws, click_js, rid=rid_base+10+i)
        RESULTS[folder_key]["tried"] += 1

        if not clicked:
            print(f"  [#{i+1}] 클릭 실패: {subj[:40]}")
            continue

        await asyncio.sleep(3)

        text = await cdp_eval(ws, "document.body.innerText.slice(0, 2000)", rid=rid_base+30+i)
        title = await cdp_eval(ws, "document.title", rid=rid_base+50+i)

        if not text or len(text) < 50:
            print(f"  [#{i+1}] 텍스트 추출 실패 ({len(text or '')}자)")
            await cdp_eval(ws, "window.history.back()", rid=rid_base+70+i)
            await asyncio.sleep(2)
            continue

        # Detect if this is a sent mail
        is_sent = folder_key == "sent"
        sent_indicator = ""
        if is_sent:
            # Check for sent-mail indicators
            if "받는사람" in text[:300] or "수신" in text[:300]:
                sent_indicator = " [보낸메일 감지됨]"

        # Parse sender
        sender_match = re.search(r"([\w가-힣]+)<([\w.@]+)>", text)
        sender = f"{sender_match.group(1)}<{sender_match.group(2)}>" if sender_match else "N/A"

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
            "sender": sender,
            "chars": len(text),
            "pushed": pushed,
        })

        ts = datetime.now().strftime("%H:%M:%S")
        print(f"  [#{i+1}] {ts} | {(title or subj)[:50]} | {len(text):,}자 | {'OK' if pushed else 'FAIL'}{sent_indicator}")

        await cdp_eval(ws, "window.history.back()", rid=rid_base+70+i)
        await asyncio.sleep(2)


async def find_custom_folders(ws, rid_base=900):
    """Find custom folders from the sidebar navigation."""
    # Try to find folder links in the sidebar
    folders_js = """
    (() => {
        const folderElements = document.querySelectorAll('[class*=folder], [class*=tree] a, .lnb a, nav a, .sidebar a');
        const folders = [];
        folderElements.forEach(el => {
            const text = el.textContent.trim();
            const href = el.getAttribute('href') || '';
            if (text.length > 1 && text.length < 30 && href) {
                folders.push({name: text, href: href});
            }
        });
        return folders;
    })()
    """
    folders = await cdp_eval(ws, folders_js, rid=rid_base)
    return folders or []


async def main():
    print("=" * 60)
    print("J.A.R.V.I.S 전체 메일폴더 크롤링 테스트")
    print(f"시작 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
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
        # 1. 보낸메일함
        await crawl_folder(ws, "보낸메일함", "sent",
                          "https://mail.worksmobile.com/w/sent", max_mails=10, rid_base=200)

        # 2. 전체메일함
        await crawl_folder(ws, "전체메일함", "all",
                          "https://mail.worksmobile.com/w/all", max_mails=10, rid_base=400)

        # 3. 임시보관함
        await crawl_folder(ws, "임시보관함", "drafts",
                          "https://mail.worksmobile.com/w/draft", max_mails=5, rid_base=600)

        # 4. 스팸함
        await crawl_folder(ws, "스팸함", "spam",
                          "https://mail.worksmobile.com/w/spam", max_mails=5, rid_base=700)

        # 5. 커스텀 폴더들 — 네이버 웍스 URL 패턴: /w/folder/{id}
        # Try known folder names from task description
        custom_folder_names = [
            "고정자산", "IO코드", "생성완료", "매각 폐기",
            "장기미대체자산", "기타무형자산", "건증증보",
        ]

        # First, try to detect custom folders from the page
        await navigate_and_wait(ws, "https://mail.worksmobile.com/w/inbox", rid=800)
        await asyncio.sleep(2)

        # Look for folder links in sidebar
        folder_links_js = """
        (() => {
            const links = [];
            document.querySelectorAll('a[href*="/w/folder/"]').forEach(a => {
                links.push({name: a.textContent.trim(), href: a.getAttribute('href')});
            });
            // Also check tree items
            document.querySelectorAll('[class*=tree] [class*=item], [class*=folder] [class*=item]').forEach(el => {
                const a = el.querySelector('a') || el;
                const name = a.textContent.trim();
                const href = a.getAttribute && a.getAttribute('href');
                if (name && name.length > 1 && name.length < 20) {
                    links.push({name: name, href: href || ''});
                }
            });
            return links;
        })()
        """
        custom_folders = await cdp_eval(ws, folder_links_js, rid=801)

        if custom_folders and len(custom_folders) > 0:
            print(f"\n커스텀 폴더 발견: {len(custom_folders)}개")
            for cf in custom_folders[:10]:
                name = cf.get("name", "?")
                href = cf.get("href", "")
                if href and "/w/folder/" in href:
                    full_url = f"https://mail.worksmobile.com{href}" if href.startswith("/") else href
                    await crawl_folder(ws, name, "custom",
                                      full_url, max_mails=3, rid_base=850)
        else:
            print("\n커스텀 폴더 자동 감지 안 됨 — sidebar 구조 분석 시도")
            # Try getting all sidebar text
            sidebar_text = await cdp_eval(ws,
                "document.querySelector('.lnb, [class*=sidebar], nav')?.innerText || 'NO SIDEBAR'",
                rid=802)
            print(f"  사이드바 텍스트: {(sidebar_text or '')[:200]}")

    # === 최종 집계 ===
    print(f"\n{'='*60}")
    print("전체 메일폴더 크롤링 결과")
    print(f"{'='*60}")
    total_tried = 0
    total_success = 0
    for key, data in RESULTS.items():
        if data["tried"] > 0:
            pct = data["success"] / data["tried"] * 100
            avg = data["chars"] // data["success"] if data["success"] else 0
            print(f"  {key:10s}: {data['success']}/{data['tried']} ({pct:.0f}%), 평균 {avg:,}자")
            total_tried += data["tried"]
            total_success += data["success"]
        else:
            print(f"  {key:10s}: 메일 없음")

    if total_tried:
        print(f"\n  전체: {total_success}/{total_tried} ({total_success/total_tried*100:.0f}%)")
    print(f"종료 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    asyncio.run(main())
