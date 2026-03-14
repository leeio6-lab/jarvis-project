"""
Jarvis Live Testing Script - Continuous Improvement Cycle
Phase 1: Real-use testing + Phase 2: Scoring
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

import httpx
import asyncio
import json
import time
import traceback

BASE = "http://localhost:8000"
CDP_URL = "http://127.0.0.1:9222"

all_results = {}

# ============================================================
# HELPER
# ============================================================
async def timed_post(client, url, json_body=None):
    t0 = time.time()
    r = await client.post(url, json=json_body)
    return r, time.time() - t0

async def timed_get(client, url):
    t0 = time.time()
    r = await client.get(url)
    return r, time.time() - t0


# ============================================================
# TEST 1: Morning Briefing
# ============================================================
async def test_morning_briefing(client):
    print("=" * 70)
    print("TEST 1: MORNING BRIEFING (출근 시뮬레이션)")
    print("=" * 70)

    r, elapsed = await timed_post(client, f"{BASE}/api/v1/data/briefing",
                                   {"type": "morning", "locale": "ko"})
    data = r.json()
    content = data.get("content", "")

    print(f"Status: {r.status_code}")
    print(f"Generation Time: {elapsed:.2f}s")
    print(f"Character Count: {len(content)}")
    print(f"Date: {data.get('date', '?')}")
    print()
    print("--- Full Briefing Text ---")
    print(content)
    print("--- End ---")
    print()

    checks = {
        "mentions_mail": any(kw in content for kw in ["메일", "mail", "받은", "보낸", "편지"]),
        "mentions_specific_person": any(kw in content for kw in ["임상민", "세금계산서", "고정자산"]),
        "mentions_calendar": any(kw in content for kw in ["일정", "캘린더", "회의", "스케줄", "calendar"]),
        "mentions_pc_activity": any(kw in content for kw in ["PC", "활동", "사용", "작업", "앱", "브라우저", "화면"]),
        "has_action_items": any(kw in content for kw in ["해야", "필요", "확인", "처리", "추천", "제안", "할 일", "해주세요", "하세요"]),
        "natural_tone": len(content) > 50,
    }

    print("Evaluation:")
    for k, v in checks.items():
        print(f"  {k}: {'YES' if v else 'NO'}")

    all_results["morning_briefing"] = {
        "status": r.status_code,
        "time": elapsed,
        "char_count": len(content),
        "content": content,
        "checks": checks,
    }


# ============================================================
# TEST 2: CDP Mail Crawl
# ============================================================
async def test_cdp_mail_crawl():
    print()
    print("=" * 70)
    print("TEST 2: CDP MAIL CRAWL (5 mails from inbox)")
    print("=" * 70)

    try:
        import websockets
        # Get tabs
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{CDP_URL}/json")
        tabs = resp.json()

        print(f"CDP Tabs found: {len(tabs)}")
        for i, t in enumerate(tabs):
            print(f"  [{i}] {t.get('title', '?')[:50]} | {t.get('url', '?')[:60]}")

        # Find worksmobile tab or first available
        ws_url = None
        for t in tabs:
            if "worksmobile" in t.get("url", "") or "naver" in t.get("url", ""):
                ws_url = t.get("webSocketDebuggerUrl")
                print(f"\nUsing tab: {t.get('title', '?')[:50]}")
                break
        if not ws_url:
            # Use first tab with webSocketDebuggerUrl
            for t in tabs:
                if t.get("webSocketDebuggerUrl"):
                    ws_url = t.get("webSocketDebuggerUrl")
                    print(f"\nUsing first available tab: {t.get('title', '?')[:50]}")
                    break

        if not ws_url:
            print("ERROR: No tab with webSocketDebuggerUrl found")
            all_results["cdp_mail_crawl"] = {"status": "FAIL", "reason": "no_ws_url"}
            return

        # Connect via websocket
        async with websockets.connect(ws_url, max_size=10*1024*1024) as ws:
            msg_id = 1

            async def send_cdp(method, params=None):
                nonlocal msg_id
                cmd = {"id": msg_id, "method": method}
                if params:
                    cmd["params"] = params
                msg_id += 1
                await ws.send(json.dumps(cmd))
                # Drain messages until we find our response
                while True:
                    raw = await asyncio.wait_for(ws.recv(), timeout=30)
                    data = json.loads(raw)
                    if data.get("id") == msg_id - 1:
                        return data
                    # else it's an event, skip

            async def navigate_and_wait(url, wait_s=5):
                resp = await send_cdp("Page.navigate", {"url": url})
                await asyncio.sleep(wait_s)
                # Drain any pending events
                try:
                    while True:
                        await asyncio.wait_for(ws.recv(), timeout=0.5)
                except asyncio.TimeoutError:
                    pass
                return resp

            async def get_text():
                resp = await send_cdp("Runtime.evaluate", {
                    "expression": "document.body ? document.body.innerText.substring(0, 3000) : 'NO_BODY'",
                    "returnByValue": True
                })
                result = resp.get("result", {}).get("result", {})
                return result.get("value", "ERROR")

            async def get_links():
                resp = await send_cdp("Runtime.evaluate", {
                    "expression": """
                    (function(){
                        var links = [];
                        var els = document.querySelectorAll('a[href]');
                        for(var i=0; i<els.length && links.length<30; i++){
                            var href = els[i].href;
                            var text = els[i].innerText.trim().substring(0,100);
                            if(text.length > 0) links.push({href: href, text: text});
                        }
                        return JSON.stringify(links);
                    })()
                    """,
                    "returnByValue": True
                })
                result = resp.get("result", {}).get("result", {})
                val = result.get("value", "[]")
                try:
                    return json.loads(val)
                except:
                    return []

            # Enable Page events
            await send_cdp("Page.enable")
            await send_cdp("Runtime.enable")

            # Navigate to mail inbox
            print("\nNavigating to mail inbox...")
            await navigate_and_wait("https://mail.worksmobile.com/w/inbox", wait_s=7)
            text = await get_text()
            print(f"Inbox text length: {len(text)}")
            print(f"Inbox preview: {text[:300]}...")

            # Get mail links
            links = await get_links()
            mail_links = [l for l in links if "mail" in l.get("href", "").lower() or len(l.get("text", "")) > 5]
            print(f"\nFound {len(mail_links)} potential mail links")
            for i, l in enumerate(mail_links[:10]):
                print(f"  [{i}] {l['text'][:60]} -> {l['href'][:80]}")

            # Try to open 5 mails
            mail_results = []
            opened = 0
            for link in mail_links[:10]:
                if opened >= 5:
                    break
                href = link.get("href", "")
                subj = link.get("text", "?")[:60]
                if not href or href.startswith("javascript:"):
                    continue

                print(f"\n  Opening mail [{opened+1}]: {subj}")
                try:
                    await navigate_and_wait(href, wait_s=4)
                    mail_text = await get_text()
                    mail_results.append({
                        "subject": subj,
                        "status": "OK",
                        "text_length": len(mail_text),
                        "preview": mail_text[:200]
                    })
                    print(f"    Status: OK | Text length: {len(mail_text)}")
                    print(f"    Preview: {mail_text[:150]}...")
                    opened += 1
                except Exception as e:
                    mail_results.append({"subject": subj, "status": "FAIL", "error": str(e)})
                    print(f"    Status: FAIL | {e}")
                    opened += 1

            print(f"\nMail crawl summary: {sum(1 for m in mail_results if m['status']=='OK')}/{len(mail_results)} succeeded")
            all_results["cdp_mail_crawl"] = {
                "status": "OK",
                "mails_found": len(mail_links),
                "mails_opened": mail_results,
            }

    except Exception as e:
        print(f"CDP MAIL CRAWL ERROR: {e}")
        traceback.print_exc()
        all_results["cdp_mail_crawl"] = {"status": "FAIL", "error": str(e)}


# ============================================================
# TEST 3: Tab Switching
# ============================================================
async def test_tab_switching():
    print()
    print("=" * 70)
    print("TEST 3: TAB SWITCHING")
    print("=" * 70)

    try:
        import websockets
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{CDP_URL}/json")
        tabs = resp.json()

        ws_url = None
        for t in tabs:
            if t.get("webSocketDebuggerUrl"):
                ws_url = t.get("webSocketDebuggerUrl")
                break

        if not ws_url:
            print("ERROR: No CDP tab available")
            all_results["tab_switching"] = {"status": "FAIL", "reason": "no_ws_url"}
            return

        async with websockets.connect(ws_url, max_size=10*1024*1024) as ws:
            msg_id = 100

            async def send_cdp(method, params=None):
                nonlocal msg_id
                cmd = {"id": msg_id, "method": method}
                if params:
                    cmd["params"] = params
                msg_id += 1
                await ws.send(json.dumps(cmd))
                while True:
                    raw = await asyncio.wait_for(ws.recv(), timeout=30)
                    data = json.loads(raw)
                    if data.get("id") == msg_id - 1:
                        return data

            async def navigate_and_wait(url, wait_s=5):
                await send_cdp("Page.navigate", {"url": url})
                await asyncio.sleep(wait_s)
                try:
                    while True:
                        await asyncio.wait_for(ws.recv(), timeout=0.5)
                except asyncio.TimeoutError:
                    pass

            async def get_text():
                resp = await send_cdp("Runtime.evaluate", {
                    "expression": "document.body ? document.body.innerText.substring(0, 3000) : 'NO_BODY'",
                    "returnByValue": True
                })
                return resp.get("result", {}).get("result", {}).get("value", "ERROR")

            await send_cdp("Page.enable")
            await send_cdp("Runtime.enable")

            tab_results = {}

            # Tab 1: Naver News
            print("\n[1] Navigating to https://news.naver.com/ ...")
            t0 = time.time()
            await navigate_and_wait("https://news.naver.com/", wait_s=5)
            text1 = await get_text()
            elapsed1 = time.time() - t0
            tab_results["naver_news"] = {
                "status": "OK" if len(text1) > 50 else "FAIL",
                "text_length": len(text1),
                "time": elapsed1,
                "preview": text1[:300]
            }
            print(f"  Status: {'OK' if len(text1) > 50 else 'FAIL'} | Length: {len(text1)} | Time: {elapsed1:.1f}s")
            print(f"  Preview: {text1[:200]}...")

            # Tab 2: Google search
            print("\n[2] Navigating to Google search for 법인세 개정안 2026 ...")
            t0 = time.time()
            await navigate_and_wait("https://www.google.com/search?q=법인세+개정안+2026", wait_s=5)
            text2 = await get_text()
            elapsed2 = time.time() - t0
            tab_results["google_search"] = {
                "status": "OK" if len(text2) > 50 else "FAIL",
                "text_length": len(text2),
                "time": elapsed2,
                "preview": text2[:300]
            }
            print(f"  Status: {'OK' if len(text2) > 50 else 'FAIL'} | Length: {len(text2)} | Time: {elapsed2:.1f}s")
            print(f"  Preview: {text2[:200]}...")

            # Tab 3: Back to mail
            print("\n[3] Navigating back to https://mail.worksmobile.com/w/inbox ...")
            t0 = time.time()
            await navigate_and_wait("https://mail.worksmobile.com/w/inbox", wait_s=7)
            text3 = await get_text()
            elapsed3 = time.time() - t0
            tab_results["mail_return"] = {
                "status": "OK" if len(text3) > 50 else "FAIL",
                "text_length": len(text3),
                "time": elapsed3,
                "preview": text3[:300]
            }
            print(f"  Status: {'OK' if len(text3) > 50 else 'FAIL'} | Length: {len(text3)} | Time: {elapsed3:.1f}s")
            print(f"  Preview: {text3[:200]}...")

            all_results["tab_switching"] = tab_results

    except Exception as e:
        print(f"TAB SWITCHING ERROR: {e}")
        traceback.print_exc()
        all_results["tab_switching"] = {"status": "FAIL", "error": str(e)}


# ============================================================
# TEST 4: Conversation Tests
# ============================================================
async def test_conversations(client):
    print()
    print("=" * 70)
    print("TEST 4: CONVERSATION TESTS")
    print("=" * 70)

    commands = [
        "미답장 메일 알려줘",
        "할 일 추가해줘. 월요일까지 주간 보고 작성",
        "할 일 보여줘",
        "임상민이 보낸 메일 뭐야?",
        "이번 주 생산성 어때?",
        "어제 네이버 웍스에서 뭐 봤어?",
    ]

    conv_results = []
    for i, cmd in enumerate(commands):
        print(f"\n[{i+1}] Command: \"{cmd}\"")
        t0 = time.time()
        try:
            r = await client.post(f"{BASE}/api/v1/command", json={"text": cmd, "locale": "ko"})
            elapsed = time.time() - t0
            data = r.json()
            reply = data.get("reply", "")
            agent = data.get("agent", "?")

            print(f"  Status: {r.status_code} | Agent: {agent} | Time: {elapsed:.2f}s")
            print(f"  Reply: {reply}")

            conv_results.append({
                "command": cmd,
                "status": r.status_code,
                "reply": reply,
                "agent": agent,
                "time": elapsed,
            })
        except Exception as e:
            elapsed = time.time() - t0
            print(f"  ERROR: {e}")
            conv_results.append({
                "command": cmd,
                "status": "ERROR",
                "error": str(e),
                "time": elapsed,
            })

    all_results["conversations"] = conv_results


# ============================================================
# TEST 5: Evening Briefing
# ============================================================
async def test_evening_briefing(client):
    print()
    print("=" * 70)
    print("TEST 5: EVENING BRIEFING (퇴근 시뮬레이션)")
    print("=" * 70)

    # 5a: "오늘 뭐했어?" via command
    print("\n[5a] Command: '오늘 뭐했어?'")
    r1, t1 = await timed_post(client, f"{BASE}/api/v1/command",
                               {"text": "오늘 뭐했어?", "locale": "ko"})
    d1 = r1.json()
    print(f"  Status: {r1.status_code} | Time: {t1:.2f}s")
    print(f"  Reply: {d1.get('reply', '')}")

    # 5b: Evening briefing
    print("\n[5b] Evening Briefing:")
    r2, t2 = await timed_post(client, f"{BASE}/api/v1/data/briefing",
                               {"type": "evening", "locale": "ko"})
    d2 = r2.json()
    content2 = d2.get("content", "")
    print(f"  Status: {r2.status_code} | Time: {t2:.2f}s")
    print(f"  Character Count: {len(content2)}")
    print(f"  --- Full Evening Briefing ---")
    print(f"  {content2}")
    print(f"  --- End ---")

    # 5c: Productivity score
    print("\n[5c] Productivity Score:")
    r3, t3 = await timed_get(client, f"{BASE}/api/v1/data/productivity/score")
    d3 = r3.json()
    print(f"  Status: {r3.status_code} | Time: {t3:.2f}s")
    print(f"  Score Data: {json.dumps(d3, ensure_ascii=False, indent=2)}")

    all_results["evening"] = {
        "command_reply": d1.get("reply", ""),
        "command_time": t1,
        "briefing_content": content2,
        "briefing_time": t2,
        "briefing_char_count": len(content2),
        "productivity_score": d3,
        "productivity_time": t3,
    }


# ============================================================
# MAIN
# ============================================================
async def main():
    async with httpx.AsyncClient(timeout=120) as client:
        # Test 1: Morning Briefing
        try:
            await test_morning_briefing(client)
        except Exception as e:
            print(f"TEST 1 ERROR: {e}")
            traceback.print_exc()
            all_results["morning_briefing"] = {"status": "ERROR", "error": str(e)}

        # Test 4: Conversations (do before CDP to avoid tab issues)
        try:
            await test_conversations(client)
        except Exception as e:
            print(f"TEST 4 ERROR: {e}")
            traceback.print_exc()
            all_results["conversations"] = {"status": "ERROR", "error": str(e)}

        # Test 5: Evening Briefing
        try:
            await test_evening_briefing(client)
        except Exception as e:
            print(f"TEST 5 ERROR: {e}")
            traceback.print_exc()
            all_results["evening"] = {"status": "ERROR", "error": str(e)}

    # Test 2: CDP Mail Crawl
    try:
        await test_cdp_mail_crawl()
    except Exception as e:
        print(f"TEST 2 ERROR: {e}")
        traceback.print_exc()
        all_results["cdp_mail_crawl"] = {"status": "ERROR", "error": str(e)}

    # Test 3: Tab Switching
    try:
        await test_tab_switching()
    except Exception as e:
        print(f"TEST 3 ERROR: {e}")
        traceback.print_exc()
        all_results["tab_switching"] = {"status": "ERROR", "error": str(e)}

    # Save raw results
    with open("test_live_results.json", "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2, default=str)
    print("\n\nRaw results saved to test_live_results.json")

asyncio.run(main())
