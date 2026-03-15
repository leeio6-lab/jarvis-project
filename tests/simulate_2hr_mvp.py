"""2-hour MVP stress test — "Does this feel like a $4.99 secretary?"

The test simulates a REAL workday with realistic timing and sequence.
After each work block, we ask Jarvis questions that a real user would ask.
We grade not just "did it answer" but "was the answer USEFUL?"

Key test dimensions:
1. MEMORY — Does Jarvis remember what I did 30 minutes ago?
2. CONTEXT — Does Jarvis connect the dots? (e.g., "I searched K-IFRS → opened DART → the mail about 손상검토 is related")
3. PROACTIVE — Does Jarvis tell me things I didn't ask?
4. SPECIFICITY — Does Jarvis give me specific answers with actual data, not generic advice?
5. SPEED — Is the response fast enough that I'd actually use it?
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

LOG = {
    "start": datetime.now(timezone.utc).isoformat(),
    "work_blocks": [],
    "jarvis_tests": [],
    "cdp_crawls": [],
    "scores": {},
}


def jarvis(text, label="", expect=""):
    """Ask Jarvis and evaluate response quality."""
    start = time.time()
    try:
        r = httpx.post(f"{SERVER}/api/v1/command", json={"text": text}, timeout=30)
        elapsed = round(time.time() - start, 2)
        data = r.json()
        reply = data.get("reply", str(data))
    except Exception as e:
        elapsed = round(time.time() - start, 2)
        reply = f"ERROR: {e}"

    # Evaluate quality
    quality = {
        "useful": False,
        "specific": False,
        "remembered_context": False,
        "had_real_data": False,
    }
    reply_lower = reply.lower()
    # Check if answer contains specific data (numbers, names, dates)
    import re
    has_numbers = bool(re.search(r'\d{4}[-/]\d{2}[-/]\d{2}|\d+건|\d+시간|\d+분', reply))
    has_names = any(name in reply for name in ['SAP', '대웅', '임상민', '엠서클', '세금계산서', 'K-IFRS', '홈택스', 'DART'])
    generic_phrases = ['도움이 필요하시면', '알려주시면', '더 궁금한', '추가로 도움']
    is_generic = sum(1 for p in generic_phrases if p in reply) >= 2

    quality["specific"] = has_numbers or has_names
    quality["had_real_data"] = '없습니다' not in reply and '없었' not in reply and has_names
    quality["useful"] = quality["specific"] and not is_generic

    entry = {
        "label": label,
        "question": text,
        "reply": reply[:600],
        "elapsed_s": elapsed,
        "quality": quality,
        "expect": expect,
    }
    LOG["jarvis_tests"].append(entry)

    status = "GOOD" if quality["useful"] else "MEH " if quality["specific"] else "FAIL"
    print(f"  [{status}] {label} ({elapsed}s)")
    print(f"    Q: {text[:80]}")
    print(f"    A: {reply[:250]}")
    if expect:
        print(f"    EXPECT: {expect}")
    print()
    return reply


def briefing(btype="morning"):
    start = time.time()
    r = httpx.post(f"{SERVER}/api/v1/data/briefing", json={"type": btype}, timeout=30)
    elapsed = round(time.time() - start, 2)
    data = r.json()
    content = data.get("content", "")
    print(f"  [{btype} 브리핑] ({elapsed}s)")
    print(f"    {content[:400]}")
    print()
    LOG["work_blocks"].append({
        "type": f"{btype}_briefing",
        "elapsed_s": elapsed,
        "content": content[:800],
    })
    return content


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


async def browse(name, url, dwell=10, push=True):
    """Browse a site, extract text, push to server."""
    start = time.time()
    try:
        r = httpx.put(f"{CDP}/json/new?{url}", timeout=10)
        tab = r.json()
    except Exception as e:
        print(f"    [ERR] {name}: {e}")
        return ""
    ws_url = tab.get("webSocketDebuggerUrl")
    tab_id = tab.get("id")
    text = ""
    title = ""
    try:
        async with websockets.connect(ws_url, close_timeout=15) as ws:
            await asyncio.sleep(dwell)
            title = await cdp_eval(ws, "document.title", rid=1) or ""
            text = await cdp_eval(ws, "document.body.innerText.slice(0, 3000)", rid=2) or ""
    except Exception:
        pass
    elapsed = round(time.time() - start, 1)
    text_len = len(text)

    if push and text_len > 30:
        record = {
            "app_name": name,
            "window_title": title or name,
            "extracted_text": text[:2000],
            "text_length": min(text_len, 2000),
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
    LOG["cdp_crawls"].append({"site": name, "text_len": text_len, "ok": ok, "elapsed": elapsed})
    status = "OK" if ok else "FAIL"
    print(f"    [{status}] {name}: {text_len:,}자 ({elapsed}s)")
    return text


def section(title):
    print(f"\n{'='*70}")
    print(f"  {title} — {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*70}\n")


async def work_block_1():
    """08:50-09:15 출근 — 브리핑 받고, 메일/일정 확인."""
    section("BLOCK 1: 출근 루틴 (08:50-09:15)")

    # Briefing
    briefing("morning")

    # Questions a real person would ask their secretary
    jarvis("오늘 일정 알려줘", "일정확인",
           "예정된 일정 있으면 구체적으로, 없으면 '없습니다'")
    jarvis("미답장 메일 있어? 급한 거 먼저 알려줘", "미답장메일",
           "건수 + 급한 거 제목/발신자")
    jarvis("오늘 할 일 보여줘", "할일목록",
           "마감일 임박 순서로 전체 목록")


async def work_block_2():
    """09:15-09:45 업무 #1 — SAP 고정자산 관련 검색+학습."""
    section("BLOCK 2: SAP 고정자산 업무 (09:15-09:45)")

    # Browse work-related sites
    await browse("Google: SAP AS01 고정자산 등록", "https://www.google.com/search?q=SAP+AS01+%EA%B3%A0%EC%A0%95%EC%9E%90%EC%82%B0+%EB%93%B1%EB%A1%9D+%EC%A0%88%EC%B0%A8", 10)
    await browse("Google: 고정자산 감가상각 내용연수", "https://www.google.com/search?q=%EA%B3%A0%EC%A0%95%EC%9E%90%EC%82%B0+%EA%B0%90%EA%B0%80%EC%83%81%EA%B0%81+%EB%82%B4%EC%9A%A9%EC%97%B0%EC%88%98+%EA%B8%B0%EC%A4%80", 8)
    await browse("국세청 홈택스", "https://www.hometax.go.kr", 12)
    await browse("DART 전자공시", "https://dart.fss.or.kr", 10)

    # After browsing, ask Jarvis context-aware questions
    print("  --- 자비스에게 맥락 질문 ---")
    jarvis("아까 내가 검색한 거 뭐야?", "검색기억",
           "SAP AS01, 감가상각 내용연수 등 방금 검색한 내용을 언급해야")
    jarvis("SAP AS01에서 고정자산 등록할 때 필요한 게 뭐야?", "SAP질문",
           "구체적인 필수 항목 리스트")
    jarvis("고정자산 내용연수 기준 알려줘. 건물이랑 차량", "감가상각",
           "건물 20-40년, 차량 4-5년 등 구체 수치")


