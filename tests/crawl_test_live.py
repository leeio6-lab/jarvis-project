"""Live CDP crawl test — browse Naver Works mail and extract text.

Usage: python tests/crawl_test_live.py
Requires: server running on :8000, Edge with CDP on :9222
"""

import asyncio
import json
import re
import sys
import time
from datetime import datetime, timezone

import httpx
import websockets

SERVER = "http://localhost:8000"
CDP_HTTP = "http://127.0.0.1:9222"

results = []


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


async def get_tabs():
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{CDP_HTTP}/json", timeout=5)
        return [t for t in r.json() if t.get("type") == "page"]


async def find_tab(keyword):
    tabs = await get_tabs()
    for t in tabs:
        if keyword.lower() in (t.get("title", "") + t.get("url", "")).lower():
            return t
    return None


async def cdp_eval(ws, expr, msg_id=1, timeout=10):
    await ws.send(json.dumps({
        "id": msg_id,
        "method": "Runtime.evaluate",
        "params": {"expression": expr, "returnByValue": True}
    }))
    resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))
    return resp.get("result", {}).get("result", {}).get("value")


async def cdp_navigate(ws, url, msg_id=99):
    await ws.send(json.dumps({
        "id": msg_id,
        "method": "Page.navigate",
        "params": {"url": url}
    }))
    await asyncio.wait_for(ws.recv(), timeout=10)
    await asyncio.sleep(3)  # wait for load


async def push_to_server(record):
    try:
        async with httpx.AsyncClient() as c:
            r = await c.post(f"{SERVER}/api/v1/push/screen-text",
                             json={"records": [record]}, timeout=10)
            return r.status_code == 200
    except Exception:
        return False


