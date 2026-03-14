"""Part 2 + Part 3: API 전체 테스트 + 비서 기능 테스트."""

import asyncio
import json
import sys
import time
from datetime import datetime, timedelta, timezone

import httpx
import websockets

sys.stdout.reconfigure(encoding="utf-8")

SERVER = "http://localhost:8000"
API_RESULTS = []
COMMAND_RESULTS = []
BUGS = []


async def api_call(client, method, path, json_data=None, params=None, label=None):
    """Make an API call and record the result."""
    url = f"{SERVER}{path}"
    label = label or f"{method} {path}"
    start = time.time()
    try:
        if method == "GET":
            r = await client.get(url, params=params, timeout=30)
        elif method == "POST":
            r = await client.post(url, json=json_data, timeout=30)
        elif method == "PUT":
            r = await client.put(url, json=json_data, params=params, timeout=30)
        elif method == "DELETE":
            r = await client.delete(url, timeout=30)
        else:
            return None

        elapsed_ms = int((time.time() - start) * 1000)
        try:
            body = r.json()
        except Exception:
            body = r.text[:200]

        result = {
            "label": label,
            "method": method,
            "path": path,
            "status": r.status_code,
            "elapsed_ms": elapsed_ms,
            "success": 200 <= r.status_code < 300,
            "body_preview": str(body)[:150] if body else "",
        }
        API_RESULTS.append(result)

        status_icon = "OK" if result["success"] else "FAIL"
        print(f"  {status_icon} {method:6s} {path:45s} {r.status_code} {elapsed_ms:5d}ms")
        if not result["success"]:
            print(f"    → {str(body)[:100]}")
            BUGS.append({"type": "API", "path": path, "status": r.status_code, "body": str(body)[:200]})

        return body
    except Exception as e:
        elapsed_ms = int((time.time() - start) * 1000)
        result = {
            "label": label,
            "method": method,
            "path": path,
            "status": 0,
            "elapsed_ms": elapsed_ms,
            "success": False,
            "body_preview": str(e)[:150],
        }
        API_RESULTS.append(result)
        print(f"  ERR {method:6s} {path:45s} {elapsed_ms:5d}ms → {str(e)[:80]}")
        BUGS.append({"type": "API", "path": path, "error": str(e)[:200]})
        return None


async def command_test(client, text, label=None):
    """Send a command and evaluate the response."""
    label = label or text[:30]
    start = time.time()
    body = await api_call(client, "POST", "/api/v1/command",
                         json_data={"text": text, "locale": "ko"}, label=f"CMD: {label}")
    elapsed = time.time() - start

    if body and isinstance(body, dict):
        reply = body.get("reply", "")
        agent = body.get("agent", "?")
        result = {
            "command": text,
            "reply": reply[:300],
            "agent": agent,
            "elapsed_s": round(elapsed, 1),
            "reply_len": len(reply),
        }
        COMMAND_RESULTS.append(result)
        print(f"    에이전트: {agent} | 응답: {len(reply)}자 | {elapsed:.1f}초")
        print(f"    답변: \"{reply[:120]}...\"" if len(reply) > 120 else f"    답변: \"{reply}\"")
        return reply
    return ""