async def work_block_3():
    """09:45-10:15 업무 #2 — 분기결산 관련 조사."""
    section("BLOCK 3: 분기결산 조사 (09:45-10:15)")

    await browse("Google: 분기결산 체크리스트 회계", "https://www.google.com/search?q=%EB%B6%84%EA%B8%B0%EA%B2%B0%EC%82%B0+%EC%B2%B4%ED%81%AC%EB%A6%AC%EC%8A%A4%ED%8A%B8+%ED%9A%8C%EA%B3%84", 8)
    await browse("Google: K-IFRS 1036 자산손상 현금창출단위", "https://www.google.com/search?q=K-IFRS+1036+%EC%9E%90%EC%82%B0%EC%86%90%EC%83%81+%ED%98%84%EA%B8%88%EC%B0%BD%EC%B6%9C%EB%8B%A8%EC%9C%84", 8)
    await browse("한국회계기준원", "https://www.kasb.or.kr", 10)
    await browse("Google: 법인세법 연구인력개발비 세액공제", "https://www.google.com/search?q=%EB%B2%95%EC%9D%B8%EC%84%B8%EB%B2%95+%EC%97%B0%EA%B5%AC%EC%9D%B8%EB%A0%A5%EA%B0%9C%EB%B0%9C%EB%B9%84+%EC%84%B8%EC%95%A1%EA%B3%B5%EC%A0%9C", 8)

    print("  --- 자비스에게 맥락 질문 ---")
    jarvis("지금까지 뭐 검색했어?", "검색히스토리",
           "SAP, 감가상각, 분기결산, K-IFRS, 세액공제 등 전체 검색 히스토리")
    jarvis("K-IFRS 1036호에서 현금창출단위 결정 기준이 뭐야?", "K-IFRS",
           "독립적 현금흐름 창출 가능한 최소 단위 등 구체 기준")
    jarvis("분기결산할 때 빠뜨리기 쉬운 거 뭐야?", "결산팁",
           "구체적인 체크포인트 — 미지급비용, 충당금, 선급비용 등")


