"""Phase 1: Full workday simulation — CDP crawling + API calls.

09:00 출근 루틴   — briefing, command
09:15 메일 확인   — CDP inbox/sent crawl
09:30 업무 사이트 — Calendar, Google, law.go.kr, dart.fss.or.kr
09:40 중간 확인   — command: 미답장, TODO 추가/조회
09:45 잡무        — 뉴스, 날씨, 유튜브 (비업무)
09:55 퇴근        — "오늘 뭐했어?", 저녁 briefing, productivity score
"""

import asyncio
import json
import sys
import time
from datetime import datetime, timezone

import httpx
import websockets

sys.stdout.reconfigure(encoding="utf-8")

SERVER = "http://localhost:8000"
CDP = "http://127.0.0.1:9222"

# ─── results tracking ───
ALL_RESULTS = {
    "api_calls": [],
    "cdp_crawls": [],
    "commands": [],
    "briefings": [],
    "errors": [],
}


# ─── helpers ───

async def api_call(method, path, json_body=None, label=""):
    """Call server API and record result."""
    start = time.time()
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            if method == "GET":
                r = await c.get(f"{SERVER}{path}")
            else:
                r = await c.post(f"{SERVER}{path}", json=json_body or {})
            elapsed = round(time.time() - start, 2)
            try:
                body_json = r.json()
            except Exception:
                body_json = None
            result = {
                "label": label,
                "method": method,
                "path": path,
                "status": r.status_code,
                "elapsed_s": elapsed,
                "body_len": len(r.text),
                "body_preview": r.text[:500],
                "body_json": body_json,
            }
            ALL_RESULTS["api_calls"].append(result)
            status_mark = "OK" if r.status_code == 200 else "FAIL"
            print(f"  [{status_mark}] {label}: {r.status_code} ({elapsed}s) {r.text[:200]}")
            return body_json or r.text
    except Exception as e:
        elapsed = round(time.time() - start, 2)
        ALL_RESULTS["errors"].append({"label": label, "error": str(e), "elapsed_s": elapsed})
        print(f"  [ERR] {label}: {e}")
        return None


async def get_tab_ws(url_filter=None):
    """Get CDP websocket for a tab matching url_filter, or first page tab."""
    r = httpx.get(f"{CDP}/json", timeout=5)
    tabs = [t for t in r.json() if t.get("type") == "page"]
    if url_filter:
        matched = [t for t in tabs if url_filter in t.get("url", "")]
        if matched:
            tabs = matched
    if not tabs:
        return None, None
    ws_url = tabs[0]["webSocketDebuggerUrl"]
    ws = await websockets.connect(ws_url, close_timeout=15)
    return ws, tabs[0]


async def cdp_eval(ws, expr, rid=1):
    """Evaluate JS in CDP page."""
    await ws.send(json.dumps({
        "id": rid, "method": "Runtime.evaluate",
        "params": {"expression": expr, "returnByValue": True}
    }))
    deadline = asyncio.get_event_loop().time() + 15
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            return None
        try:
            resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=remaining))
        except asyncio.TimeoutError:
            return None
        if resp.get("id") == rid:
            return resp.get("result", {}).get("result", {}).get("value")