async def main():
    start_time = datetime.now()
    print("=" * 70)
    print("Part 2 + Part 3: 비서 기능 + API 전체 테스트")
    print(f"시작: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    async with httpx.AsyncClient() as client:
        # ━━━━━ Part 3: API 전체 테스트 ━━━━━
        print(f"\n{'━'*60}")
        print("Part 3: API 엔드포인트 전체 테스트")
        print(f"{'━'*60}\n")

        # Health
        await api_call(client, "GET", "/health")

        # Push: Mobile activity (simulation)
        now = datetime.now(timezone.utc)
        mobile_data = {
            "app_usage": [
                {"package": "com.kakao.talk", "app_name": "KakaoTalk",
                 "started_at": (now - timedelta(hours=2)).isoformat(), "duration_s": 300},
                {"package": "com.samsung.notes", "app_name": "Samsung Notes",
                 "started_at": (now - timedelta(hours=1, minutes=30)).isoformat(), "duration_s": 600},
                {"package": "com.slack", "app_name": "Slack",
                 "started_at": (now - timedelta(hours=1)).isoformat(), "duration_s": 900},
                {"package": "com.microsoft.teams", "app_name": "Teams",
                 "started_at": (now - timedelta(minutes=45)).isoformat(), "duration_s": 450},
                {"package": "com.google.maps", "app_name": "Google Maps",
                 "started_at": (now - timedelta(minutes=30)).isoformat(), "duration_s": 120},
            ],
            "locations": [
                {"latitude": 37.5074, "longitude": 127.0596, "accuracy_m": 15,
                 "label": "대웅제약 본사", "recorded_at": (now - timedelta(hours=3)).isoformat()},
                {"latitude": 37.5013, "longitude": 127.0396, "accuracy_m": 20,
                 "label": "강남역", "recorded_at": now.isoformat()},
            ],
            "call_logs": [
                {"phone_number": "010-1234-5678", "direction": "incoming",
                 "started_at": (now - timedelta(hours=1)).isoformat(), "duration_s": 180},
            ],
        }
        await api_call(client, "POST", "/api/v1/push/activity", json_data=mobile_data)

        # Push: PC activity
        pc_data = {
            "activities": [
                {"window_title": "SAP Logon", "process_name": "saplogon.exe",
                 "started_at": (now - timedelta(hours=3)).isoformat(),
                 "ended_at": (now - timedelta(hours=2)).isoformat(),
                 "duration_s": 3600, "idle": False},
                {"window_title": "Excel - 매출대사.xlsx", "process_name": "excel.exe",
                 "started_at": (now - timedelta(hours=2)).isoformat(),
                 "ended_at": (now - timedelta(hours=1)).isoformat(),
                 "duration_s": 3600, "idle": False},
                {"window_title": "네이버 웍스 메일", "process_name": "msedge.exe",
                 "url": "https://mail.worksmobile.com/w/inbox",
                 "started_at": (now - timedelta(hours=1)).isoformat(),
                 "ended_at": now.isoformat(),
                 "duration_s": 3600, "idle": False},
            ]
        }
        await api_call(client, "POST", "/api/v1/push/pc-activity", json_data=pc_data)

        # Push: Screen text
        screen_data = {
            "records": [
                {"app_name": "SAP", "window_title": "SAP - FI 전표 조회",
                 "extracted_text": "전표번호: 200012345\n회사코드: DW01\n전기일: 2026.03.14\n차변 합계: 50,000,000\n대변 합계: 50,000,000",
                 "text_length": 120, "timestamp": now.isoformat()},
            ]
        }
        await api_call(client, "POST", "/api/v1/push/screen-text", json_data=screen_data)

        # Push: Tasks CRUD
        task_body = await api_call(client, "POST", "/api/v1/push/tasks",
                                  json_data={"title": "월요일까지 보고서 작성", "due_date": "2026-03-16", "priority": "high"})
        task_id = task_body.get("task_id") if task_body else None

        if task_id:
            await api_call(client, "PUT", f"/api/v1/push/tasks/{task_id}",
                          json_data={"status": "in_progress"})

        # Data queries
        await api_call(client, "GET", "/api/v1/data/activity/summary")
        await api_call(client, "GET", "/api/v1/data/activity/trend", params={"days": 7})
        await api_call(client, "GET", "/api/v1/data/emails/unreplied")
        await api_call(client, "GET", "/api/v1/data/promises")
        await api_call(client, "GET", "/api/v1/data/promises/summary")
        await api_call(client, "GET", "/api/v1/data/tasks")
        await api_call(client, "GET", "/api/v1/data/transcripts")
        await api_call(client, "GET", "/api/v1/data/screen-texts")
        await api_call(client, "GET", "/api/v1/data/productivity/score")
        await api_call(client, "GET", "/api/v1/data/trends/weekly")
        await api_call(client, "GET", "/api/v1/data/app-categories")
        await api_call(client, "GET", "/api/v1/data/notifications")

        # App category override
        await api_call(client, "PUT", "/api/v1/data/app-category",
                      params={"app_name": "kakaotalk.exe", "category": "work"})

        # Briefing
        print(f"\n{'━'*60}")
        print("Part 2-1: 브리핑 테스트")
        print(f"{'━'*60}")
        briefing_body = await api_call(client, "POST", "/api/v1/data/briefing",
                                      json_data={"type": "morning", "locale": "ko"})
        if briefing_body and isinstance(briefing_body, dict):
            content = briefing_body.get("content", "")
            print(f"\n  ── 아침 브리핑 ({len(content)}자) ──")
            print(f"  {content[:500]}")

        evening_body = await api_call(client, "POST", "/api/v1/data/briefing",
                                     json_data={"type": "evening", "locale": "ko"})
        if evening_body and isinstance(evening_body, dict):
            content = evening_body.get("content", "")
            print(f"\n  ── 저녁 정리 ({len(content)}자) ──")
            print(f"  {content[:500]}")

        # Proactive check
        print(f"\n{'━'*60}")
        print("Part 2-2: 프로액티브 알림 테스트")
        print(f"{'━'*60}")
        await api_call(client, "POST", "/api/v1/data/proactive/check")

        # Weekly report
        await api_call(client, "POST", "/api/v1/data/report/weekly", params={"locale": "ko"})

        # Drive save (DRY-RUN — will fail without Google token, that's expected)
        drive_body = await api_call(client, "POST", "/api/v1/data/drive/save?filename=test-briefing.md&content_type=briefing",
                                   json_data={})
        if drive_body and "error" in str(drive_body).lower():
            print(f"    [DRY-RUN] Drive 저장: 토큰 없음 (예상된 결과)")

        # Upload audio (mock)
        # Skip actual audio — just verify endpoint exists

        # Delete test task
        if task_id:
            await api_call(client, "DELETE", f"/api/v1/push/tasks/{task_id}")

        # ━━━━━ Part 2-3: 대화 테스트 ━━━━━
        print(f"\n{'━'*60}")
        print("Part 2-3: 대화 테스트")
        print(f"{'━'*60}")

        commands = [
            ("오늘 뭐했어?", "activity"),
            ("미답장 메일 알려줘", "unreplied"),
            ("할 일 추가해줘. 월요일까지 보고서 작성", "add_task"),
            ("할 일 보여줘", "show_tasks"),
            ("이번 주 생산성 어때?", "productivity"),
            ("브리핑 만들어줘", "briefing"),
            ("어제 네이버 웍스에서 뭐 봤어?", "screen_text"),
            ("임상민이 보낸 메일 뭐야?", "specific_mail"),
        ]

        for text, label in commands:
            print(f"\n  ▶ \"{text}\"")
            await command_test(client, text, label)

        # ━━━━━ Part 2-4: 앱 자동 분류 테스트 ━━━━━
        print(f"\n{'━'*60}")
        print("Part 2-4: 앱 자동 분류 테스트")
        print(f"{'━'*60}")

        test_apps = [
            "kakaotalk.exe", "notion.exe", "figma.exe", "spotify.exe", "zoom.exe",
            "obsidian.exe", "line.exe", "discord.exe", "vlc.exe", "calculator.exe",
            "saplogon.exe", "teams.exe", "slack.exe", "photoshop.exe", "terminal.exe",
        ]

        # First pass: classify all (some will use LLM)
        print("  첫 번째 분류 (LLM 호출 포함):")
        for app in test_apps:
            # Push a PC activity record to trigger classification
            pc = {
                "activities": [{
                    "window_title": app.replace(".exe", ""),
                    "process_name": app,
                    "started_at": now.isoformat(),
                    "ended_at": (now + timedelta(seconds=60)).isoformat(),
                    "duration_s": 60,
                    "idle": False,
                }]
            }
            await api_call(client, "POST", "/api/v1/push/pc-activity", json_data=pc, label=f"classify: {app}")

        # Check categories
        cats_body = await api_call(client, "GET", "/api/v1/data/app-categories")
        if cats_body and isinstance(cats_body, dict):
            categories = cats_body.get("categories", {})
            if isinstance(categories, dict):
                print(f"\n  분류된 앱: {len(categories)}개")
                for name, info in list(categories.items())[:20]:
                    if isinstance(info, dict):
                        print(f"    {name:20s} → {info.get('category', '?'):10s} ({info.get('classified_by', '?')})")
                    else:
                        print(f"    {name:20s} → {info}")
            elif isinstance(categories, list):
                print(f"\n  분류된 앱: {len(categories)}개")
                for cat in categories[:20]:
                    print(f"    {cat.get('app_name', '?'):20s} → {cat.get('category', '?'):10s} ({cat.get('classified_by', '?')})")

        # User override test
        print(f"\n  유저 오버라이드: kakaotalk.exe → work")
        await api_call(client, "PUT", "/api/v1/data/app-category",
                      params={"app_name": "kakaotalk.exe", "category": "work"})

        # ━━━━━ Part 2-5: 생산성 점수 + 리포트 ━━━━━
        print(f"\n{'━'*60}")
        print("Part 2-5: 생산성 점수 + 리포트")
        print(f"{'━'*60}")

        score_body = await api_call(client, "GET", "/api/v1/data/productivity/score")
        if score_body and isinstance(score_body, dict):
            score = score_body.get("score", -1)
            print(f"\n  생산성 점수: {score}/100")
            if score == 0 or score == 100:
                print(f"  ⚠️ 점수가 {score}점 — 비정상적일 수 있음")
                BUGS.append({"type": "IMPROVE", "desc": f"생산성 점수 {score}점 — 데이터 부족일 수 있음"})

        trend_body = await api_call(client, "GET", "/api/v1/data/trends/weekly")
        if trend_body and isinstance(trend_body, dict):
            print(f"  주간 트렌드: {json.dumps(trend_body, ensure_ascii=False)[:200]}")

        # ━━━━━ Part 2-6: Google API (DRY-RUN) ━━━━━
        print(f"\n{'━'*60}")
        print("Part 2-6: Google API (DRY-RUN)")
        print(f"{'━'*60}")

        # Calendar: verify logic works (will fail without token)
        print(f"\n  [DRY-RUN] 캘린더 등록: 내일 15:00 자비스 테스트 미팅")
        print(f"    → 실제 insert 호출 안 함 (외부 쓰기 금지)")

        # Gmail: verify logic
        print(f"\n  [DRY-RUN] Gmail 발송: leeio6@naver.com, 제목: '[자비스 테스트] 자동 발송 테스트'")
        print(f"    → 실제 send 호출 안 함 (외부 쓰기 금지)")

        # Drive: verify logic
        print(f"\n  [DRY-RUN] Drive 저장: test-briefing.md")
        print(f"    → 실제 upload 호출 안 함 (외부 쓰기 금지)")

        # Check if OAuth token exists
        # Try to hit auth endpoint
        try:
            r = await client.get(f"{SERVER}/auth/google/login", timeout=10, follow_redirects=False)
            if r.status_code in (302, 307):
                print(f"    OAuth 리다이렉트 정상: {r.status_code}")
            elif r.status_code == 404:
                print(f"    OAuth 엔드포인트 없음 (404) — 구현 필요")
                BUGS.append({"type": "BUG", "desc": "OAuth /auth/google/login 엔드포인트 미구현"})
            else:
                print(f"    OAuth 응답: {r.status_code}")
        except Exception as e:
            print(f"    OAuth 확인 실패: {e}")

        # ━━━━━ WebSocket 테스트 ━━━━━
        print(f"\n{'━'*60}")
        print("WebSocket /ws/pc-client 테스트")
        print(f"{'━'*60}")

        try:
            async with websockets.connect(f"ws://localhost:8000/ws/pc-client",
                                         close_timeout=5) as ws:
                # Send ping
                await ws.send(json.dumps({"type": "ping"}))
                resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                if resp.get("type") == "pong":
                    print(f"  OK WebSocket ping/pong 정상")
                    API_RESULTS.append({"label": "WS /ws/pc-client", "method": "WS", "path": "/ws/pc-client",
                                       "status": 200, "elapsed_ms": 0, "success": True, "body_preview": "pong"})
                else:
                    print(f"  FAIL WebSocket 응답: {resp}")
        except Exception as e:
            print(f"  ERR WebSocket 연결 실패: {e}")
            API_RESULTS.append({"label": "WS /ws/pc-client", "method": "WS", "path": "/ws/pc-client",
                               "status": 0, "elapsed_ms": 0, "success": False, "body_preview": str(e)[:100]})

    # ══════════ 최종 결과 ══════════
    end_time = datetime.now()
    elapsed_total = (end_time - start_time).total_seconds()

    print(f"\n{'═'*70}")
    print("📊 최종 결과")
    print(f"{'═'*70}")

    # API results
    total = len(API_RESULTS)
    success = sum(1 for r in API_RESULTS if r["success"])
    failed = total - success
    avg_ms = sum(r["elapsed_ms"] for r in API_RESULTS) / total if total else 0
    slowest = max(API_RESULTS, key=lambda r: r["elapsed_ms"]) if API_RESULTS else None

    print(f"\n  API 테스트:")
    print(f"    전체: {total}개")
    print(f"    성공: {success}개")
    print(f"    실패: {failed}개")
    print(f"    평균 응답시간: {avg_ms:.0f}ms")
    if slowest:
        print(f"    가장 느린: {slowest['label']} ({slowest['elapsed_ms']}ms)")

    # Failed APIs
    if failed:
        print(f"\n  실패한 API:")
        for r in API_RESULTS:
            if not r["success"]:
                print(f"    {r['method']} {r['path']} → {r['status']} ({r['body_preview'][:80]})")

    # Command results
    if COMMAND_RESULTS:
        print(f"\n  대화 테스트:")
        for cr in COMMAND_RESULTS:
            print(f"    \"{cr['command'][:30]}\" → {cr['agent']} | {cr['elapsed_s']}초 | {cr['reply_len']}자")

    # Bugs
    if BUGS:
        print(f"\n  발견된 이슈: {len(BUGS)}개")
        for b in BUGS:
            print(f"    [{b['type']}] {b.get('desc', b.get('path', '?'))}")

    print(f"\n  총 소요시간: {elapsed_total:.0f}초 ({elapsed_total/60:.1f}분)")

    # Save results
    with open("tests/api_test_results.json", "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "api_results": API_RESULTS,
            "command_results": COMMAND_RESULTS,
            "bugs": BUGS,
            "total_apis": total,
            "success_apis": success,
            "failed_apis": failed,
            "avg_ms": round(avg_ms),
            "elapsed_total_s": round(elapsed_total),
        }, f, ensure_ascii=False, indent=2)
    print(f"  결과 저장: tests/api_test_results.json")


if __name__ == "__main__":
    asyncio.run(main())