async def work_block_4():
    """10:15-10:45 업무 #3 — 메일 답장 + 할일 관리."""
    section("BLOCK 4: 메일 답장 + 할일 (10:15-10:45)")

    jarvis("임상민 팀장한테 연구인력개발비 세액공제 자료 요청 답장 써줘. 구체적인 필요 자료 리스트 포함해서.", "답장초안1",
           "메일 형식, 비즈니스 톤, 구체 자료 리스트")
    jarvis("idsTrust 온라인 자산 실사 협조 요청에 답장 써줘. 3/20까지 완료 예정이고, 실사 대상 자산 목록 요청하는 내용으로.", "답장초안2",
           "일정+요청 내용 포함된 비즈니스 메일")
    jarvis("할 일 추가해줘. 이번 주 금요일까지 감사보고서 자료 정리", "할일추가")
    jarvis("내일 오후 2시에 분기결산 회의 등록해줘. 1시간, 회의실 B", "캘린더등록")
    jarvis("이번 주 할 일 뭐가 있어? 마감 임박한 순서로", "할일우선순위",
           "마감일 기준 정렬된 할일 목록")


async def work_block_5():
    """10:45-11:15 비업무 + 잡무."""
    section("BLOCK 5: 비업무 + 잡무 (10:45-11:15)")

    await browse("네이버 뉴스 경제", "https://news.naver.com/section/101", 10)
    await browse("네이버 증권 대웅제약", "https://finance.naver.com/item/main.naver?code=069620", 12)
    await browse("네이버 날씨", "https://weather.naver.com/", 6)
    await browse("유튜브", "https://www.youtube.com/", 8)
    await browse("쿠팡", "https://www.coupang.com", 6)

    print("  --- 자비스에게 맥락 질문 ---")
    jarvis("대웅제약 주가 지금 얼마야?", "주가",
           "screen_texts에서 네이버 증권 데이터 추출해야")
    jarvis("오늘 날씨 어때?", "날씨",
           "screen_texts에서 날씨 데이터 추출해야")
    jarvis("오늘 업무 외에 뭐 했어?", "비업무파악",
           "유튜브, 쿠팡, 부동산 등 비업무 활동을 정확히 구분해야")


async def work_block_6():
    """11:15-11:45 추가 업무 사이트."""
    section("BLOCK 6: 추가 업무 (11:15-11:45)")

    await browse("Google: 세금계산서 발행 방법", "https://www.google.com/search?q=%EC%84%B8%EA%B8%88%EA%B3%84%EC%82%B0%EC%84%9C+%EB%B0%9C%ED%96%89+%EB%B0%A9%EB%B2%95+%ED%99%88%ED%83%9D%EC%8A%A4", 8)
    await browse("Google: 대웅제약 IR 사업보고서", "https://www.google.com/search?q=%EB%8C%80%EC%9B%85%EC%A0%9C%EC%95%BD+IR+%EC%82%AC%EC%97%85%EB%B3%B4%EA%B3%A0%EC%84%9C+2025", 8)
    await browse("Google: 엑셀 피벗테이블 사용법", "https://www.google.com/search?q=%EC%97%91%EC%85%80+%ED%94%BC%EB%B2%97%ED%85%8C%EC%9D%B4%EB%B8%94+%EC%82%AC%EC%9A%A9%EB%B2%95", 8)
    await browse("Google: SAP FI 전표 입력", "https://www.google.com/search?q=SAP+FI+%EC%A0%84%ED%91%9C+%EC%9E%85%EB%A0%A5+FB50", 8)

    print("  --- 자비스에게 최종 질문 ---")
    jarvis("오늘 하루 뭐했어? 상세하게 정리해줘", "하루종합상세",
           "모든 업무 활동 + 검색 내용 + 방문 사이트를 시간순/카테고리별로")
    jarvis("오늘 검색한 것 중에 분기결산이랑 관련된 것만 정리해줘", "주제별필터",
           "분기결산 관련 검색만 필터링해서 보여줘야")
    jarvis("내가 SAP 관련해서 뭘 검색했었어?", "SAP검색회상",
           "AS01, FB50 등 SAP 관련 검색만 뽑아서 보여줘야")