async def open_tab_and_crawl(url, name, dwell_seconds=5):
    """Open new tab via CDP browser target, crawl, close tab. Returns (success, text)."""
    start = time.time()

    # Create new tab via HTTP endpoint (Edge requires PUT)
    try:
        r = httpx.put(f"{CDP}/json/new?{url}", timeout=10)
        tab_info = r.json()
    except Exception as e:
        ALL_RESULTS["errors"].append({"label": name, "error": f"new tab: {e}"})
        print(f"  [ERR] {name}: new tab failed: {e}")
        return False, ""

    tab_id = tab_info.get("id")
    ws_url = tab_info.get("webSocketDebuggerUrl")
    if not ws_url:
        print(f"  [ERR] {name}: no ws url for new tab")
        return False, ""

    try:
        async with websockets.connect(ws_url, close_timeout=15) as ws:
            # Wait for page to load
            await asyncio.sleep(dwell_seconds)

            title = await cdp_eval(ws, "document.title", rid=1)
            text = await cdp_eval(ws, "document.body.innerText.slice(0, 2000)", rid=2)
            current_url = await cdp_eval(ws, "window.location.href", rid=3)
    except Exception as e:
        ALL_RESULTS["errors"].append({"label": name, "error": str(e)})
        print(f"  [ERR] {name}: ws error: {e}")
        title, text, current_url = None, None, url

    elapsed = round(time.time() - start, 1)
    text_len = len(text) if text else 0

    # Push to server
    record = {
        "app_name": name,
        "window_title": title or name,
        "extracted_text": text or "",
        "text_length": text_len,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    pushed = False
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(f"{SERVER}/api/v1/push/screen-text",
                             json={"records": [record]})
            pushed = r.status_code == 200
    except Exception:
        pass

    # Close tab
    try:
        httpx.put(f"{CDP}/json/close/{tab_id}", timeout=5)
    except Exception:
        pass

    success = text_len > 50
    result = {
        "site": name,
        "url": (current_url or url)[:80],
        "title": (title or "")[:60],
        "text_len": text_len,
        "pushed": pushed,
        "success": success,
        "elapsed_s": elapsed,
    }
    ALL_RESULTS["cdp_crawls"].append(result)

    status = "OK" if success else "FAIL"
    print(f"  [{status}] {name}: {text_len:,}자, pushed={pushed}, {elapsed}s")
    if text and text_len > 50:
        print(f"       preview: \"{text[:100]}...\"")
    return success, text or ""


# ─── Phase 1 sections ───

async def section_0900_morning():
    """09:00 출근 루틴 — briefing + commands."""
    print("\n" + "=" * 60)
    print("09:00 출근 루틴")
    print("=" * 60)

    # Morning briefing
    print("\n[아침 브리핑 생성]")
    briefing = await api_call("POST", "/api/v1/data/briefing",
                              {"type": "morning"}, "아침 브리핑")
    if briefing:
        ALL_RESULTS["briefings"].append({"type": "morning", "content": briefing})

    # "자비스, 오늘 일정 알려줘"
    print("\n[오늘 일정 알려줘]")
    resp = await api_call("POST", "/api/v1/command",
                          {"text": "오늘 일정 알려줘"}, "오늘 일정")
    ALL_RESULTS["commands"].append({"cmd": "오늘 일정 알려줘", "resp": resp})

    # "미답장 메일 있어?"
    print("\n[미답장 메일 있어?]")
    resp = await api_call("POST", "/api/v1/command",
                          {"text": "미답장 메일 있어?"}, "미답장 메일")
    ALL_RESULTS["commands"].append({"cmd": "미답장 메일 있어?", "resp": resp})


async def section_0915_mail():
    """09:15 메일 확인 — CDP로 네이버 웍스 메일 열기."""
    print("\n" + "=" * 60)
    print("09:15 메일 확인 (CDP)")
    print("=" * 60)

    mail_results = []

    # Open inbox in new tab
    print("\n[받은메일함]")
    r = httpx.put(f"{CDP}/json/new?https://mail.worksmobile.com/w/inbox", timeout=10)
    tab_info = r.json()
    ws_url = tab_info.get("webSocketDebuggerUrl")
    tab_id = tab_info.get("id")

    if not ws_url:
        print("  [ERR] 메일 탭 생성 실패")
        return False

    await asyncio.sleep(8)

    try:
        async with websockets.connect(ws_url, close_timeout=15) as ws:
            # Check if logged in
            current_url = await cdp_eval(ws, "window.location.href", rid=1)
            if current_url and "auth" in current_url.lower():
                print("  WARNING: 로그인 필요 — clean CDP profile에서는 메일 접속 불가")
                print("  → 기존 screen_texts 데이터로 시뮬레이션 계속 진행")
                ALL_RESULTS["errors"].append({
                    "label": "mail_crawl",
                    "error": "Not logged in to Naver Works — using existing data",
                })
                try:
                    httpx.put(f"{CDP}/json/close/{tab_id}", timeout=5)
                except Exception:
                    pass
                return False

            # Get mail subjects
            mail_js = """
            (function() {
                var items = document.querySelectorAll('.subject, [class*=mail_item] .subject');
                if (!items.length) items = document.querySelectorAll('[class*=subject]');
                var results = [];
                for (var i = 0; i < Math.min(items.length, 10); i++) {
                    var text = items[i].textContent.trim()
                        .replace(/^내가 수신인에 포함된 메일메일 제목:/, '').trim();
                    results.push(text.slice(0, 80));
                }
                return results;
            })()
            """
            inbox_subjects = await cdp_eval(ws, mail_js, rid=10)

            if inbox_subjects:
                print(f"  받은메일 {len(inbox_subjects)}건 감지:")
                for i, s in enumerate(inbox_subjects[:10]):
                    print(f"    {i+1}. {s[:60]}")

                # Extract each mail by clicking
                for i in range(min(len(inbox_subjects), 10)):
                    click_js = f"""
                    (function() {{
                        var items = document.querySelectorAll('.subject, [class*=mail_item] .subject');
                        if (!items.length) items = document.querySelectorAll('[class*=subject]');
                        if (items[{i}]) {{ items[{i}].click(); return true; }}
                        return false;
                    }})()
                    """
                    clicked = await cdp_eval(ws, click_js, rid=100 + i*10)
                    await asyncio.sleep(5)

                    text = await cdp_eval(ws, "document.body.innerText.slice(0, 2000)", rid=101 + i*10)
                    title = await cdp_eval(ws, "document.title", rid=102 + i*10)
                    text_len = len(text) if text else 0

                    # Push to server
                    record = {
                        "app_name": "네이버 웍스 메일",
                        "window_title": title or f"메일 #{i+1}",
                        "extracted_text": text or "",
                        "text_length": text_len,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                    try:
                        async with httpx.AsyncClient(timeout=10) as c:
                            await c.post(f"{SERVER}/api/v1/push/screen-text",
                                         json={"records": [record]})
                    except Exception:
                        pass

                    subject = inbox_subjects[i] if i < len(inbox_subjects) else "?"
                    mail_results.append({
                        "type": "inbox",
                        "index": i+1,
                        "subject": subject[:60],
                        "text_len": text_len,
                        "success": text_len > 50,
                    })
                    print(f"  메일 #{i+1}: {text_len:,}자 {'OK' if text_len > 50 else 'FAIL'} — {subject[:40]}")

                    # Go back via browser back
                    await cdp_eval(ws, "window.history.back()", rid=103 + i*10)
                    await asyncio.sleep(3)
            else:
                print("  받은메일함 비어있거나 감지 실패")

    except Exception as e:
        print(f"  [ERR] inbox ws: {e}")
        ALL_RESULTS["errors"].append({"label": "inbox_ws", "error": str(e)})

    # Close inbox tab
    try:
        httpx.put(f"{CDP}/json/close/{tab_id}", timeout=5)
    except Exception:
        pass

    # Sent folder in new tab
    print("\n[보낸메일함]")
    try:
        r = httpx.put(f"{CDP}/json/new?https://mail.worksmobile.com/w/sent", timeout=10)
        tab_info = r.json()
        ws_url = tab_info.get("webSocketDebuggerUrl")
        tab_id = tab_info.get("id")
        await asyncio.sleep(8)

        async with websockets.connect(ws_url, close_timeout=15) as ws:
            current_url = await cdp_eval(ws, "window.location.href", rid=1)
            if current_url and "auth" in current_url.lower():
                print("  보낸메일함도 로그인 필요 — 건너뜀")
            else:
                sent_js = """
                (function() {
                    var items = document.querySelectorAll('.subject, [class*=subject]');
                    var results = [];
                    for (var i = 0; i < Math.min(items.length, 5); i++) {
                        results.push(items[i].textContent.trim().slice(0, 80));
                    }
                    return results;
                })()
                """
                sent_subjects = await cdp_eval(ws, sent_js, rid=10)
                if sent_subjects:
                    print(f"  보낸메일 {len(sent_subjects)}건 감지")
                    for i in range(min(len(sent_subjects), 5)):
                        click_js = f"""
                        (function() {{
                            var items = document.querySelectorAll('.subject, [class*=subject]');
                            if (items[{i}]) {{ items[{i}].click(); return true; }}
                            return false;
                        }})()
                        """
                        await cdp_eval(ws, click_js, rid=200 + i*10)
                        await asyncio.sleep(5)
                        text = await cdp_eval(ws, "document.body.innerText.slice(0, 2000)", rid=201 + i*10)
                        text_len = len(text) if text else 0

                        record = {
                            "app_name": "네이버 웍스 보낸메일",
                            "window_title": f"보낸메일 #{i+1}",
                            "extracted_text": text or "",
                            "text_length": text_len,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                        try:
                            async with httpx.AsyncClient(timeout=10) as c:
                                await c.post(f"{SERVER}/api/v1/push/screen-text",
                                             json={"records": [record]})
                        except Exception:
                            pass

                        mail_results.append({
                            "type": "sent",
                            "index": i+1,
                            "subject": sent_subjects[i][:60] if i < len(sent_subjects) else "?",
                            "text_len": text_len,
                            "success": text_len > 50,
                        })
                        print(f"  보낸메일 #{i+1}: {text_len:,}자 {'OK' if text_len > 50 else 'FAIL'}")
                        await cdp_eval(ws, "window.history.back()", rid=202 + i*10)
                        await asyncio.sleep(3)

        try:
            httpx.put(f"{CDP}/json/close/{tab_id}", timeout=5)
        except Exception:
            pass

    except Exception as e:
        print(f"  [ERR] sent folder: {e}")

    ALL_RESULTS["cdp_crawls"].extend(mail_results)

    total = len(mail_results)
    success = sum(1 for m in mail_results if m.get("success"))
    print(f"\n  메일 크롤링 합계: {success}/{total} ({100*success//max(total,1)}%)")
    return total > 0


async def section_0930_work():
    """09:30 업무 시작 — 업무 사이트 순회."""
    print("\n" + "=" * 60)
    print("09:30 업무 사이트 순회")
    print("=" * 60)

    sites = [
        ("Google Calendar", "https://calendar.google.com", 15),
        ("Google 검색 (2026 법인세율)", "https://www.google.com/search?q=2026%EB%85%84+%EB%B2%95%EC%9D%B8%EC%84%B8%EC%9C%A8+%EB%B3%80%EA%B2%BD", 15),
        ("국가법령정보센터", "https://law.go.kr", 20),
        ("전자공시시스템 DART", "https://dart.fss.or.kr", 20),
    ]

    for name, url, dwell in sites:
        print(f"\n[{name}]")
        await open_tab_and_crawl(url, name, dwell_seconds=dwell)


async def section_0940_check():
    """09:40 중간 확인 — 자비스에게 질문."""
    print("\n" + "=" * 60)
    print("09:40 중간 확인")
    print("=" * 60)

    questions = [
        ("아까 열어본 메일 중에 답장 안 한 거 있어?", "미답장 확인"),
        ("할 일 추가해줘. 오늘까지 월간 보고서 작성", "할일 추가"),
        ("할 일 보여줘", "할일 조회"),
    ]

    for text, label in questions:
        print(f"\n[{label}]")
        resp = await api_call("POST", "/api/v1/command",
                              {"text": text}, label)
        ALL_RESULTS["commands"].append({"cmd": text, "resp": resp})


async def section_0945_leisure():
    """09:45 점심 전 잡무 — 비업무 활동."""
    print("\n" + "=" * 60)
    print("09:45 점심 전 잡무 (비업무 — 뉴스, 날씨, 유튜브)")
    print("=" * 60)

    sites = [
        ("네이버 뉴스 경제", "https://news.naver.com/section/101", 10),
        ("네이버 뉴스 기사", "https://news.naver.com/section/101", 10),
        ("네이버 뉴스 IT", "https://news.naver.com/section/105", 10),
        ("네이버 날씨", "https://weather.naver.com/", 8),
        ("유튜브", "https://www.youtube.com/", 10),
    ]

    for name, url, dwell in sites:
        print(f"\n[{name}]")
        await open_tab_and_crawl(url, name, dwell_seconds=dwell)


async def section_0955_wrapup():
    """09:55 퇴근 시뮬레이션."""
    print("\n" + "=" * 60)
    print("09:55 퇴근 시뮬레이션")
    print("=" * 60)

    # "자비스, 오늘 뭐했어?"
    print("\n[오늘 뭐했어?]")
    resp = await api_call("POST", "/api/v1/command",
                          {"text": "오늘 뭐했어?"}, "하루 종합")
    ALL_RESULTS["commands"].append({"cmd": "오늘 뭐했어?", "resp": resp})

    # Evening briefing
    print("\n[저녁 브리핑]")
    briefing = await api_call("POST", "/api/v1/data/briefing",
                              {"type": "evening"}, "저녁 브리핑")
    if briefing:
        ALL_RESULTS["briefings"].append({"type": "evening", "content": briefing})

    # Productivity score
    print("\n[생산성 점수]")
    score = await api_call("GET", "/api/v1/data/productivity/score", label="생산성 점수")
    ALL_RESULTS["commands"].append({"cmd": "생산성 점수", "resp": score})


async def main():
    print("=" * 60)
    print(f"Phase 1: 사무직 업무 시뮬레이션 — {datetime.now().isoformat()}")
    print("=" * 60)

    overall_start = time.time()

    # === Run all sections ===
    await section_0900_morning()
    await section_0915_mail()
    await section_0930_work()
    await section_0940_check()
    await section_0945_leisure()
    await section_0955_wrapup()

    elapsed_total = round(time.time() - overall_start, 1)

    # === Summary ===
    print("\n" + "=" * 60)
    print(f"Phase 1 완료 — 총 {elapsed_total}초")
    print("=" * 60)

    api_ok = sum(1 for a in ALL_RESULTS["api_calls"] if a["status"] == 200)
    api_total = len(ALL_RESULTS["api_calls"])
    cdp_ok = sum(1 for c in ALL_RESULTS["cdp_crawls"] if c.get("success"))
    cdp_total = len(ALL_RESULTS["cdp_crawls"])
    cmd_total = len(ALL_RESULTS["commands"])
    err_total = len(ALL_RESULTS["errors"])
    briefing_count = len(ALL_RESULTS["briefings"])

    print(f"  API 호출: {api_ok}/{api_total} 성공")
    print(f"  CDP 크롤: {cdp_ok}/{cdp_total} 성공")
    print(f"  명령어: {cmd_total}회")
    print(f"  브리핑: {briefing_count}건")
    print(f"  에러: {err_total}건")

    # Save results
    results_path = "tests/simulation_results.json"
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(ALL_RESULTS, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n  결과 저장: {results_path}")


if __name__ == "__main__":
    asyncio.run(main())
