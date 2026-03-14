"""Browse Naver Works inbox — click each mail, extract text, push to server."""

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


async def main():
    # Find mail tab
    r = httpx.get(f"{CDP}/json", timeout=5)
    tabs = [t for t in r.json()
            if t.get("type") == "page" and
            ("worksmobile" in t.get("url", "") or "메일" in t.get("title", ""))]
    if not tabs:
        print("No mail tab found in CDP")
        return

    ws_url = tabs[0]["webSocketDebuggerUrl"]
    print(f"Tab: {tabs[0]['title']}")
    print(f"URL: {tabs[0]['url'][:80]}")
    print()

    async with websockets.connect(ws_url, close_timeout=15) as ws:
        # Check current page
        current_url = await cdp_eval(ws, "window.location.href", rid=1)
        if "inbox" not in (current_url or ""):
            # Navigate to inbox
            print("Navigating to inbox...")
            await ws.send(json.dumps({"id": 2, "method": "Page.navigate",
                                       "params": {"url": "https://mail.worksmobile.com/w/inbox"}}))
            await asyncio.wait_for(ws.recv(), timeout=10)
            await asyncio.sleep(6)

        # Wait for subject elements
        for attempt in range(5):
            count = await cdp_eval(ws, "document.querySelectorAll('.subject').length", rid=3)
            if count and count > 0:
                break
            await asyncio.sleep(2)

        # Get mail subject titles for reference
        mail_titles_js = (
            "Array.from(document.querySelectorAll('.subject'))"
            ".filter(el => el.closest('[class*=mail_item], tr, [class*=item]'))"
            ".slice(0, 15)"
            ".map((el, i) => el.textContent.trim().slice(0, 80))"
        )
        mail_titles = await cdp_eval(ws, mail_titles_js, rid=4)

        if not mail_titles:
            # Fallback: just get all .subject text
            mail_titles = await cdp_eval(ws,
                "Array.from(document.querySelectorAll('.subject')).slice(0,15)"
                ".map(el => el.textContent.trim().slice(0,80))", rid=5)

        if not mail_titles:
            print("메일 subject 요소 없음")
            return

        # Filter out empty/navigation subjects + strip accessibility prefixes
        cleaned = []
        for t in mail_titles:
            t = t.replace("내가 수신인에 포함된 메일", "").replace("메일 제목:", "").strip()
            if len(t) > 3:
                cleaned.append(t)
        mail_titles = cleaned
        print(f"받은메일함: {len(mail_titles)}건 발견\n")

        success_count = 0
        total_chars = 0

        for i, subj in enumerate(mail_titles[:10]):
            # Click the i-th subject
            click_js = (
                f"(() => {{"
                f"  const subs = Array.from(document.querySelectorAll('.subject'))"
                f"    .filter(el => el.textContent.trim().length > 3);"
                f"  if (subs[{i}]) {{ subs[{i}].click(); return true; }}"
                f"  return false;"
                f"}})()"
            )
            clicked = await cdp_eval(ws, click_js, rid=10 + i)
            if not clicked:
                print(f"[메일 #{i+1}] 클릭 실패: {subj[:40]}")
                continue

            await asyncio.sleep(3)  # wait for mail to render

            # Extract full page text
            text = await cdp_eval(ws, "document.body.innerText.slice(0, 2000)", rid=30 + i)
            title = await cdp_eval(ws, "document.title", rid=50 + i)

            if not text or len(text) < 50:
                print(f"[메일 #{i+1}] 텍스트 추출 실패 ({len(text or '')}자)")
                await cdp_eval(ws, "window.history.back()", rid=70 + i)
                await asyncio.sleep(2)
                continue

            # Parse sender
            sender_match = re.search(r"([\w가-힣]+)<([\w.@]+)>", text)
            sender = f"{sender_match.group(1)}<{sender_match.group(2)}>" if sender_match else ""
            if not sender:
                # Try "보낸사람\n이름" pattern
                s_match = re.search(r"보낸사람\n[^\n]*\n?([\w가-힣]+)", text)
                sender = s_match.group(1) if s_match else "N/A"

            # Attachments
            atts = re.findall(r"[\w가-힣★]+\.\w{2,5}", text)
            atts = [a for a in atts if len(a) > 5][:5]

            # Body preview
            body = ""
            for kw in ["안녕하세요", "안녕하", "확인 부탁", "공유드", "보고드", "회신드",
                        "감사합니다", "요청드", "알려드", "송부드"]:
                pos = text.find(kw)
                if pos > 0:
                    body = text[pos:pos + 120].replace("\n", " ").strip()
                    break

            # Push to server
            record = {
                "app_name": "네이버 웍스",
                "window_title": title or subj,
                "extracted_text": text,
                "text_length": len(text),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            pushed = await push(record)

            ts = datetime.now().strftime("%H:%M:%S")
            print(f"[메일 #{i+1}] {ts}")
            print(f"  제목: {title or subj}")
            print(f"  발신자: {sender}")
            if body:
                print(f"  본문: \"{body[:80]}...\"")
            if atts:
                print(f"  첨부: {', '.join(atts)}")
            print(f"  추출: {len(text):,}자 | 서버: {'OK' if pushed else 'FAIL'}")
            print(f"  ---")

            success_count += 1
            total_chars += len(text)

            # Go back to inbox
            await cdp_eval(ws, "window.history.back()", rid=70 + i)
            await asyncio.sleep(2)

        # === Summary ===
        print(f"\n{'='*50}")
        print(f"받은메일함 크롤링 완료")
        print(f"{'='*50}")
        print(f"시도: {min(len(mail_titles), 10)}건")
        print(f"성공: {success_count}건 ({success_count/max(min(len(mail_titles),10),1)*100:.0f}%)")
        if success_count:
            print(f"평균 텍스트: {total_chars // success_count:,}자")

        # Server total
        async with httpx.AsyncClient() as c:
            r = await c.get(f"{SERVER}/api/v1/data/screen-texts?limit=100", timeout=10)
            print(f"서버 총 screen_texts: {r.json()['count']}건")


if __name__ == "__main__":
    asyncio.run(main())