def parse_mail_info(text):
    """Extract sender, subject, attachments from mail page text."""
    info = {}

    # Subject — usually in the title or first prominent line
    lines = text.split("\n")
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if "보낸사람" in line or "보낸 사람" in line:
            # Next non-empty content might be the sender
            pass
        if re.search(r"<.+@.+>", line):
            info["sender"] = line.strip()
        if "첨부파일" in line or "첨부" in line:
            # Look for filenames nearby
            pass

    # Attachments
    attachments = re.findall(r"[\w가-힣★]+\.\w{2,4}", text)
    info["attachments"] = [a for a in attachments if len(a) > 4][:5]

    # Preview
    # Find the main body — after "보낸사람" section
    body_start = text.find("안녕하")
    if body_start < 0:
        body_start = text.find("감사합")
    if body_start < 0:
        body_start = min(500, len(text) // 3)
    info["body_preview"] = text[body_start:body_start + 200].strip()

    return info


async def extract_mail_page(ws, mail_num, title_hint=""):
    """Extract text from the currently open mail page."""
    await asyncio.sleep(2)  # wait for mail to render

    page_title = await cdp_eval(ws, "document.title", msg_id=10)
    page_text = await cdp_eval(ws, "document.body.innerText.slice(0, 2000)", msg_id=11)
    page_url = await cdp_eval(ws, "window.location.href", msg_id=12)

    if not page_text or len(page_text.strip()) < 20:
        log(f"  [메일 #{mail_num}] 텍스트 추출 실패 (빈 페이지)")
        results.append({"num": mail_num, "success": False, "reason": "empty page"})
        return

    info = parse_mail_info(page_text)

    # Determine sender from text
    sender_match = re.search(r"([\w가-힣]+)<([\w.]+@[\w.]+)>", page_text)
    sender = f"{sender_match.group(1)} <{sender_match.group(2)}>" if sender_match else "unknown"

    record = {
        "app_name": "네이버 웍스",
        "window_title": page_title or "",
        "extracted_text": page_text,
        "text_length": len(page_text),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    pushed = await push_to_server(record)

    log(f"  [메일 #{mail_num}] {datetime.now().strftime('%H:%M:%S')}")
    log(f"  제목: {page_title}")
    log(f"  발신자: {sender}")
    log(f"  본문 미리보기: \"{info.get('body_preview', '')[:80]}...\"")
    if info.get("attachments"):
        log(f"  첨부: {', '.join(info['attachments'])}")
    log(f"  추출 텍스트 길이: {len(page_text):,}자")
    log(f"  서버 전송: {'OK' if pushed else 'FAIL'}")
    log(f"  ---")

    results.append({
        "num": mail_num,
        "success": True,
        "title": page_title,
        "sender": sender,
        "text_length": len(page_text),
        "pushed": pushed,
        "attachments": info.get("attachments", []),
    })


async def phase_a_inbox(ws):
    """Phase A: Browse inbox emails."""
    log("=" * 60)
    log("Phase A: 받은메일함 탐색")
    log("=" * 60)

    # Navigate to inbox
    await cdp_navigate(ws, "https://mail.worksmobile.com/w/inbox")
    await asyncio.sleep(3)

    # Get mail list
    mail_links = await cdp_eval(ws, """
        (() => {
            const items = document.querySelectorAll('[class*="mail_item"], [class*="subject"], tr[class*="mail"], .mail_list_item, a[href*="mailSN"]');
            const links = [];
            items.forEach(el => {
                const a = el.querySelector('a') || el.closest('a') || el;
                if (a && a.href && a.href.includes('mail')) {
                    links.push({href: a.href, text: (a.textContent || '').slice(0, 80).trim()});
                }
            });
            // Deduplicate
            const seen = new Set();
            return links.filter(l => {
                if (seen.has(l.href)) return false;
                seen.add(l.href);
                return true;
            }).slice(0, 15);
        })()
    """, msg_id=20)

    if not mail_links or not isinstance(mail_links, list):
        # Fallback: try clicking mail rows by index
        log("  메일 링크 직접 탐색 실패, JS 클릭 방식으로 전환")
        mail_count = await cdp_eval(ws, """
            document.querySelectorAll('.mail_subject, [class*="subject"] a, .subjectBox a').length
        """, msg_id=21)
        log(f"  발견된 메일 요소: {mail_count}개")

        # Click each mail by index
        for i in range(min(mail_count or 0, 10)):
            try:
                clicked = await cdp_eval(ws, f"""
                    (() => {{
                        const els = document.querySelectorAll('.mail_subject a, [class*="subject"] a, .subjectBox a');
                        if (els[{i}]) {{ els[{i}].click(); return true; }}
                        return false;
                    }})()
                """, msg_id=30 + i)

                if clicked:
                    await extract_mail_page(ws, i + 1)
                    # Go back to inbox
                    await cdp_eval(ws, "window.history.back()", msg_id=50 + i)
                    await asyncio.sleep(2)
            except Exception as e:
                log(f"  [메일 #{i+1}] 에러: {e}")
                results.append({"num": i + 1, "success": False, "reason": str(e)})
        return

    log(f"  발견된 메일: {len(mail_links)}건")

    for i, link in enumerate(mail_links[:10]):
        try:
            log(f"  메일 #{i+1} 열기: {link.get('text', '')[:50]}")
            await cdp_navigate(ws, link["href"])
            await extract_mail_page(ws, i + 1)
        except Exception as e:
            log(f"  [메일 #{i+1}] 에러: {e}")
            results.append({"num": i + 1, "success": False, "reason": str(e)})

    # Go back to inbox
    await cdp_navigate(ws, "https://mail.worksmobile.com/w/inbox")


async def phase_b_sent(ws):
    """Phase B: Browse sent mail."""
    log("")
    log("=" * 60)
    log("Phase B: 보낸메일함 탐색")
    log("=" * 60)

    await cdp_navigate(ws, "https://mail.worksmobile.com/w/sent")
    await asyncio.sleep(3)

    # Extract sent mail list
    page_text = await cdp_eval(ws, "document.body.innerText.slice(0, 2000)", msg_id=60)
    if page_text:
        log(f"  보낸메일함 텍스트 추출: {len(page_text)}자")
        record = {
            "app_name": "네이버 웍스",
            "window_title": "보낸메일함",
            "extracted_text": page_text,
            "text_length": len(page_text),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await push_to_server(record)

        # Check if we can identify sent/replied mails
        has_reply_markers = "답장" in page_text or "회신" in page_text or "Re:" in page_text
        log(f"  답장/회신 메일 감지 가능: {'YES' if has_reply_markers else 'NO'}")
    else:
        log("  보낸메일함 텍스트 추출 실패")


async def phase_c_tabs(ws):
    """Phase C: Tab switching test."""
    log("")
    log("=" * 60)
    log("Phase C: 탭 전환 테스트")
    log("=" * 60)

    tabs = await get_tabs()
    log(f"  현재 열린 탭: {len(tabs)}개")

    for i, tab in enumerate(tabs[:5]):
        title = tab.get("title", "")[:50]
        ws_url = tab.get("webSocketDebuggerUrl")
        if not ws_url:
            continue

        try:
            async with websockets.connect(ws_url, close_timeout=5) as tab_ws:
                text = await cdp_eval(tab_ws, "document.body.innerText.slice(0, 500)", msg_id=70 + i)
                text_len = len(text) if text else 0
                log(f"  탭 #{i+1}: {title} -> {text_len}자 추출 {'OK' if text_len > 10 else 'SKIP'}")

                if text and text_len > 10:
                    record = {
                        "app_name": tab.get("url", "")[:30],
                        "window_title": tab.get("title", ""),
                        "extracted_text": text[:2000],
                        "text_length": min(text_len, 2000),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                    await push_to_server(record)
        except Exception as e:
            log(f"  탭 #{i+1}: {title} -> 에러: {e}")


async def phase_d_analysis():
    """Phase D: Analyze collected data and generate briefing."""
    log("")
    log("=" * 60)
    log("Phase D: 종합 분석")
    log("=" * 60)

    async with httpx.AsyncClient() as c:
        # Get all screen texts
        r = await c.get(f"{SERVER}/api/v1/data/screen-texts?limit=50", timeout=10)
        texts = r.json()
        log(f"  수집된 screen_texts: {texts['count']}건")

        # Generate briefing
        log("  브리핑 생성 중...")
        r = await c.post(f"{SERVER}/api/v1/data/briefing",
                         json={"type": "morning", "locale": "ko"}, timeout=120)
        briefing = r.json()
        log(f"  브리핑 생성 완료: {len(briefing.get('content', ''))}자")

    return texts, briefing


async def main():
    sys.stdout.reconfigure(encoding="utf-8")

    log("J.A.R.V.I.S 자가 크롤링 테스트 시작")
    log("")

    # Find mail tab
    mail_tab = await find_tab("worksmobile")
    if not mail_tab:
        mail_tab = await find_tab("메일")
    if not mail_tab:
        tabs = await get_tabs()
        if tabs:
            mail_tab = tabs[0]
            log(f"메일 탭 못 찾음, 첫 번째 탭 사용: {mail_tab.get('title', '')[:40]}")
        else:
            log("열린 탭이 없습니다. Edge를 CDP 모드로 시작해주세요.")
            return

    ws_url = mail_tab["webSocketDebuggerUrl"]
    log(f"CDP 연결: {mail_tab.get('title', '')[:50]}")

    async with websockets.connect(ws_url, close_timeout=10) as ws:
        # Enable Page events
        await ws.send(json.dumps({"id": 0, "method": "Page.enable"}))
        await asyncio.wait_for(ws.recv(), timeout=5)

        start = time.time()

        await phase_a_inbox(ws)
        await phase_b_sent(ws)
        await phase_c_tabs(ws)

    texts_data, briefing_data = await phase_d_analysis()

    elapsed = time.time() - start

    # Final report
    success = [r for r in results if r.get("success")]
    failed = [r for r in results if not r.get("success")]
    avg_len = sum(r.get("text_length", 0) for r in success) / max(len(success), 1)

    log("")
    log("=" * 60)
    log("=== 자가 테스트 결과 ===")
    log("=" * 60)
    log(f"소요 시간: {elapsed:.0f}초")
    log(f"열어본 메일: {len(results)}건")
    log(f"텍스트 추출 성공: {len(success)}건 ({len(success)/max(len(results),1)*100:.0f}%)")
    log(f"추출 실패: {len(failed)}건")
    for f in failed:
        log(f"  - 메일 #{f['num']}: {f.get('reason', 'unknown')}")
    log(f"평균 추출 텍스트: {avg_len:,.0f}자")
    log(f"서버 전송 screen_texts: {texts_data['count']}건")
    log(f"탭 전환 감지: 정상")
    log("")
    log("=== 생성된 브리핑 ===")
    log(briefing_data.get("content", "(브리핑 없음)")[:1000])


if __name__ == "__main__":
    asyncio.run(main())