async def work_block_7():
    """11:45-12:00 퇴근 마무리."""
    section("BLOCK 7: 퇴근 마무리 (11:45-12:00)")

    # Evening briefing
    briefing("evening")

    # Final questions
    jarvis("내일 뭐 해야 해?", "내일준비",
           "마감 임박 할일 + 내일 일정 + 미답장 메일 중 내일까지 처리할 것")
    jarvis("이번 주 가장 중요한 일이 뭐야?", "주간우선순위",
           "마감일 기준으로 이번 주 할일 정리")
    jarvis("생산성 점수 어때?", "생산성",
           "점수 + 구체적 개선 제안")

    # Get cost
    r = httpx.get(f"{SERVER}/api/v1/data/cost/summary", timeout=10)
    cost = r.json()
    LOG["cost"] = cost
    print(f"\n  === 비용 ===")
    print(f"  총 호출: {cost.get('total_calls', 0)}회")
    print(f"  총 비용: ${cost.get('total_cost_usd', 0)}")
    print(f"  월간 추정: ${cost.get('monthly_estimate_usd', 0)}")


async def main():
    overall_start = time.time()

    print("=" * 70)
    print("  2시간 MVP 테스트 — '이 비서에게 $4.99를 낼 가치가 있는가?'")
    print(f"  시작: {datetime.now().isoformat()}")
    print("=" * 70)

    await work_block_1()
    await work_block_2()
    await work_block_3()
    await work_block_4()
    await work_block_5()
    await work_block_6()
    await work_block_7()

    elapsed_total = round(time.time() - overall_start, 1)

    # ── Final scoring ──
    section(f"최종 결과 — {elapsed_total}초 ({elapsed_total/60:.1f}분)")

    tests = LOG["jarvis_tests"]
    total = len(tests)
    useful = sum(1 for t in tests if t["quality"]["useful"])
    specific = sum(1 for t in tests if t["quality"]["specific"])
    had_data = sum(1 for t in tests if t["quality"]["had_real_data"])
    avg_latency = sum(t["elapsed_s"] for t in tests) / max(total, 1)

    cdp_total = len(LOG["cdp_crawls"])
    cdp_ok = sum(1 for c in LOG["cdp_crawls"] if c["ok"])

    print(f"  자비스 질문: {total}회")
    print(f"  유용한 답변: {useful}/{total} ({100*useful//max(total,1)}%)")
    print(f"  구체적 답변: {specific}/{total} ({100*specific//max(total,1)}%)")
    print(f"  실데이터 포함: {had_data}/{total} ({100*had_data//max(total,1)}%)")
    print(f"  평균 응답시간: {avg_latency:.1f}초")
    print(f"  CDP 크롤: {cdp_ok}/{cdp_total}")

    # Score
    scores = {
        "useful_rate": round(useful / max(total, 1) * 10, 1),
        "specific_rate": round(specific / max(total, 1) * 10, 1),
        "data_rate": round(had_data / max(total, 1) * 10, 1),
        "speed": min(10, round(10 - (avg_latency - 3) * 2, 1)),  # 3s=10, 8s=0
        "crawl": round(cdp_ok / max(cdp_total, 1) * 10, 1),
    }
    overall = round(sum(scores.values()) / len(scores), 1)
    scores["overall"] = overall
    LOG["scores"] = scores

    print(f"\n  === MVP 점수 ===")
    for k, v in scores.items():
        print(f"    {k}: {v}/10")
    print(f"\n  진짜 비서 같은가? {'YES' if overall >= 7 else 'NO'}")
    print(f"  $4.99 낼 가치? {'YES' if overall >= 7 else 'NO'}")

    LOG["end"] = datetime.now(timezone.utc).isoformat()
    LOG["elapsed_total_s"] = elapsed_total
    with open("tests/mvp_2hr_results.json", "w", encoding="utf-8") as f:
        json.dump(LOG, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n  결과 저장: tests/mvp_2hr_results.json")


if __name__ == "__main__":
    asyncio.run(main())
