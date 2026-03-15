"""Phase 2: Detailed workday simulation — accounting team at pharma company."""

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
ALL = {"api": [], "cdp": [], "errors": []}


def api(method, path, body=None, label=""):
    start = time.time()
    if method == "GET":
        r = httpx.get(f"{SERVER}{path}", timeout=30)
    else:
        r = httpx.post(f"{SERVER}{path}", json=body or {}, timeout=30)
    elapsed = round(time.time() - start, 2)
    try:
        data = r.json()
    except Exception:
        data = r.text
    reply = ""
    if isinstance(data, dict):
        reply = data.get("reply", data.get("content", ""))
        if not reply:
            reply = json.dumps(data, ensure_ascii=False)[:500]
    else:
        reply = str(data)[:500]
    display = reply[:300] + "..." if len(reply) > 300 else reply
    ALL["api"].append({
        "label": label, "status": r.status_code,
        "elapsed": elapsed, "response": reply[:500],
    })
    print(f"[{label}] {r.status_code} ({elapsed}s)")
    print(f"  {display}")
    print()
    return data


async def cdp_eval(ws, expr, rid=1):
    await ws.send(json.dumps({
        "id": rid, "method": "Runtime.evaluate",
        "params": {"expression": expr, "returnByValue": True},
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


async def crawl(name, url, dwell=8):
    start = time.time()
    try:
        r = httpx.put(f"{CDP}/json/new?{url}", timeout=10)
        tab = r.json()
    except Exception as e:
        print(f"  [ERR] {name}: {e}")
        ALL["errors"].append({"site": name, "error": str(e)})
        return
    ws_url = tab.get("webSocketDebuggerUrl")
    tab_id = tab.get("id")
    try:
        async with websockets.connect(ws_url, close_timeout=15) as ws:
            await asyncio.sleep(dwell)
            title = await cdp_eval(ws, "document.title", rid=1)
            text = await cdp_eval(ws, "document.body.innerText.slice(0, 2000)", rid=2)
    except Exception:
        title, text = None, None
    text_len = len(text) if text else 0
    elapsed = round(time.time() - start, 1)
    record = {
        "app_name": name,
        "window_title": title or name,
        "extracted_text": text or "",
        "text_length": text_len,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(f"{SERVER}/api/v1/push/screen-text", json={"records": [record]})
    except Exception:
        pass
    try:
        httpx.put(f"{CDP}/json/close/{tab_id}", timeout=5)
    except Exception:
        pass
    ok = text_len > 50
    ALL["cdp"].append({"site": name, "text_len": text_len, "ok": ok, "elapsed": elapsed})
    status = "OK" if ok else "FAIL"
    print(f"  [{status}] {name}: {text_len:,}자 ({elapsed}s)")


async def run_cdp_crawl():
    sites = [
        ("국세청 홈택스", "https://www.hometax.go.kr", 10),
        ("DART 전자공시", "https://dart.fss.or.kr", 10),
        ("Google: 분기결산 체크리스트", "https://www.google.com/search?q=%EB%B6%84%EA%B8%B0%EA%B2%B0%EC%82%B0+%EC%B2%B4%ED%81%AC%EB%A6%AC%EC%8A%A4%ED%8A%B8+%ED%9A%8C%EA%B3%84", 8),
        ("Google: K-IFRS 1036 자산손상", "https://www.google.com/search?q=K-IFRS+1036+%EC%9E%90%EC%82%B0%EC%86%90%EC%83%81", 8),
        ("한국회계기준원", "https://www.kasb.or.kr", 8),
        ("대웅제약 홈페이지", "https://www.daewoong.co.kr", 8),
        ("네이버 증권 대웅제약", "https://finance.naver.com/item/main.naver?code=069620", 10),
        ("네이버 뉴스 경제", "https://news.naver.com/section/101", 8),
        ("네이버 날씨", "https://weather.naver.com/", 6),
        ("유튜브", "https://www.youtube.com/", 6),
    ]
    for name, url, dwell in sites:
        await crawl(name, url, dwell)


def main():
    start_time = time.time()

    print("=" * 70)
    print(f"Phase 2: 상세 업무 시뮬레이션 — {datetime.now().isoformat()}")
    print("=" * 70)

    # ━━━ 08:50 아침 브리핑 ━━━
    print("\n━━━ 08:50 아침 브리핑 ━━━")
    api("POST", "/api/v1/data/briefing", {"type": "morning"}, "아침 브리핑")

    # ━━━ 09:00 일정/메일 확인 ━━━
    print("━━━ 09:00 출근 — 일정/메일 ━━━")
    api("POST", "/api/v1/command", {"text": "오늘 일정 알려줘"}, "일정 확인")
    api("POST", "/api/v1/command", {"text": "미답장 메일 있어?"}, "미답장 메일")
    api("POST", "/api/v1/command", {"text": "미답장 메일 중에 긴급한 거 뭐야?"}, "긴급 미답장")

    # ━━━ 09:15 SAP 질문 ━━━
    print("━━━ 09:15 SAP 작업 준비 ━━━")
    api("POST", "/api/v1/command",
        {"text": "SAP AS01 트랜잭션으로 고정자산 등록하려면 뭐가 필요해?"}, "SAP 질문")
    api("POST", "/api/v1/command",
        {"text": "고정자산 감가상각 내용연수 기준이 어떻게 돼?"}, "감가상각")

    # ━━━ 09:30 메일 답장 ━━━
    print("━━━ 09:30 메일 답장 ━━━")
    api("POST", "/api/v1/command",
        {"text": "임상민 팀장한테 연구인력개발비 세액공제 관련 답장 초안 만들어줘. 필요 자료 리스트 포함."},
        "답장 초안 1")
    api("POST", "/api/v1/command",
        {"text": "idsTrust 온라인 자산 실사 협조 요청에 답장 초안. 3/20까지 일정 조율 내용으로."},
        "답장 초안 2")

    # ━━━ 09:45 할 일 관리 ━━━
    print("━━━ 09:45 할 일 관리 ━━━")
    api("POST", "/api/v1/command",
        {"text": "할 일 추가해줘. 금요일까지 분기결산 감사보고서 자료 준비"}, "할일 추가 1")
    api("POST", "/api/v1/command",
        {"text": "할 일 추가해줘. 내일까지 엠서클 세금계산서 발행 확인"}, "할일 추가 2")
    api("POST", "/api/v1/command", {"text": "할 일 보여줘"}, "할일 조회")

    # ━━━ 10:00 회의 등록 ━━━
    print("━━━ 10:00 회의 등록 ━━━")
    api("POST", "/api/v1/command",
        {"text": "내일 오후 2시에 분기결산 검토 회의 등록해줘. 회의실 A, 1시간"},
        "캘린더 등록 1")
    api("POST", "/api/v1/command",
        {"text": "다음 주 월요일 오전 10시에 고정자산 실사 킥오프 등록해줘"},
        "캘린더 등록 2")

    # ━━━ 10:15 전문 지식 ━━━
    print("━━━ 10:15 전문 지식 질문 ━━━")
    api("POST", "/api/v1/command",
        {"text": "K-IFRS 1036호 자산손상 검토할 때 현금창출단위 결정 기준이 뭐야?"},
        "K-IFRS 질문")
    api("POST", "/api/v1/command",
        {"text": "법인세법 제55조의2 연구인력개발비 세액공제 대상 범위 알려줘"},
        "세법 질문")

    # ━━━ 10:30 중간 점검 ━━━
    print("━━━ 10:30 중간 점검 ━━━")
    api("POST", "/api/v1/command", {"text": "오늘 뭐했어?"}, "하루 종합")
    api("GET", "/api/v1/data/productivity/score", label="생산성 점수")

    # ━━━ CDP 크롤링 ━━━
    print("\n━━━ 업무 사이트 CDP 크롤링 ━━━")
    asyncio.run(run_cdp_crawl())

    # ━━━ 퇴근 ━━━
    print("\n━━━ 퇴근 준비 ━━━")
    api("POST", "/api/v1/command",
        {"text": "오늘 뭐했어? 상세하게 알려줘"}, "하루 종합 상세")
    api("POST", "/api/v1/data/briefing", {"type": "evening"}, "저녁 브리핑")

    # ━━━ 비용 ━━━
    print("━━━ 비용 확인 ━━━")
    cost = api("GET", "/api/v1/data/cost/summary", label="비용 요약")

    # ━━━ Google ━━━
    print("━━━ Google 연동 상태 ━━━")
    api("GET", "/api/v1/data/google/status", label="Google 상태")

    # ━━━ Summary ━━━
    elapsed_total = round(time.time() - start_time, 1)
    print("\n" + "=" * 70)
    print(f"Phase 2 완료 — 총 {elapsed_total}초")
    print("=" * 70)
    api_ok = sum(1 for a in ALL["api"] if a["status"] == 200)
    cdp_ok = sum(1 for c in ALL["cdp"] if c["ok"])
    print(f"  API: {api_ok}/{len(ALL['api'])} 성공")
    print(f"  CDP: {cdp_ok}/{len(ALL['cdp'])} 성공")
    print(f"  에러: {len(ALL['errors'])}")

    if isinstance(cost, dict):
        print(f"\n  === 비용 분석 ===")
        print(f"  총 API 호출: {cost.get('total_calls', 0)}회")
        print(f"  총 비용: ${cost.get('total_cost_usd', 0)}")
        print(f"  입력 토큰: {cost.get('total_input_tokens', 0):,}")
        print(f"  출력 토큰: {cost.get('total_output_tokens', 0):,}")
        print(f"  일간 추정: ${cost.get('daily_estimate_usd', 0)}")
        print(f"  월간 추정: ${cost.get('monthly_estimate_usd', 0)}")
        by_model = cost.get("by_model", {})
        for model, data in by_model.items():
            print(f"    {model}: {data['calls']}회, ${data['cost_usd']}")

    with open("tests/phase2_detailed_results.json", "w", encoding="utf-8") as f:
        json.dump(ALL, f, ensure_ascii=False, indent=2)
    print(f"\n  결과 저장: tests/phase2_detailed_results.json")


if __name__ == "__main__":
    main()
